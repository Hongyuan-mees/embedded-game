"""Replay recorded IMU through detector and runner input, without random hazards.

Recorded UI/readiness states are replayed; this is not a whole-game simulation
or an intention-labelled success-rate measurement. Requires the local raw trace.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import types

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import pygame
from MotionGolf_Stage1_v4.controller.upward_jump import UpwardJumpDetector
from MotionGolf_Stage2_v3.runner import RunnerGame


def legacy_module(path, name):
    module = types.ModuleType(name)
    sys.modules[name] = module
    source = subprocess.check_output(['git', 'show', '54dfcfa:' + path], cwd=ROOT)
    exec(compile(source.decode('utf-8-sig'), '<' + name + '>', 'exec'), module.__dict__)
    return module


def main():
    source = Path(__file__).with_name('live_game_gesture_f710bc28.jsonl')
    rows = []
    with source.open(encoding='utf-8') as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row['type'] == 'sample' and row['host_s'] <= 294.2:
                rows.append(row)
    old_detector = legacy_module('MotionGolf_Stage1_v4/controller/upward_jump.py', 'old_detector').UpwardJumpDetector
    old_runner = legacy_module('MotionGolf_Stage2_v3/runner.py', 'old_runner').RunnerGame
    pygame.init()
    report = {'source': source.name, 'sample_count': len(rows),
              'limitations': 'Recorded UI states, no random hazards or human intention labels',
              'versions': {}}
    for name, detector_cls, runner_cls in [('before', old_detector, old_runner),
                                          ('after', UpwardJumpDetector, RunnerGame)]:
        detector = detector_cls(.28)
        runner = runner_cls()
        runner._check_collisions = lambda: None
        detected, accepted = [], []
        current_host_s = 0.0
        original_jump = runner.request_jump

        def jump():
            was_jumping = runner.mode == 'jumping'
            result = original_jump()
            if runner.mode == 'jumping' and not was_jumping:
                accepted.append(current_host_s)
            return result

        runner.request_jump = jump
        previous = None
        previous_status = 'menu'
        for row in rows:
            current_host_s = row['host_s']
            if not row['reference_available_before'] and detector._gravity is not None:
                detector.reset()
                runner.reset_motion_input()
            elif (row['state_before'] == 'waiting' and previous is not None
                  and previous['state_after'] != 'waiting'):
                detector.reset(preserve_reference=True)
                runner.reset_motion_input()
            game = row['game']
            status = game.get('runner_status', 'menu')
            if status == 'playing' and previous_status in ('menu', 'game_over'):
                runner.start()
            else:
                runner.status = status
            previous_status = status
            event = detector.update(row['accel_g'], row['gyro_dps'], row['tick_ms'])
            if event:
                detected.append(current_host_s)
            active = (game.get('state') == 'runner' and status == 'playing'
                      and game.get('focused') and game.get('ready')
                      and not game.get('settings_open') and game.get('mode') == 'STM32')
            if active:
                runner.set_motion_state(0, jump_event=event, pitch=game.get('mapped_pitch', 0))
                runner.update(.02)
            previous = row
        report['versions'][name] = {'detector_events': detected, 'actual_jump_starts': accepted}
    before = report['versions']['before']['actual_jump_starts']
    after = report['versions']['after']['actual_jump_starts']
    unmatched = [t for t in before if not any(abs(v - t) <= .35 for v in after)]
    report['old_jump_starts_without_new_start_within_350ms'] = unmatched
    destination = source.with_name('short_pulse_runner_replay_20261113.json')
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    pygame.quit()
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
