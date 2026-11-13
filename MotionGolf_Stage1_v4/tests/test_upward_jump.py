import json
import math
from pathlib import Path
import tempfile
import unittest

from MotionGolf_Stage1_v4.controller import ControllerConfig, SerialController, parse_packet
from MotionGolf_Stage1_v4.controller.upward_jump import UpwardJumpDetector
from MotionGolf_Stage1_v4.settings import load_settings, save_settings
from MotionGolf_Stage1_v4.tests.test_serial_controller import FakeSerial, FakeClock


def v2_frame(tick, roll=0, pitch=0, accel=(0, 0, 1), gyro=(0, 0, 0), jump=0):
    raw = [round(x * 16384) for x in accel] + [round(x * 131) for x in gyro]
    return (f"ROLL:{roll},PITCH:{pitch},JUMP:{jump},V:2,T:{tick & 0xFFFFFFFF}," +
            ",".join(f"{key}:{value}" for key, value in zip(("AX", "AY", "AZ", "GX", "GY", "GZ"), raw)) +
            "\r\n").encode("ascii")


class GestureTests(unittest.TestCase):
    def setUp(self):
        self.detector = UpwardJumpDetector()
        self.tick = 0

    def feed(self, accel=(0, 0, 1), count=1, gyro=(0, 0, 0)):
        events = 0
        for _ in range(count):
            self.tick = (self.tick + 20) & 0xFFFFFFFF
            events += self.detector.update(accel, gyro, self.tick)
        return events

    def settle(self):
        self.assertEqual(self.feed(count=40), 0)
        self.assertEqual(self.detector.state, "ready")

    def test_upward_acceleration_braking_and_return_produce_one_event(self):
        self.settle()
        self.assertEqual(self.feed((0, 0, 1.45), 3), 1)
        self.assertEqual(self.feed((0, 0, 0.65), 4), 0)
        self.assertEqual(self.feed(count=50), 0)
        self.assertEqual(self.feed((0, 0, 1.45), 3), 1)

    def test_downward_onset_blocks_upward_braking(self):
        self.settle()
        self.assertEqual(self.feed((0, 0, 0.6), 4), 0)
        self.assertEqual(self.feed((0, 0, 1.6), 4), 0)
        self.assertEqual(self.feed(count=50), 0)
        self.assertEqual(self.feed((0, 0, 1.4), 3), 1)

    def test_mild_downward_braking_is_an_accepted_playability_tradeoff(self):
        self.settle()
        # -0.04g for 0.50s and +0.50g for 0.04s have equal impulses.
        # Weak downward preparation is now tolerated by user preference. This
        # balanced braking pulse can therefore count; it must not latch a lockout.
        self.assertEqual(self.feed((0, 0, 0.96), 25), 0)
        self.assertEqual(self.detector.state, "ready")
        self.assertEqual(self.feed((0, 0, 1.50), 2), 1)

    def test_mild_downward_preparation_allows_a_later_lift(self):
        self.settle()
        self.assertEqual(self.feed((0, 0, 0.97), 35), 0)
        self.assertEqual(self.feed((0, 0, 1.35), 3), 1)
        self.feed(count=50)
        self.assertEqual(self.detector.state, "ready")
        self.assertEqual(self.feed((0, 0, 1.5), 3), 1)

    def test_small_alternating_noise_does_not_lock_out_lifts(self):
        self.settle()
        for n in range(100):
            self.assertEqual(self.feed((0, 0, 1.008 if n % 2 else 0.992)), 0)
        self.assertEqual(self.detector.state, "ready")
        self.assertEqual(self.feed((0, 0, 1.5), 3), 1)

    def test_drifted_gravity_and_bad_bias_recover_from_measured_rest(self):
        self.settle()
        self.detector._gravity = (0.0, 1.0, 0.0)
        self.detector._bias = (7.0, 0.0, 0.0)
        gravity = (0.08, 0.01, 0.96)
        gyro = (-4.7, 0.1, 0.0)
        self.assertEqual(self.feed(gravity, 60, gyro), 0)
        expected_vertical = math.sqrt(sum(a * a for a in gravity)) - self.detector._rest_g
        self.assertAlmostEqual(self.detector.vertical_g, expected_vertical, delta=0.001)
        self.assertLess(self.detector.horizontal_g, 0.02)
        self.assertAlmostEqual(self.detector._bias[0], -4.7)
        self.assertEqual(self.feed(tuple(1.5 * a for a in gravity), 3, gyro), 1)

    def test_stationary_bias_change_does_not_accumulate_orientation_drift(self):
        self.settle()
        self.assertEqual(self.feed(count=2000, gyro=(3, 0, 0)), 0)
        self.assertLess(abs(self.detector.vertical_g), 0.02)
        self.assertLess(self.detector.horizontal_g, 0.02)
        self.assertEqual(self.feed((0, 0, 1.45), 3, gyro=(3, 0, 0)), 1)

    def test_recorded_stationary_data_recovers_the_reported_drift(self):
        path = Path(__file__).with_name('fixtures') / 'drifted_reference_rest_20261109.json'
        trace = json.loads(path.read_text(encoding='utf-8'))
        detector = UpwardJumpDetector(trace['threshold_g'])
        seed = trace['seed']
        detector._gravity = tuple(seed['gravity'])
        detector._bias = tuple(seed['bias_dps'])
        detector._rest_g = seed['rest_g']
        detector._tick = seed['tick_ms']
        detector.state = 'ready'
        self.assertLess(seed['vertical_g'], -0.5)
        for tick, accel, gyro in trace['samples']:
            self.assertFalse(detector.update(accel, gyro, tick))
        self.assertLess(abs(detector.vertical_g), 0.03)
        self.assertLess(detector.horizontal_g, 0.03)
        events = 0
        for _ in range(3):
            tick = (tick + 20) & 0xffffffff
            events += detector.update(tuple(1.5 * a for a in accel), gyro, tick)
        self.assertEqual(events, 1)

    def test_inverted_reference_recovers_without_false_jump(self):
        self.settle()
        self.detector._gravity = (0.0, 0.0, -1.0)
        self.assertEqual(self.feed(count=40), 0)
        self.assertLess(abs(self.detector.vertical_g), 0.02)
        self.assertEqual(self.feed((0, 0, 1.5), 3), 1)

    def test_pure_lateral_motion_without_upward_force_does_not_jump(self):
        self.settle()
        for accel in [(0.8, 0, 1), (0, -0.8, 1)]:
            with self.subTest(accel=accel):
                self.assertEqual(self.feed(accel, 10), 0)
                self.feed(count=50)

    def test_upward_lift_allows_incidental_lateral_acceleration(self):
        self.settle()
        self.assertEqual(self.feed((0.20, 0, 1.35), 3), 1)

    def test_lateral_component_does_not_veto_upward_force(self):
        self.settle()
        self.assertEqual(self.feed((0.80, 0, 1.35), 3), 1)

    def test_small_preparatory_wobble_can_be_followed_by_a_lift(self):
        self.settle()
        self.assertEqual(self.feed((0, 0, 1.10)), 0)
        self.assertEqual(self.feed((0, 0, 0.99)), 0)
        self.assertEqual(self.detector.state, "ready")
        self.assertEqual(self.feed((0.15, 0, 1), 3), 0)
        self.assertEqual(self.detector.state, "ready")
        self.assertEqual(self.feed((0.20, 0, 1.35), 3), 1)

    def test_repeated_lift_after_natural_rest_noise(self):
        self.settle()
        self.assertEqual(self.feed((0, 0, 1.45), 3), 1)
        self.assertEqual(self.feed((0, 0, 0.65), 4), 0)
        self.assertEqual(self.feed(count=25), 0)
        for n in range(10):
            self.assertEqual(self.feed((0.09, 0, 1.025 if n % 2 else 0.975)), 0)
        self.assertEqual(self.detector.state, "ready")
        self.assertEqual(self.feed((0, 0, 1.45), 3), 1)

    def test_mild_downward_motion_after_cooldown_does_not_latch_a_lockout(self):
        self.settle()
        self.assertEqual(self.feed((0, 0, 1.45), 3), 1)
        self.assertEqual(self.feed((0, 0, 0.975), 50), 0)
        self.assertEqual(self.detector.state, "ready")
        self.assertEqual(self.feed((0, 0, 1.625), 2), 1)
        self.feed(count=50)
        self.assertEqual(self.detector.state, "ready")
        self.assertEqual(self.feed((0, 0, 1.45), 3), 1)

    def test_downward_holdoff_is_brief_and_does_not_require_strict_rest(self):
        self.settle()
        self.assertEqual(self.feed((0, 0, 0.6), 4), 0)
        self.assertEqual(self.feed((0, 0, 1.6), 4), 0)
        self.assertEqual(self.feed(count=4), 0)
        for n in range(10):
            self.assertEqual(self.feed((0.09, 0, 1.025 if n % 2 else 0.975)), 0)
        self.assertEqual(self.detector.state, "ready")
        self.assertEqual(self.feed((0, 0, 1.45), 3), 1)

    def test_cooldown_expires_while_the_hand_is_still_moving(self):
        self.settle()
        self.assertEqual(self.feed((0, 0, 1.45), 3), 1)
        self.assertEqual(self.feed((0.35, 0, 1.06), 40), 0)
        self.assertEqual(self.detector.state, "ready")
        self.assertEqual(self.feed((0.30, 0, 1.45), 3), 1)

    def test_continued_strong_downward_motion_extends_only_short_holdoff(self):
        self.settle()
        self.assertEqual(self.feed((0, 0, 0.6), 50), 0)
        self.assertEqual(self.feed((0, 0, 1.6), 4), 0)
        self.assertEqual(self.feed((0.2, 0, 1.02), 8), 0)
        self.assertEqual(self.feed((0, 0, 1.45), 3), 1)

    def test_separated_spikes_do_not_accumulate_into_a_jump(self):
        self.settle()
        for _ in range(3):
            self.assertEqual(self.feed((0, 0, 1.6)), 0)
            self.assertEqual(self.feed(), 0)

    def test_recorded_lifts_with_accepted_extra_event_in_playable_policy(self):
        path = Path(__file__).with_name("fixtures") / "natural_upward_lifts_20261106.json"
        trace = json.loads(path.read_text(encoding="utf-8"))
        detector = UpwardJumpDetector(trace["threshold_g"])
        events = []
        for tick, ax, ay, az, gx, gy, gz, reset_before in trace["samples"]:
            if reset_before:
                detector.reset()
            if detector.update((ax / 16384, ay / 16384, az / 16384),
                               (gx / 131, gy / 131, gz / 131), tick):
                events.append(tick)
        # The relaxed policy accepts an earlier braking pulse as a tradeoff;
        # both originally missed, annotated lifts must still be recognised.
        self.assertTrue(set(trace["expected_event_ticks"]).issubset(events))
        self.assertEqual(events, trace["playable_policy_event_ticks"])

    def test_sustained_acceleration_does_not_repeat_after_cooldown(self):
        self.settle()
        self.assertEqual(self.feed((0, 0, 1.4), 100), 1)

    def test_one_sample_spike_and_small_lift_do_not_trigger(self):
        self.settle()
        self.assertEqual(self.feed((0, 0, 1.6), 1), 0)
        self.feed(count=50)
        self.assertEqual(self.feed((0, 0, 1.2), 10), 0)

    def test_short_peak_with_adjacent_upward_support_triggers_once(self):
        self.settle()
        self.detector.set_threshold(0.28)
        self.settle()
        events = sum(self.feed((0, 0, 1 + v)) for v in (0.13, 0.137, 0.379, 0.203))
        self.assertEqual(events, 1)
        self.assertEqual(self.detector.event_reason, 'supported_short_peak')
        self.assertEqual(self.feed(count=50), 0)
        self.assertEqual(self.feed((0, 0, 1.45), 3), 1)

    def test_short_peak_can_use_a_leading_shoulder(self):
        self.settle()
        self.assertEqual(self.feed((0, 0, 1.20)), 0)
        self.assertEqual(self.feed((0, 0, 1.56)), 1)
        self.assertEqual(self.detector.event_reason, 'supported_short_peak')

    def test_large_spike_cannot_borrow_a_small_shoulder(self):
        self.settle()
        self.assertEqual(self.feed((0, 0, 2.47)), 0)
        self.assertEqual(self.feed((0, 0, 1.24)), 0)
        self.assertEqual(self.feed(count=20), 0)

    def test_short_peak_requires_enough_combined_force(self):
        self.settle()
        self.assertEqual(self.feed((0, 0, 1.31)), 0)
        self.assertEqual(self.feed((0, 0, 1.16)), 0)
        self.assertEqual(self.feed(count=20), 0)

    def test_delayed_single_sample_cannot_supply_a_full_confirmation(self):
        self.settle()
        self.tick += 80
        self.assertFalse(self.detector.update((0, 0, 1.6), (0, 0, 0), self.tick))
        self.assertEqual(self.feed(), 0)

    def test_short_peak_does_not_bridge_a_pause_transition(self):
        self.settle()
        self.assertEqual(self.feed((0, 0, 1.25)), 0)
        self.detector.reset(preserve_reference=True)
        self.assertEqual(self.feed((0, 0, 1.56)), 0)
        self.feed(count=10)
        self.assertEqual(self.feed((0, 0, 1.56)), 0)

    def test_recorded_rejected_short_pulses_now_meet_supported_peak_policy(self):
        path = Path(__file__).with_name('fixtures') / 'supported_short_pulses_20261113.json'
        trace = json.loads(path.read_text(encoding='utf-8'))
        for clip in trace['clips']:
            with self.subTest(clip=clip['host_s_range']):
                detector = UpwardJumpDetector(trace['threshold_g'])
                seed = clip['seed']
                detector._gravity = tuple(seed['gravity'])
                detector._bias = tuple(seed['bias_dps'])
                detector._rest_g = seed['rest_g']
                detector._tick = seed['tick_ms']
                detector.state = 'ready'
                events = []
                for tick, accel, gyro in clip['samples']:
                    if detector.update(accel, gyro, tick):
                        events.append(tick)
                        self.assertEqual(detector.event_reason, 'supported_short_peak')
                self.assertEqual(events, clip['comparison_event_ticks']['after'])

    def test_threshold_change_affects_force_and_resets_candidate(self):
        self.settle()
        self.detector.set_threshold(0.5)
        self.settle()
        self.assertEqual(self.feed((0, 0, 1.4), 4), 0)
        self.feed(count=50)
        self.detector.set_threshold(0.2)
        self.settle()
        self.assertEqual(self.feed((0, 0, 1.4), 4), 1)

    def test_tilted_gravity_stays_neutral_and_vertical_lift_still_works(self):
        angle = math.radians(25)
        gravity = (0, math.sin(angle), math.cos(angle))
        self.feed(gravity, 40)
        self.assertEqual(self.detector.state, "ready")
        self.assertEqual(self.feed(gravity, 50), 0)
        self.assertAlmostEqual(self.detector.vertical_g, 0, places=5)
        self.assertEqual(self.feed(tuple(1.45 * x for x in gravity), 3), 1)

    def test_slow_roll_rotation_uses_gyro_to_track_gravity(self):
        self.settle()
        for n in range(1, 51):
            angle = math.radians(n * 0.4)
            self.assertEqual(self.feed((0, math.sin(angle), math.cos(angle)), gyro=(20, 0, 0)), 0)
        self.assertAlmostEqual(self.detector.vertical_g, 0, places=3)

    def test_slow_intentional_rotation_is_not_learned_as_gyro_bias(self):
        self.settle()
        for n in range(1, 201):
            angle = math.radians(n * .1)
            self.assertEqual(self.feed((0, math.sin(angle), math.cos(angle)), gyro=(5, 0, 0)), 0)
        self.assertAlmostEqual(self.detector._bias[0], 0, delta=.1)
        self.assertAlmostEqual(self.detector.fused_angles[0], 20, delta=.5)

    def test_bad_reference_recovers_during_rotation_without_stationary_window(self):
        self.settle()
        self.detector._gravity = (1, 0, 0)
        for n in range(1, 61):
            angle = math.radians(n * .4)
            gravity = (0, math.sin(angle), math.cos(angle))
            self.assertEqual(self.feed(gravity, gyro=(20, 0, 0)), 0)
        self.assertFalse(self.detector.orientation_recovering)
        self.assertEqual(len(self.detector._reference_rest), 0)
        self.assertLess(abs(self.detector.vertical_g), .01)
        self.assertLess(self.detector.horizontal_g, .03)
        self.assertEqual(self.feed(tuple(1.45 * a for a in gravity), 3), 1)

    def test_vertical_lift_with_incidental_force_does_not_become_tilt(self):
        self.settle()
        self.feed((.3, 0, 1.45), 4)
        self.assertAlmostEqual(self.detector.fused_angles[0], 0, delta=.01)
        self.assertAlmostEqual(self.detector.fused_angles[1], 0, delta=.01)

    def test_sustained_gyro_clipping_enters_recovery_and_does_not_jump(self):
        self.settle()
        self.assertEqual(self.feed(count=4, gyro=(0, 32767 / 131, 0)), 0)
        self.assertTrue(self.detector.sensor_saturated)
        self.assertTrue(self.detector.orientation_recovering)
        self.assertEqual(self.feed(count=40), 0)
        self.assertFalse(self.detector.orientation_recovering)
        self.assertEqual(self.feed((0, 0, 1.45), 3), 1)

    def test_wrist_rotation_does_not_veto_upward_force(self):
        self.settle()
        self.assertEqual(self.feed((0, 0, 1.5), 3, gyro=(150, 0, 0)), 1)

    def test_gap_and_reordered_time_require_new_settling(self):
        self.settle()
        self.tick += 500
        self.assertFalse(self.detector.update((0, 0, 1.5), (0, 0, 0), self.tick))
        self.assertEqual(self.feed((0, 0, 1.5), 3), 0)
        self.settle()
        self.assertFalse(self.detector.update((0, 0, 1.5), (0, 0, 0), self.tick - 10))
        self.assertEqual(self.detector.state, "settling")

    def test_duplicate_timestamp_does_not_complete_lift(self):
        self.settle()
        self.assertEqual(self.feed((0, 0, 1.5)), 0)
        for _ in range(5):
            self.assertFalse(self.detector.update((0, 0, 1.5), (0, 0, 0), self.tick))

    def test_transition_preserves_reference_but_discards_pending_gesture(self):
        self.feed((0, 0, 1.04), 40)
        self.assertEqual(self.feed((0, 0, 1.50)), 0)
        gravity = self.detector._gravity
        self.detector.reset(preserve_reference=True)
        self.assertEqual(self.detector._gravity, gravity)
        self.assertAlmostEqual(self.detector._rest_g, 1.04)
        self.assertEqual(self.feed((0, 0, 1.50), 10), 0)
        self.assertEqual(self.detector.state, "waiting")
        self.assertEqual(self.feed((0, 0, 1.04), 8), 0)
        self.assertEqual(self.detector.state, "ready")
        self.assertEqual(self.feed((0, 0, 1.50), 3), 1)

    def test_gap_discards_even_a_preserved_reference(self):
        self.settle()
        self.detector.reset(preserve_reference=True)
        self.tick += 500
        self.assertEqual(self.feed(), 0)
        self.assertIsNone(self.detector._gravity)
        self.assertEqual(self.detector.state, "settling")

    def test_transition_waits_for_release_without_precise_stillness(self):
        self.settle()
        self.detector.reset(preserve_reference=True)
        self.assertEqual(self.feed((0.25, 0, 1.05), 8), 0)
        self.assertEqual(self.detector.state, "ready")
        self.assertEqual(self.feed((0.25, 0, 1.45), 3), 1)

    def test_uint32_timestamp_wrap(self):
        self.tick = 0xFFFFFF00
        self.settle()
        self.assertEqual(self.feed((0, 0, 1.5), 3), 1)

    def test_does_not_arm_while_moving(self):
        self.assertEqual(self.feed((0, 0, 1.5), 40), 0)
        self.assertEqual(self.detector.state, "settling")

    def test_small_rest_scale_bias_is_calibrated_out(self):
        self.feed((0, 0, 1.04), 40)
        self.assertEqual(self.detector.state, "ready")
        self.feed((0, 0, 1.04), 2)
        self.assertAlmostEqual(self.detector.vertical_g, 0, places=5)
        self.assertEqual(self.feed((0, 0, 1.44), 3), 1)
        self.assertAlmostEqual(self.detector.peak_g, 0.4, places=5)


class ExtendedProtocolTests(unittest.TestCase):
    def test_v2_integer_scales_and_legacy_compatibility(self):
        p = parse_packet(v2_frame(1234, accel=(0, 0, 1)).decode())
        self.assertEqual(p.accel_raw, (0, 0, 16384))
        self.assertEqual(p.tick_ms, 1234)
        self.assertIsNone(parse_packet("ROLL:0,PITCH:0,JUMP:0").tick_ms)

    def test_partial_unknown_version_bad_integer_and_out_of_range(self):
        good = v2_frame(123).decode()
        bad = [good.replace(",GZ:0", ""), good.replace("V:2", "V:3"),
               good.replace("T:123", "T:-1"), good.replace("T:123", "T:4294967296"),
               good.replace("AX:0", "AX:32768"), good.replace("AX:0", "AX:0.0")]
        for line in bad:
            with self.subTest(line=line):
                self.assertIsNone(parse_packet(line))

    def test_upward_mode_ignores_legacy_jump_and_uses_device_time_in_bursts(self):
        clock = FakeClock()
        streams = []

        def factory(**kwargs):
            stream = FakeSerial(**kwargs)
            streams.append(stream)
            return stream

        c = SerialController(ControllerConfig(jump_mode="upward"), serial_factory=factory, clock=clock)
        self.addCleanup(c.close)
        c.connect("TEST")
        s = streams[0]
        s.data.extend(b"ROLL:0,PITCH:0,JUMP:0\nROLL:0,PITCH:0,JUMP:1\n")
        c.update()
        self.assertFalse(c.jump)
        self.assertEqual(c.protocol_version, 1)
        s.data.extend(b"".join(v2_frame(t) for t in range(20, 420, 20)))
        c.update()
        self.assertEqual(c.protocol_version, 2)
        s.data.extend(v2_frame(420, accel=(0, 0, 1.5)) + v2_frame(440, accel=(0, 0, 1.5)))
        c.update()
        self.assertTrue(c.jump)
        c.update()
        self.assertFalse(c.jump)
        c.reset_gesture()
        s.data.extend(v2_frame(460, accel=(0, 0, 1.5)))
        c.update()
        self.assertFalse(c.jump)


class SettingsTests(unittest.TestCase):
    def test_roundtrip_and_replace(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            self.assertEqual(load_settings(path)["jump_threshold_g"], 0.30)
            save_settings({"jump_threshold_g": 0.45, "port": "TEST"}, path)
            self.assertEqual(load_settings(path), {"jump_threshold_g": 0.45, "port": "TEST"})
            save_settings({"jump_threshold_g": 0.18}, path)
            self.assertEqual(load_settings(path)["jump_threshold_g"], 0.18)
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    def test_corrupt_and_invalid_settings_fall_back(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            for content in ["broken", "[]", '{"jump_threshold_g": true}',
                            '{"jump_threshold_g": 20}', '{"jump_threshold_g": NaN}']:
                path.write_text(content)
                self.assertEqual(load_settings(path)["jump_threshold_g"], 0.30)


if __name__ == "__main__":
    unittest.main()
