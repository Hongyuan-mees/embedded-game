"""Run the existing game with process-local gesture logging; no source edits."""

import json
import math
from pathlib import Path
import runpy
import sys
import time
import uuid


def main():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root))
    import pygame
    from MotionGolf_Stage1_v4.controller.upward_jump import UpwardJumpDetector

    path = Path(__file__).with_name(f"live_game_gesture_{uuid.uuid4().hex[:8]}.jsonl")
    game = None
    last_view = None
    last_flush = time.monotonic()
    started = last_flush
    stream = path.open("x", encoding="utf-8")

    def log(kind, **fields):
        nonlocal last_flush
        stream.write(json.dumps({"type": kind, "host_s": round(time.monotonic() - started, 4),
                                 **fields}, ensure_ascii=False) + "\n")
        if time.monotonic() - last_flush >= 0.25:
            stream.flush()
            last_flush = time.monotonic()

    def view():
        if game is None:
            return {}
        panel = game.get("controller_panel")
        controller = game.get("serial_input")
        return {
            "focused": game.get("focused"), "paused": game.get("paused"),
            "settings_open": panel.open if panel else None,
            "mode": panel.mode if panel else None,
            "ready": panel.ready if panel else None,
            "calibrated": controller.calibrated if controller else None,
            "calibrating": controller.calibrating if controller else None,
            "last_error": controller.last_error if controller else None,
            "threshold_g": controller.detector.threshold_g if controller else None,
            "raw_roll": controller.raw_roll if controller else None,
            "raw_pitch": controller.raw_pitch if controller else None,
            "level_complete": game.get("level_complete"),
            "ball_height": game.get("ball_height"),
            "jump_velocity": game.get("jump_velocity"),
            "status": game.get("status_message"),
        }

    original_update = UpwardJumpDetector.update
    original_events = pygame.event.get

    def recorded_update(detector, accel_g, gyro_dps, tick_ms):
        before = detector.state
        had_gravity = detector._gravity is not None
        event = original_update(detector, accel_g, gyro_dps, tick_ms)
        gyro_speed = math.sqrt(sum((a - b) ** 2 for a, b in zip(gyro_dps, detector._bias)))
        conditions = []
        holdoff = max(0.0, detector._downward_until - detector._time)
        cooldown = (max(0.0, detector.COOLDOWN_SECONDS -
                        (detector._time - detector._locked_at))
                    if detector.state == "locked" else 0.0)
        if holdoff > 0:
            conditions.append("brief_downward_holdoff")
        if detector.state == "locked" and not event:
            conditions.append("jump_cooldown" if cooldown > 0 else "await_force_release")
        if detector.state == "waiting":
            conditions.append("await_force_release_after_transition")
        log("sample", tick_ms=tick_ms, accel_g=accel_g, gyro_dps=gyro_dps,
            state_before=before, state_after=detector.state, event=event,
            reference_available_before=had_gravity,
            vertical_g=detector.vertical_g, horizontal_g=detector.horizontal_g,
            peak_g=detector.peak_g, above_time_s=detector._above_time,
            cooldown_remaining_s=cooldown, downward_holdoff_remaining_s=holdoff,
            force_release_seen=detector._released, gyro_speed_dps=gyro_speed,
            lock_conditions=conditions, game=view())
        return event

    def recorded_events(*args, **kwargs):
        nonlocal game, last_view
        namespace = sys._getframe(1).f_globals
        if game is None and namespace.get("__file__") == str(root / "MotionGolf_Stage1_v4/main.py"):
            game = namespace
            original_jump = namespace["request_jump"]

            def recorded_jump():
                before = view()
                result = original_jump()
                log("request_jump", before=before, after=view())
                return result

            namespace["request_jump"] = recorded_jump
        current = view()
        stable = {k: current.get(k) for k in (
            "focused", "paused", "settings_open", "mode", "ready", "calibrated",
            "calibrating", "last_error", "threshold_g", "level_complete")}
        if stable != last_view:
            log("game_state", **current)
            last_view = stable
        return original_events(*args, **kwargs)

    UpwardJumpDetector.update = recorded_update
    pygame.event.get = recorded_events
    print(f"DIAGNOSTIC_TRACE={path}", flush=True)
    log("session", description="Existing game, in-memory logging wrappers only",
        recognition_policy="playability_first_v1",
        default_threshold_g=UpwardJumpDetector.DEFAULT_THRESHOLD,
        cooldown_seconds=UpwardJumpDetector.COOLDOWN_SECONDS,
        downward_threshold_g=UpwardJumpDetector.DOWNWARD_THRESHOLD_G,
        downward_holdoff_seconds=UpwardJumpDetector.DOWNWARD_HOLDOFF_SECONDS,
        transition_rest_seconds=UpwardJumpDetector.TRANSITION_REST_SECONDS)
    try:
        runpy.run_module("MotionGolf_Stage1_v4.main", run_name="__main__")
    finally:
        UpwardJumpDetector.update = original_update
        pygame.event.get = original_events
        log("session_end")
        stream.close()


if __name__ == "__main__":
    main()
