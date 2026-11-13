"""Playable upward gestures with brief downward suppression and fixed cooldown.

Lateral motion and wrist rotation do not veto a lift. Mild downward preparation
is tolerated; occasional braking false positives are an accepted tradeoff.
"""

from collections import deque
import math


def _norm(v):
    return math.sqrt(sum(x * x for x in v))


def _unit(v):
    length = _norm(v)
    return tuple(x / length for x in v) if length > 1e-9 else (0.0, 0.0, 1.0)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _rotate_gravity(gravity, angular_velocity, dt):
    speed = _norm(angular_velocity)
    if speed < 1e-9:
        return gravity
    axis = tuple(v / speed for v in angular_velocity)
    angle = speed * dt
    cosine, sine = math.cos(angle), math.sin(angle)
    tangent = _cross(gravity, axis)
    projection = sum(a * b for a, b in zip(gravity, axis))
    return _unit(tuple(cosine * g + sine * t + (1 - cosine) * projection * a
                       for g, t, a in zip(gravity, tangent, axis)))


def _towards_direction(gravity, measured, fraction):
    """Spherical correction, including a recoverable antiparallel reference."""
    dot = max(-1.0, min(1.0, sum(a * b for a, b in zip(gravity, measured))))
    if dot > 0.9995:
        return _unit(tuple((1 - fraction) * a + fraction * b
                           for a, b in zip(gravity, measured)))
    angle = math.acos(dot)
    tangent = tuple(b - dot * a for a, b in zip(gravity, measured))
    if _norm(tangent) < 1e-6:
        axis = (1.0, 0.0, 0.0) if abs(gravity[0]) < 0.8 else (0.0, 1.0, 0.0)
        tangent = _cross(gravity, axis)
    tangent = _unit(tangent)
    return _unit(tuple(math.cos(angle * fraction) * a + math.sin(angle * fraction) * b
                       for a, b in zip(gravity, tangent)))


class UpwardJumpDetector:
    MIN_THRESHOLD = 0.10
    MAX_THRESHOLD = 0.80
    DEFAULT_THRESHOLD = 0.30
    COOLDOWN_SECONDS = 0.70
    DOWNWARD_THRESHOLD_G = -0.25
    DOWNWARD_HOLDOFF_SECONDS = 0.12
    TRANSITION_REST_SECONDS = 0.08
    REFERENCE_REST_SAMPLES = 30
    SHORT_PULSE_WINDOW = 0.08
    SHORT_PULSE_IMPULSE_SECONDS = 0.04

    def __init__(self, threshold_g=DEFAULT_THRESHOLD):
        self.set_threshold(threshold_g)

    def set_threshold(self, value):
        if not math.isfinite(value) or not self.MIN_THRESHOLD <= value <= self.MAX_THRESHOLD:
            raise ValueError("Upward threshold must be between 0.10 and 0.80 g")
        self.threshold_g = float(value)
        self.reset()

    def reset(self, *, preserve_reference=False):
        reference = ((self._gravity, self._bias, self._rest_g, self._tick,
                      self.orientation_recovering)
                     if preserve_reference and getattr(self, "_gravity", None) is not None
                     else None)
        self.state = "settling"
        self.vertical_g = self.horizontal_g = 0.0
        self.peak_g = 0.0
        self._rest_g = 1.0
        self._tick = None
        self._gravity = None
        self._bias = (0.0, 0.0, 0.0)
        self._initial = deque(maxlen=20)
        self._reference_rest = deque(maxlen=self.REFERENCE_REST_SAMPLES)
        self._pulse = deque()
        self.event_reason = None
        self.orientation_recovering = False
        self.sensor_saturated = False
        self._reliable_samples = 0
        self._gyro_clip_time = 0.0
        self._time = self._above_time = 0.0
        self._candidate_at = self._locked_at = 0.0
        self._downward_until = 0.0
        self._released = False
        if reference is not None:
            (self._gravity, self._bias, self._rest_g, self._tick,
             self.orientation_recovering) = reference
            # Keep calibration, but require the old upward force to be released.
            self.state = "waiting"

    def _lock(self):
        self.state = "locked"
        self._locked_at = self._time
        self._above_time = 0.0
        self._released = False
        self._pulse.clear()

    @property
    def fused_angles(self):
        if self._gravity is None:
            return None
        x, y, z = self._gravity
        return (math.degrees(math.atan2(y, z)),
                math.degrees(math.atan2(-x, math.sqrt(y * y + z * z))))

    def _update_orientation(self, accel_g, gyro_dps, dt, magnitude):
        accel_clipped = any(abs(v) >= 32767 / 16384 for v in accel_g)
        gyro_clipped = any(abs(v) >= 32767 / 131 for v in gyro_dps)
        self.sensor_saturated = accel_clipped or gyro_clipped
        self._gyro_clip_time = self._gyro_clip_time + dt if gyro_clipped else 0.0

        # Bias learning is separate from directional correction. Compare window
        # halves to avoid learning a slow intentional rotation as a gyro bias.
        if abs(magnitude - self._rest_g) <= 0.06 and _norm(gyro_dps) < 12.0:
            self._reference_rest.append((accel_g, gyro_dps))
        else:
            self._reference_rest.clear()
        if len(self._reference_rest) == self.REFERENCE_REST_SAMPLES:
            samples = list(self._reference_rest)
            middle = len(samples) // 2
            stable = all(max(row[0][i] for row in samples) - min(row[0][i] for row in samples) <= 0.06
                         and max(row[1][i] for row in samples) - min(row[1][i] for row in samples) <= 2.0
                         and abs(sum(row[0][i] for row in samples[:middle]) / middle -
                                 sum(row[0][i] for row in samples[middle:]) / middle) <= 0.006
                         for i in range(3))
            if stable:
                self._bias = tuple(sum(row[1][i] for row in samples) / len(samples) for i in range(3))

        gyro = tuple(math.radians(a - b) for a, b in zip(gyro_dps, self._bias))
        self._gravity = _rotate_gravity(self._gravity, gyro, dt)
        measured = _unit(accel_g)
        agreement = sum(a * b for a, b in zip(self._gravity, measured))
        trust = 0.0 if accel_clipped else max(0.0, 1.0 - abs(magnitude - self._rest_g) / 0.12)
        if (accel_clipped or self._gyro_clip_time >= 0.06 - 1e-9
                or (trust > 0.5 and agreement < math.cos(math.radians(45)))):
            self.orientation_recovering = True
            self._reliable_samples = 0
        # Accelerometer feedback runs during normal movement, independently of
        # our computed vertical force. Large errors recover without exact rest.
        if trust > 0:
            tau = 0.10 if self.orientation_recovering else 0.25
            self._gravity = _towards_direction(self._gravity, measured,
                                              1.0 - math.exp(-dt * trust / tau))
        agreement = sum(a * b for a, b in zip(self._gravity, measured))
        if self.orientation_recovering:
            if not self.sensor_saturated and trust > 0.5 and agreement > math.cos(math.radians(20)):
                self._reliable_samples += 1
                if self._reliable_samples >= 3:
                    self.orientation_recovering = False
            else:
                self._reliable_samples = 0

    def update(self, accel_g, gyro_dps, tick_ms):
        """Return one event. Device sample time, not host arrival time, sets dt."""
        self.event_reason = None
        if self._tick is None:
            self._tick = tick_ms
            dt = 0.02
        else:
            delta = (tick_ms - self._tick) & 0xFFFFFFFF
            if delta == 0:
                return False
            if delta > 120:
                self.reset()
                self._tick = tick_ms
                return False
            self._tick = tick_ms
            dt = delta / 1000.0
        self._time += dt
        magnitude = _norm(accel_g)
        if self._gravity is None:
            if abs(magnitude - 1.0) > 0.08 or _norm(gyro_dps) > 35.0:
                self._initial.clear()
                return False
            self._initial.append((accel_g, gyro_dps))
            if len(self._initial) < self._initial.maxlen:
                return False
            if any(max(row[0][axis] for row in self._initial) -
                   min(row[0][axis] for row in self._initial) > 0.06 for axis in range(3)):
                return False
            mean_accel = tuple(sum(row[0][i] for row in self._initial) /
                               len(self._initial) for i in range(3))
            self._rest_g = _norm(mean_accel)
            self._gravity = _unit(mean_accel)
            self._bias = tuple(sum(row[1][i] for row in self._initial) /
                               len(self._initial) for i in range(3))
            self.state = "ready"
            return False

        self._update_orientation(accel_g, gyro_dps, dt, magnitude)
        projected = sum(a * g for a, g in zip(accel_g, self._gravity))
        self.vertical_g = projected - self._rest_g
        self.horizontal_g = _norm(tuple(a - projected * g
                                        for a, g in zip(accel_g, self._gravity)))
        if self.state == "ready" and self.vertical_g > 0.08:
            self.peak_g = self.vertical_g
        elif self.state in {"lifting", "locked"}:
            self.peak_g = max(self.peak_g, self.vertical_g)
        if self.orientation_recovering:
            self._pulse.clear()
            self._above_time = 0.0
            self._downward_until = self._time
            if self.state not in {'waiting', 'locked'}:
                self.state = 'ready'
            return False

        if self.vertical_g <= self.threshold_g * 0.5:
            self._released = True
        if self.vertical_g < self.DOWNWARD_THRESHOLD_G:
            self._downward_until = self._time + self.DOWNWARD_HOLDOFF_SECONDS

        if self.state == "waiting":
            if self._released and self._time >= self.TRANSITION_REST_SECONDS - 1e-9:
                self.state = "ready"
            return False

        if self.state == "locked":
            if self._released and self._time - self._locked_at >= self.COOLDOWN_SECONDS - 1e-9:
                self.state = "ready"
            return False

        # Clear only this candidate after a strong downward pulse. There is no
        # latched rejection or requirement for precise stillness to resume.
        if self._time < self._downward_until - 1e-9:
            self.state = "ready"
            self._above_time = 0.0
            self._pulse.clear()
            return False
        if self.state == "ready":
            if self.vertical_g <= 0.08:
                return False
            self.state = "lifting"
            self._candidate_at = self._time
            self._above_time = 0.0
            self._pulse.clear()
        if self.state == "lifting":
            # One reading represents at most one nominal 50Hz sample. A late
            # packet must not masquerade as a sustained force by itself.
            sample_dt = min(dt, 0.02)
            self._above_time = self._above_time + sample_dt if self.vertical_g >= self.threshold_g else 0.0
            if self.vertical_g >= self.threshold_g * 0.5:
                self._pulse.append((self._time, sample_dt, self.vertical_g))
            else:
                self._pulse.clear()
            while self._pulse and self._time - self._pulse[0][0] >= self.SHORT_PULSE_WINDOW - 1e-9:
                self._pulse.popleft()
            peak = max((row[2] for row in self._pulse), default=0.0)
            # A huge isolated spike must not borrow a tiny shoulder as support.
            support_floor = max(self.threshold_g * 0.5, peak / 3.0)
            supported_peak = (sum(row[2] >= support_floor - 1e-9 for row in self._pulse) >= 2
                              and peak >= self.threshold_g
                              and sum(row[1] * row[2] for row in self._pulse) >=
                              self.threshold_g * self.SHORT_PULSE_IMPULSE_SECONDS - 1e-9)
            if self._above_time >= 0.04 - 1e-9 or supported_peak:
                self.event_reason = 'sustained' if self._above_time >= 0.04 - 1e-9 else 'supported_short_peak'
                self._lock()
                return True
            if self.vertical_g < 0.04:
                self.state = "ready"
                self._above_time = 0.0
                self._pulse.clear()
            elif self._time - self._candidate_at > 0.25:
                self.state = "ready"
                self._above_time = 0.0
                self._pulse.clear()
        return False
