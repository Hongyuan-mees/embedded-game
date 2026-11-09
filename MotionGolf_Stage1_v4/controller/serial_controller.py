"""STM32 USB CDC input, independent of Pygame.

Call update() once per game frame, then read roll, pitch and jump. roll/pitch
are normalized acceleration inputs. jump is latched for that update only.
Upward mode requires v2 samples and a settled pose after connection or timeout.
Explicit legacy mode requires a valid JUMP:0 before a rising-edge jump event.
The serial factory and monotonic clock can be injected for hardware-free tests.
"""

from collections import deque
from dataclasses import dataclass
import math
from statistics import fmean
import time

from .upward_jump import UpwardJumpDetector


@dataclass(frozen=True)
class MotionPacket:
    roll: float
    pitch: float
    jump: bool
    tick_ms: int | None = None
    accel_raw: tuple[int, int, int] | None = None
    gyro_raw: tuple[int, int, int] | None = None


def parse_packet(line: str) -> MotionPacket | None:
    """Accept legacy v1 or complete v2 fields; reject partial/unknown formats."""
    fields = {}
    for item in line.strip().split(","):
        name, separator, value = item.partition(":")
        name, value = name.strip(), value.strip()
        if not separator or name in fields:
            return None
        fields[name] = value
    base = {"ROLL", "PITCH", "JUMP"}
    extended = {"V", "T", "AX", "AY", "AZ", "GX", "GY", "GZ"}
    if set(fields) not in (base, base | extended) or fields["JUMP"] not in {"0", "1"}:
        return None
    try:
        roll, pitch = float(fields["ROLL"]), float(fields["PITCH"])
    except ValueError:
        return None
    if not (math.isfinite(roll) and math.isfinite(pitch)):
        return None
    if not (-180 <= roll <= 180 and -90 <= pitch <= 90):
        return None
    if set(fields) == base:
        return MotionPacket(roll, pitch, fields["JUMP"] == "1")
    if fields["V"] != "2":
        return None
    try:
        tick = int(fields["T"])
        raw = tuple(int(fields[key]) for key in ("AX", "AY", "AZ", "GX", "GY", "GZ"))
    except ValueError:
        return None
    if not 0 <= tick <= 0xFFFFFFFF or any(not -32768 <= value <= 32767 for value in raw):
        return None
    return MotionPacket(roll, pitch, fields["JUMP"] == "1", tick, raw[:3], raw[3:])


@dataclass(frozen=True)
class ControllerConfig:
    dead_zone_deg: float = 4.0
    full_scale_deg: float = 25.0
    swap_axes: bool = False
    invert_roll: bool = False
    invert_pitch: bool = False
    data_timeout: float = 0.25
    calibration_samples: int = 25
    calibration_spread_deg: float = 2.0
    max_read_bytes: int = 4096
    max_line_bytes: int = 256
    jump_mode: str = "upward"
    jump_threshold_g: float = UpwardJumpDetector.DEFAULT_THRESHOLD
    connection_timeout: float = 3.0

    def __post_init__(self):
        if self.jump_mode not in {"legacy", "upward"}:
            raise ValueError("jump_mode must be legacy or upward")
        UpwardJumpDetector(self.jump_threshold_g)
        if not (math.isfinite(self.dead_zone_deg) and math.isfinite(self.full_scale_deg)
                and 0 <= self.dead_zone_deg < self.full_scale_deg <= 180):
            raise ValueError("Require 0 <= dead zone < full scale <= 180 degrees")
        if not math.isfinite(self.data_timeout) or self.data_timeout <= 0:
            raise ValueError("data_timeout must be positive and finite")
        if not math.isfinite(self.connection_timeout) or self.connection_timeout < self.data_timeout:
            raise ValueError("connection_timeout must be finite and at least data_timeout")
        if not math.isfinite(self.calibration_spread_deg) or self.calibration_spread_deg <= 0:
            raise ValueError("calibration_spread_deg must be positive and finite")
        for name in ("calibration_samples", "max_read_bytes", "max_line_bytes"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.max_read_bytes < self.max_line_bytes:
            raise ValueError("max_read_bytes must be at least max_line_bytes")


def _angle_difference(angle, reference):
    return (angle - reference + 180.0) % 360.0 - 180.0


class SerialController:
    """Explicit connection lifecycle; no automatic COM selection or reconnect.

    connected means a fresh valid control packet has arrived, whereas is_open
    only means the OS port is open. Calibration collects a stable pose window;
    input stays neutral while collecting. Axis inversion applies
    to the output axes after any swap. Defaults await physical orientation tests.
    """

    def __init__(self, config=None, *, serial_factory=None, clock=time.monotonic):
        self.config = config if config is not None else ControllerConfig()
        self._serial_factory = serial_factory
        self._clock = clock
        self._serial = None
        self.port = None
        self.last_error = None
        self.last_sensor_error = None
        self.connected = False
        self.roll = self.pitch = 0.0
        self.jump = False
        self.raw_roll = self.raw_pitch = None
        self.calibrated = False
        self.calibrating = False
        self._roll_zero = self._pitch_zero = 0.0
        self._samples = deque(maxlen=self.config.calibration_samples)
        self._buffer = bytearray()
        self._discard_until_newline = False
        self._partial_since = None
        self._last_packet_at = None
        self._waiting_since = None
        self._previous_jump = None
        self.protocol_version = None
        self.detector = UpwardJumpDetector(self.config.jump_threshold_g)

    @property
    def is_open(self):
        return self._serial is not None and self._serial.is_open

    @staticmethod
    def available_ports():
        """Return (device, description) pairs for an explicit user selection."""
        from serial.tools import list_ports
        return [(item.device, item.description) for item in list_ports.comports()]

    @staticmethod
    def detect_port():
        """Suggest only a unique matching CDC device; multiple matches need selection."""
        from serial.tools import list_ports
        matches = [item.device for item in list_ports.comports()
                   if item.vid == 0x0483 and item.pid == 0x5740]
        return matches[0] if len(matches) == 1 else None

    def reset_gesture(self, *, preserve_reference=False):
        """Discard gestures; UI transitions may retain the measured IMU reference."""
        self.jump = False
        self._previous_jump = None
        self.detector.reset(preserve_reference=preserve_reference)

    def set_jump_threshold(self, value):
        self.detector.set_threshold(value)
        self.jump = False

    def connect(self, port: str) -> bool:
        """Open at 115200/8N1 with nonblocking reads; failures stay recoverable."""
        previous_sensor_error = self.last_sensor_error if self.port == port else None
        self.close()
        self.last_sensor_error = previous_sensor_error
        self.last_error = None
        if not isinstance(port, str) or not port.strip():
            self.last_error = "Select a serial port"
            return False
        try:
            factory = self._serial_factory
            if factory is None:
                from serial import Serial
                factory = Serial
            self._serial = factory(port=port, baudrate=115200, bytesize=8,
                                   parity="N", stopbits=1, timeout=0, write_timeout=0)
            if not self.is_open:
                raise OSError("Serial port did not open")
            self._serial.reset_input_buffer()
            self.port = port
            self._waiting_since = self._clock()
            return True
        except (ImportError, OSError, ValueError) as exc:
            self.close()
            self.last_error = f"Cannot open serial port: {exc}"
            return False

    def close(self):
        """Release the port and forget device-specific calibration."""
        stream, self._serial = self._serial, None
        if stream is not None:
            try:
                stream.close()
            except OSError as exc:
                self.last_error = f"Cannot close serial port: {exc}"
        self.port = None
        self._invalidate()
        self._roll_zero = self._pitch_zero = 0.0
        self.calibrated = False

    def _invalidate(self):
        self.connected = False
        self.roll = self.pitch = 0.0
        self.jump = False
        self.raw_roll = self.raw_pitch = None
        self._last_packet_at = None
        self._waiting_since = None
        self._previous_jump = None
        self._buffer.clear()
        self._discard_until_newline = False
        self._partial_since = None
        self.calibrating = False
        self._samples.clear()
        self.protocol_version = None
        self.detector.reset()

    def update(self):
        """Consume at most one bounded read; never wait for a line to arrive.

        Each update clears the previous jump event. A gap beyond data_timeout
        discards queued data before resuming, preventing a delayed backlog jump.
        Without firmware timestamps, actual sensor sample age cannot be known.
        """
        self.jump = False
        now = self._clock()
        freshness_since = (self._last_packet_at if self._last_packet_at is not None
                           else self._waiting_since)
        timeout = (self.config.data_timeout if self._last_packet_at is not None
                   else self.config.connection_timeout)
        if freshness_since is not None and now - freshness_since >= timeout:
            had_packet = self._last_packet_at is not None
            self._invalidate()
            self.last_error = (self.last_sensor_error or
                               ("Control data timed out" if had_packet else
                                "No control data received: check device"))
            if self.is_open:
                try:
                    self._serial.reset_input_buffer()
                except OSError as exc:
                    self.close()
                    self.last_error = f"Serial read failed: {exc}"
            return
        if not self.is_open:
            self._invalidate()
            return
        if self._partial_since is not None and now - self._partial_since >= self.config.data_timeout:
            self._buffer.clear()
            self._partial_since = None
            self._discard_until_newline = True
        try:
            waiting = self._serial.in_waiting
            if waiting > self.config.max_read_bytes:
                self._serial.reset_input_buffer()
                self._invalidate()
                self.last_error = "Serial backlog discarded"
                return
            if waiting:
                self._receive(self._serial.read(min(waiting, self.config.max_read_bytes)), now)
        except OSError as exc:
            self.close()
            self.last_error = f"Serial read failed: {exc}"

    def _receive(self, data, now):
        for byte in data:
            if byte == 10:
                if not self._discard_until_newline:
                    try:
                        line = self._buffer.decode("ascii").strip()
                    except UnicodeDecodeError:
                        line = ""
                    if line.startswith("MPU6050_ERROR"):
                        self._invalidate()
                        self.last_sensor_error = line
                        self.last_error = line
                    else:
                        packet = parse_packet(line)
                        if packet is not None:
                            self._accept(packet, now)
                self._buffer.clear()
                self._discard_until_newline = False
                self._partial_since = None
            elif not self._discard_until_newline:
                if not self._buffer:
                    self._partial_since = now
                self._buffer.append(byte)
                if len(self._buffer) > self.config.max_line_bytes:
                    self._buffer.clear()
                    self._partial_since = None
                    self._discard_until_newline = True

    def _accept(self, packet, now):
        version = 2 if packet.accel_raw is not None else 1
        if self.protocol_version != version:
            self.reset_gesture()
        self.protocol_version = version
        self.connected = True
        self.last_error = None
        self.last_sensor_error = None
        self._last_packet_at = now
        self.raw_roll, self.raw_pitch = packet.roll, packet.pitch
        rising_edge = self._previous_jump is False and packet.jump
        self._previous_jump = packet.jump
        event = rising_edge
        if self.config.jump_mode == "upward":
            event = False
            if version == 2:
                event = self.detector.update(tuple(x / 16384.0 for x in packet.accel_raw),
                                             tuple(x / 131.0 for x in packet.gyro_raw),
                                             packet.tick_ms)
        if self.calibrating:
            moving = packet.jump if self.config.jump_mode == "legacy" else (
                version == 2 and (abs(math.sqrt(sum((x / 16384.0) ** 2
                                                    for x in packet.accel_raw)) - 1.0) > 0.08 or
                                  abs(self.detector.vertical_g) > 0.08 or
                                  self.detector.horizontal_g > 0.08 or
                                  any(abs(x / 131.0) > 35 for x in packet.gyro_raw)))
            if moving:
                self._samples.clear()
            else:
                self._samples.append((packet.roll, packet.pitch))
                self._finish_calibration()
        else:
            self.jump = self.jump or event
        if not self.calibrating:
            self._map_angles()

    def _map_angles(self):
        roll = _angle_difference(self.raw_roll, self._roll_zero)
        pitch = self.raw_pitch - self._pitch_zero
        if self.config.swap_axes:
            roll, pitch = pitch, roll
        self.roll = self._normalize(-roll if self.config.invert_roll else roll)
        self.pitch = self._normalize(-pitch if self.config.invert_pitch else pitch)

    def _normalize(self, angle):
        magnitude = abs(angle)
        if magnitude <= self.config.dead_zone_deg:
            return 0.0
        value = min(1.0, (magnitude - self.config.dead_zone_deg) /
                    (self.config.full_scale_deg - self.config.dead_zone_deg))
        return math.copysign(value, angle)

    def calibrate(self) -> bool:
        """Request a stable neutral pose window, normally 25 samples (~0.5 s)."""
        now = self._clock()
        if (not self.is_open or self._last_packet_at is None
                or now - self._last_packet_at >= self.config.data_timeout):
            return False
        self.calibrating = True
        self._samples.clear()
        self._previous_jump = None
        self.roll = self.pitch = 0.0
        self.jump = False
        self.detector.reset()
        return True

    def _finish_calibration(self):
        if len(self._samples) < self.config.calibration_samples:
            return
        reference = self._samples[0][0]
        rolls = [_angle_difference(roll, reference) for roll, _ in self._samples]
        pitches = [pitch for _, pitch in self._samples]
        if (max(rolls) - min(rolls) > self.config.calibration_spread_deg
                or max(pitches) - min(pitches) > self.config.calibration_spread_deg):
            return
        self._roll_zero = _angle_difference(reference + fmean(rolls), 0.0)
        self._pitch_zero = fmean(pitches)
        self.calibrating = False
        self.calibrated = True
        self._samples.clear()
        self.detector.reset(preserve_reference=True)
