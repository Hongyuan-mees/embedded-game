"""Labelled real-device traces for diagnosing upward/downward gesture errors.

Run with the game closed. Prompts synchronize each action with recording;
sensor errors abort the action and remain in the trace instead of counting as
a failed gesture. Output stays under the repository's ignored tmp directory.
"""

import argparse
import json
from pathlib import Path
import time
import uuid

import serial

if __package__:
    from .controller import SerialController, parse_packet
    from .controller.upward_jump import UpwardJumpDetector
    from .settings import load_settings
else:
    from controller import SerialController, parse_packet
    from controller.upward_jump import UpwardJumpDetector
    from settings import load_settings


def capture(stream, detector, output, action, phase, seconds):
    stop = time.monotonic() + seconds
    last_valid = time.monotonic()
    count = 0
    while time.monotonic() < stop:
        line = stream.readline().decode("ascii", errors="replace").strip()
        if line.startswith("MPU6050_ERROR"):
            output.write(json.dumps({"type": "sensor_error", "line": line,
                                     "action": action, "phase": phase}) + "\n")
            raise RuntimeError(line)
        packet = parse_packet(line)
        if packet is not None:
            if packet.accel_raw is None:
                raise RuntimeError("This recorder requires v2 firmware")
            last_valid = time.monotonic()
            before = detector.state
            event = detector.update(tuple(x / 16384 for x in packet.accel_raw),
                                    tuple(x / 131 for x in packet.gyro_raw), packet.tick_ms)
            output.write(json.dumps({
                "type": "sample", "action": action, "phase": phase,
                "tick_ms": packet.tick_ms, "accel_raw": packet.accel_raw,
                "gyro_raw": packet.gyro_raw, "roll": packet.roll, "pitch": packet.pitch,
                "vertical_g": detector.vertical_g, "horizontal_g": detector.horizontal_g,
                "state_before": before, "state_after": detector.state, "event": event,
            }) + "\n")
            count += event
        if time.monotonic() - last_valid > 0.75:
            raise RuntimeError("No valid control data for 0.75 seconds; check sensor/USB")
    output.flush()
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="Actual COM port; defaults to a unique matching STM32")
    parser.add_argument("--threshold", type=float, default=load_settings()["jump_threshold_g"])
    args = parser.parse_args()
    port = args.port or SerialController.detect_port()
    if not port:
        parser.error("Select an actual port with --port")
    try:
        detector = UpwardJumpDetector(args.threshold)
    except ValueError as exc:
        parser.error(str(exc))
    folder = Path(__file__).resolve().parent.parent / "tmp"
    folder.mkdir(exist_ok=True)
    path = folder / f"gesture_trace_{uuid.uuid4().hex[:8]}.jsonl"
    print(f"Trace: {path}", flush=True)
    try:
        with path.open("x", encoding="utf-8") as output, serial.Serial(port, 115200, timeout=0.1) as stream:
            output.write(json.dumps({"type": "session", "threshold_g": args.threshold, "port": port}) + "\n")
            for action, instruction in [
                ("up", "ONE short upward lift, then stop"),
                ("down", "ONE downward movement and stop, without pulling upward afterward"),
                ("side", "ONE sideways movement, then stop"),
            ]:
                print(f"\nNext: {instruction}")
                input("Hold steady and press Enter. Wait for GO before moving: ")
                stream.reset_input_buffer()
                detector.reset()
                print("Hold steady for 3 seconds...", flush=True)
                capture(stream, detector, output, action, "baseline", 3.0)
                if detector.state != "ready":
                    raise RuntimeError("Not settled: repeat with a stable neutral pose")
                print(f"GO: {instruction}. Recording 4 seconds.", flush=True)
                events = capture(stream, detector, output, action, "action", 4.0)
                print(f"{action}: {events} event(s); expected {1 if action == 'up' else 0}", flush=True)
            print("Recording complete. Port released.")
    except (OSError, RuntimeError, KeyboardInterrupt, EOFError) as exc:
        print(f"Stopped: {exc}. Port released. Partial trace preserved.", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
