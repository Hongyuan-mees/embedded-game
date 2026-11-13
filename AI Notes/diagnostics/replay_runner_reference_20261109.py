"""Compare the reported IMU trace with the pre-fix and current estimators."""

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from MotionGolf_Stage1_v4.controller.upward_jump import UpwardJumpDetector


def main():
    source = Path(__file__).with_name('live_game_gesture_9b258b23.jsonl')
    legacy_namespace = {'__name__': 'legacy_jump_reference'}
    legacy_source = subprocess.check_output(
        ['git', 'show', '1542aef:MotionGolf_Stage1_v4/controller/upward_jump.py'],
        cwd=ROOT).decode('utf-8-sig')
    exec(compile(legacy_source, '<legacy_jump_reference>', 'exec'), legacy_namespace)
    classes = {'before': legacy_namespace['UpwardJumpDetector'], 'after': UpwardJumpDetector}
    samples = []
    with source.open(encoding='utf-8') as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row['type'] == 'sample' and row['host_s'] <= 224.2:
                samples.append(row)
    report = {'trace': source.name, 'sample_count': len(samples), 'versions': {}}
    for name, cls in classes.items():
        detector = cls(0.28)
        previous = None
        events = []
        snapshots = {}
        for row in samples:
            # Reproduce UI/full resets recorded immediately before these samples.
            if not row['reference_available_before'] and detector._gravity is not None:
                detector.reset()
            elif (row['state_before'] == 'waiting' and previous is not None
                  and previous['state_after'] != 'waiting'):
                detector.reset(preserve_reference=True)
            if detector.update(row['accel_g'], row['gyro_dps'], row['tick_ms']):
                events.append(row['host_s'])
            for target in (90, 125, 170, 220):
                if str(target) not in snapshots and row['host_s'] >= target:
                    snapshots[str(target)] = round(detector.vertical_g, 6)
            previous = row
        # A controlled new lift appended to the recorded final stationary pose.
        tick = samples[-1]['tick_ms']
        accel, gyro = samples[-1]['accel_g'], samples[-1]['gyro_dps']
        rest_events = 0
        for _ in range(50):
            tick = (tick + 20) & 0xffffffff
            rest_events += detector.update(accel, gyro, tick)
        baseline = detector.vertical_g
        lift_events = 0
        for _ in range(3):
            tick = (tick + 20) & 0xffffffff
            lift_events += detector.update(tuple(1.5 * a for a in accel), gyro, tick)
        report['versions'][name] = {
            'replayed_event_host_s': events,
            'snapshots_vertical_g': snapshots,
            'appended_rest_events': rest_events,
            'appended_rest_vertical_g': round(baseline, 6),
            'appended_synthetic_lift_events': lift_events,
        }
    after = report['versions']['after']
    assert after['appended_rest_events'] == 0
    assert abs(after['appended_rest_vertical_g']) < 0.03
    assert after['appended_synthetic_lift_events'] == 1
    destination = source.with_name('runner_reference_replay_20261109.json')
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
