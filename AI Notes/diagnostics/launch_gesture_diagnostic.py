"""Run the existing game with process-local gesture logging; no source edits."""

import argparse
import json
import math
from pathlib import Path
import runpy
import sys
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage2", action="store_true", help="Run the integrated Stage 2 game")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    game_package = "MotionGolf_Stage2_v3" if args.stage2 else "MotionGolf_Stage1_v4"
    game_entry = str(root / game_package / "main.py")
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
        controller = game.get("serial_input") or game.get("stm32_controller")
        scene = game.get("state")
        runner = game.get("runner")
        return {
            "focused": game.get("focused"),
            "paused": game.get("paused", scene == "paused"),
            "state": scene, "current_level": game.get("current_level"),
            "ball_sinking": game.get("ball_sinking", False),
            "settings_open": panel.open if panel else None,
            "mode": panel.mode if panel else None,
            "ready": panel.ready if panel else None,
            "calibrated": controller.calibrated if controller else None,
            "calibrating": controller.calibrating if controller else None,
            "last_error": controller.last_error if controller else None,
            "threshold_g": controller.detector.threshold_g if controller else None,
            "raw_roll": controller.raw_roll if controller else None,
            "raw_pitch": controller.raw_pitch if controller else None,
            "mapped_pitch": controller.pitch if controller else None,
            "mapped_roll": controller.roll if controller else None,
            "fused_angles": controller.detector.fused_angles if controller else None,
            "orientation_recovering": controller.detector.orientation_recovering if controller else None,
            "sensor_saturated": controller.detector.sensor_saturated if controller else None,
            "pitch_zero_deg": controller._pitch_zero if controller else None,
            "level_complete": game.get("level_complete", scene in ("level_complete", "game_complete")),
            "ball_height": game.get("ball_height"),
            "jump_velocity": game.get("jump_velocity"),
            "status": game.get("status_message"),
            "runner_status": runner.status if runner else None,
            "runner_lane": runner.target_lane if runner else None,
            "runner_mode": runner.mode if runner else None,
            "runner_height": runner.player_height if runner else None,
            "runner_slide_pending_s": runner._slide_confirm_time if runner else None,
            "runner_slide_armed": runner._slide_armed if runner else None,
            "runner_action_lock_s": runner.action_lock if runner else None,
            "runner_jump_buffer_s": runner._jump_buffer_time if runner else None,
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
            event_reason=detector.event_reason,
            reference_available_before=had_gravity,
            vertical_g=detector.vertical_g, horizontal_g=detector.horizontal_g,
            peak_g=detector.peak_g, above_time_s=detector._above_time,
            cooldown_remaining_s=cooldown, downward_holdoff_remaining_s=holdoff,
            force_release_seen=detector._released, gyro_speed_dps=gyro_speed,
            gravity_reference=detector._gravity, gyro_bias_dps=detector._bias,
            reference_rest_samples=len(detector._reference_rest),
            lock_conditions=conditions, game=view())
        return event

    def recorded_events(*args, **kwargs):
        nonlocal game, last_view
        namespace = sys._getframe(1).f_globals
        if game is None and namespace.get("__file__") == game_entry:
            game = namespace
            original_jump = namespace["request_jump"]

            def recorded_jump():
                before = view()
                result = original_jump()
                log("request_jump", before=before, after=view())
                return result

            namespace["request_jump"] = recorded_jump
            runner = namespace.get("runner")
            if runner is not None:
                original_runner_jump = runner.request_jump

                def recorded_runner_jump():
                    before = view()
                    accepted = original_runner_jump()
                    reason = None
                    if not accepted:
                        reason = ("not_playing" if before['runner_status'] != 'playing'
                                  else "action_" + before['runner_mode']
                                  if before['runner_mode'] != 'running' else "action_lock")
                    log("runner_jump_request", accepted=accepted, rejection_reason=reason,
                        before=before, after=view())
                    return accepted

                runner.request_jump = recorded_runner_jump
        current = view()
        stable = {k: current.get(k) for k in (
            "focused", "paused", "settings_open", "mode", "ready", "calibrated",
            "calibrating", "last_error", "threshold_g", "level_complete",
            "state", "current_level", "ball_sinking",
            "runner_status", "runner_lane", "runner_mode")}
        if stable != last_view:
            log("game_state", **current)
            last_view = stable
        return original_events(*args, **kwargs)

    UpwardJumpDetector.update = recorded_update
    pygame.event.get = recorded_events
    print(f"DIAGNOSTIC_TRACE={path}", flush=True)
    log("session", description="Existing game, in-memory logging wrappers only",
        game_package=game_package,
        recognition_policy="shared_continuous_pose_v4",
        short_pulse_window_seconds=UpwardJumpDetector.SHORT_PULSE_WINDOW,
        default_threshold_g=UpwardJumpDetector.DEFAULT_THRESHOLD,
        cooldown_seconds=UpwardJumpDetector.COOLDOWN_SECONDS,
        downward_threshold_g=UpwardJumpDetector.DOWNWARD_THRESHOLD_G,
        downward_holdoff_seconds=UpwardJumpDetector.DOWNWARD_HOLDOFF_SECONDS,
        transition_rest_seconds=UpwardJumpDetector.TRANSITION_REST_SECONDS)
    try:
        runpy.run_module(game_package + ".main", run_name="__main__")
    finally:
        UpwardJumpDetector.update = original_update
        pygame.event.get = original_events
        log("session_end")
        stream.close()


if __name__ == "__main__":
    main()
