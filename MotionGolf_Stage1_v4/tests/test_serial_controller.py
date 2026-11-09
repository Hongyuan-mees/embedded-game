"""Run from the repository root:
python -m unittest discover -s MotionGolf_Stage1_v4/tests -v
"""

import unittest

from MotionGolf_Stage1_v4.controller import (
    ControllerConfig, MotionPacket, SerialController, parse_packet,
)


def frame(roll=0, pitch=0, jump=0):
    return f"ROLL:{roll},PITCH:{pitch},JUMP:{jump}\r\n".encode("ascii")


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeSerial:
    """A controllable byte stream, including OS read/disconnect failures."""

    def __init__(self, **options):
        self.options = options
        self.is_open = True
        self.data = bytearray()
        self.read_calls = 0
        self.reset_calls = 0
        self.fail_read = False
        self.fail_reset = False
        self.fail_close = False

    @property
    def in_waiting(self):
        if self.fail_read:
            raise OSError("USB unplugged")
        return len(self.data)

    def read(self, size):
        self.read_calls += 1
        result = bytes(self.data[:size])
        del self.data[:size]
        return result

    def reset_input_buffer(self):
        if self.fail_reset:
            raise OSError("USB unplugged while flushing")
        self.reset_calls += 1
        self.data.clear()

    def close(self):
        self.is_open = False
        if self.fail_close:
            raise OSError("Device disappeared")


class ProtocolTests(unittest.TestCase):
    def test_decimal_degrees_are_not_scaled_again(self):
        self.assertEqual(parse_packet("ROLL:-12.3,PITCH:4.5,JUMP:0\r\n"),
                         MotionPacket(-12.3, 4.5, False))

    def test_reordered_fields_and_whitespace(self):
        self.assertEqual(parse_packet(" JUMP:1, PITCH:-90, ROLL:180 "),
                         MotionPacket(180, -90, True))

    def test_bad_packets_and_status_lines_are_rejected(self):
        invalid = [
            "", "Motion Controller Ready,MPU6050_OK,ADDR:0x68,WHO_AM_I:0x74",
            "MPU6050_ERROR,I2C_READ_FAILED", "MPU6050_OK,ADDR:0x68,WHO_AM_I:0x74",
            "ROLL:0,PITCH:0", "ROLL:0,PITCH:0,JUMP:0,EXTRA:1",
            "ROLL:0,ROLL:1,PITCH:0,JUMP:0", "roll:0,PITCH:0,JUMP:0",
            "ROLL:hello,PITCH:0,JUMP:0", "ROLL:nan,PITCH:0,JUMP:0",
            "ROLL:inf,PITCH:0,JUMP:0", "ROLL:0,PITCH:-inf,JUMP:0",
            "ROLL:1e999,PITCH:0,JUMP:0", "ROLL:180.1,PITCH:0,JUMP:0",
            "ROLL:0,PITCH:90.1,JUMP:0", "ROLL:0,PITCH:0,JUMP:2",
            "ROLL:0,PITCH:0,JUMP:1.0", "ROLL:0,PITCH:0,JUMP:-1",
        ]
        for line in invalid:
            with self.subTest(line=line):
                self.assertIsNone(parse_packet(line))

    def test_invalid_configuration_is_rejected(self):
        invalid = [
            {"dead_zone_deg": -1}, {"dead_zone_deg": 25},
            {"full_scale_deg": float("nan")}, {"data_timeout": 0},
            {"data_timeout": float("inf")}, {"calibration_samples": 0},
            {"calibration_samples": 1.5}, {"calibration_spread_deg": 0},
            {"max_read_bytes": 128}, {"max_line_bytes": 0},
        ]
        for options in invalid:
            with self.subTest(options=options), self.assertRaises(ValueError):
                ControllerConfig(**options)


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.streams = []
        self.controller = self.make_controller()
        self.assertTrue(self.controller.connect("TEST_PORT"))
        self.stream = self.streams[-1]

    def make_controller(self, **options):
        options.setdefault("jump_mode", "legacy")
        def factory(**serial_options):
            stream = FakeSerial(**serial_options)
            self.streams.append(stream)
            return stream
        controller = SerialController(ControllerConfig(**options),
                                      serial_factory=factory, clock=self.clock)
        self.addCleanup(controller.close)
        return controller

    def send(self, data):
        self.stream.data.extend(data)
        self.controller.update()

    def test_open_is_explicit_and_does_not_claim_data_connected(self):
        self.assertTrue(self.controller.is_open)
        self.assertFalse(self.controller.connected)
        self.assertFalse(self.controller.calibrate())
        self.assertEqual(self.stream.options, dict(port="TEST_PORT", baudrate=115200,
                         bytesize=8, parity="N", stopbits=1, timeout=0, write_timeout=0))

    def test_empty_update_performs_no_read(self):
        self.controller.update()
        self.assertEqual(self.stream.read_calls, 0)
        self.assertFalse(self.controller.connected)

    def test_no_initial_control_packet_also_times_out(self):
        self.send(b"Motion Controller Ready,MPU6050_OK\r\n")
        self.clock.advance(3.1)
        self.controller.update()
        self.assertTrue(self.controller.is_open)
        self.assertFalse(self.controller.connected)
        self.assertIn("No control data", self.controller.last_error)

    def test_initial_connection_allows_sensor_startup_time(self):
        self.clock.advance(0.6)
        self.send(frame())
        self.assertTrue(self.controller.connected)
        self.assertIsNone(self.controller.last_error)

    def test_retry_does_not_mask_known_sensor_fault_with_generic_timeout(self):
        self.send(b"MPU6050_ERROR,HW_SCAN_COUNT:0,FIRST:0x00,WHO:0x00\n")
        self.assertTrue(self.controller.connect("TEST_PORT"))
        self.stream = self.streams[-1]
        self.clock.advance(3.1)
        self.controller.update()
        self.assertIn("MPU6050_ERROR", self.controller.last_error)
        self.send(frame())
        self.assertTrue(self.controller.connected)
        self.assertIsNone(self.controller.last_sensor_error)

    def test_split_packet_is_only_applied_after_newline(self):
        packet = frame(25, -25)
        self.send(packet[:12])
        self.assertFalse(self.controller.connected)
        self.send(packet[12:-1])
        self.assertFalse(self.controller.connected)
        self.send(packet[-1:])
        self.assertTrue(self.controller.connected)
        self.assertEqual((self.controller.roll, self.controller.pitch), (1.0, -1.0))

    def test_each_possible_packet_split(self):
        packet = frame(-12.3, 4.5)
        for split in range(1, len(packet)):
            with self.subTest(split=split):
                self.controller.connect("TEST_PORT")
                self.stream = self.streams[-1]
                self.send(packet[:split])
                self.assertFalse(self.controller.connected)
                self.send(packet[split:])
                self.assertEqual(self.controller.raw_roll, -12.3)
                self.assertEqual(self.controller.raw_pitch, 4.5)

    def test_burst_keeps_latest_angles_and_latches_short_jump(self):
        self.send(frame(0, 0, 0) + frame(10, 0, 1) + frame(25, 0, 0))
        self.assertEqual(self.controller.roll, 1.0)
        self.assertTrue(self.controller.jump)
        self.assertEqual(self.stream.read_calls, 1)
        self.controller.update()
        self.assertFalse(self.controller.jump)

    def test_first_high_is_suppressed_then_requires_a_low(self):
        self.send(frame(jump=1))
        self.assertFalse(self.controller.jump)
        self.send(frame(jump=1))
        self.assertFalse(self.controller.jump)
        self.send(frame(jump=0))
        self.send(frame(jump=1))
        self.assertTrue(self.controller.jump)

    def test_300ms_high_produces_one_event(self):
        self.send(frame())
        events = []
        for _ in range(15):
            self.clock.advance(0.02)
            self.send(frame(jump=1))
            events.append(self.controller.jump)
        self.assertEqual(sum(events), 1)
        self.send(frame(jump=0))
        self.send(frame(jump=1))
        self.assertTrue(self.controller.jump)

    def test_dead_zone_continuous_gain_and_saturation(self):
        for angle, expected in [(0, 0), (4, 0), (-4, 0), (14.5, 0.5),
                                (-14.5, -0.5), (25, 1), (60, 1), (-60, -1)]:
            with self.subTest(angle=angle):
                self.send(frame(angle, angle))
                self.assertAlmostEqual(self.controller.roll, expected)
                self.assertAlmostEqual(self.controller.pitch, expected)

    def test_swap_then_invert_output_axes(self):
        controller = self.make_controller(swap_axes=True, invert_roll=True, invert_pitch=True)
        controller.connect("TEST_PORT")
        self.streams[-1].data.extend(frame(25, -14.5))
        controller.update()
        self.assertEqual((controller.roll, controller.pitch), (0.5, -1.0))

    def test_status_bad_values_and_non_ascii_do_not_replace_angles(self):
        self.send(frame(14.5, 0))
        self.send(b"Motion Controller Ready,MPU6050_OK\r\n" +
                  b"ROLL:nan,PITCH:0,JUMP:1\r\n" + b"\xff\xfe\n")
        self.assertEqual(self.controller.roll, 0.5)
        self.assertFalse(self.controller.jump)

    def test_bad_packets_do_not_refresh_timeout(self):
        self.send(frame(25))
        self.clock.advance(0.2)
        self.send(b"ROLL:bad,PITCH:0,JUMP:0\n")
        self.clock.advance(0.06)
        self.send(b"MPU6050_OK,ADDR:0x68\n")
        self.assertFalse(self.controller.connected)
        self.assertEqual(self.controller.roll, 0)
        self.assertIsNone(self.controller.raw_roll)
        self.assertIn("timed out", self.controller.last_error)

    def test_timeout_discards_backlog_and_rearms_jump(self):
        self.send(frame(25))
        self.clock.advance(1)
        self.send(frame(25, 0, 1))
        self.assertEqual((self.controller.roll, self.controller.jump), (0, False))
        self.assertEqual(len(self.stream.data), 0)
        self.send(frame(0, 0, 1))
        self.assertTrue(self.controller.connected)
        self.assertFalse(self.controller.jump)
        self.send(frame(jump=0))
        self.send(frame(jump=1))
        self.assertTrue(self.controller.jump)

    def test_stale_fragment_is_not_joined_to_a_new_packet(self):
        self.send(b"ROLL:25,PITCH:")
        self.clock.advance(0.3)
        self.controller.update()
        self.send(b"0,JUMP:1\n" + frame())
        self.assertTrue(self.controller.connected)
        self.assertEqual(self.controller.roll, 0)
        self.assertFalse(self.controller.jump)

    def test_partial_line_expiry_while_awaiting_first_valid_packet(self):
        self.clock.advance(0.3)
        self.controller.update()
        self.send(b"ROLL:25,PITCH:")
        self.clock.advance(0.3)
        self.send(b"0,JUMP:1\n" + frame())
        self.assertTrue(self.controller.connected)
        self.assertEqual(self.controller.roll, 0)
        self.assertFalse(self.controller.jump)

    def test_overlong_line_discards_whole_line_and_recovers(self):
        self.send(b"X" * 300)
        self.send(frame(25, 0, 1) + frame(-25))
        self.assertEqual(self.controller.roll, -1)
        self.assertFalse(self.controller.jump)

    def test_excessive_backlog_is_discarded(self):
        self.send(frame(25))
        self.send(b"X" * 4097)
        self.assertFalse(self.controller.connected)
        self.assertEqual(self.controller.roll, 0)
        self.assertEqual(len(self.stream.data), 0)
        self.assertIn("backlog", self.controller.last_error)
        self.send(frame(-25))
        self.assertEqual(self.controller.roll, -1)

    def test_sensor_error_neutralizes_immediately_and_can_recover(self):
        self.send(frame(25))
        self.send(frame(jump=1) + b"MPU6050_ERROR,I2C_READ_FAILED\r\n")
        self.assertFalse(self.controller.connected)
        self.assertEqual((self.controller.roll, self.controller.jump), (0, False))
        self.assertIn("MPU6050_ERROR", self.controller.last_error)
        self.send(b"MPU6050_OK,ADDR:0x68,WHO_AM_I:0x74\r\n")
        self.assertFalse(self.controller.connected)
        self.send(frame(jump=1))
        self.assertTrue(self.controller.connected)
        self.assertFalse(self.controller.jump)

    def test_read_failure_closes_port_and_neutralizes(self):
        self.send(frame(25))
        self.stream.fail_read = True
        self.controller.update()
        self.assertFalse(self.controller.is_open)
        self.assertFalse(self.controller.connected)
        self.assertEqual((self.controller.roll, self.controller.jump), (0, False))
        self.assertIn("USB unplugged", self.controller.last_error)

    def test_close_failure_still_neutralizes(self):
        self.send(frame(25))
        self.stream.fail_close = True
        self.controller.close()
        self.assertFalse(self.controller.is_open)
        self.assertEqual(self.controller.roll, 0)

    def test_flush_failure_during_timeout_is_recoverable(self):
        self.send(frame(25))
        self.clock.advance(1)
        self.stream.fail_reset = True
        self.controller.update()
        self.assertFalse(self.controller.is_open)
        self.assertFalse(self.controller.connected)
        self.assertEqual(self.controller.roll, 0)

    def test_open_failure_and_blank_port_are_recoverable(self):
        def unavailable(**options):
            raise OSError("Port busy")
        controller = SerialController(serial_factory=unavailable)
        self.assertFalse(controller.connect("BUSY_PORT"))
        self.assertIn("Port busy", controller.last_error)
        controller.update()
        self.assertEqual(controller.roll, 0)
        self.assertFalse(controller.connect(""))
        self.assertFalse(controller.is_open)

    def test_calibration_collects_stable_samples_and_clears_jump(self):
        controller = self.make_controller(calibration_samples=3)
        controller.connect("TEST_PORT")
        stream = self.streams[-1]
        stream.data.extend(frame())
        controller.update()
        self.assertTrue(controller.calibrate())
        stream.data.extend(frame(10, -5, 1) + frame(10, -5) * 2)
        controller.update()
        self.assertTrue(controller.calibrating)
        self.assertEqual((controller.roll, controller.pitch, controller.jump), (0, 0, False))
        stream.data.extend(frame(10, -5))
        controller.update()
        self.assertTrue(controller.calibrated)
        self.assertFalse(controller.calibrating)
        self.assertEqual((controller.roll, controller.pitch), (0, 0))
        stream.data.extend(frame(35, -30))
        controller.update()
        self.assertEqual((controller.roll, controller.pitch), (1, -1))

    def test_unstable_calibration_waits_for_stable_window(self):
        controller = self.make_controller(calibration_samples=3)
        controller.connect("TEST_PORT")
        stream = self.streams[-1]
        stream.data.extend(frame())
        controller.update()
        controller.calibrate()
        stream.data.extend(frame(0) + frame(10) + frame(20))
        controller.update()
        self.assertTrue(controller.calibrating)
        stream.data.extend(frame(12) * 3)
        controller.update()
        self.assertTrue(controller.calibrated)
        self.assertEqual(controller.roll, 0)

    def test_roll_calibration_handles_180_degree_boundary(self):
        controller = self.make_controller(calibration_samples=2)
        controller.connect("TEST_PORT")
        stream = self.streams[-1]
        stream.data.extend(frame(179.5))
        controller.update()
        controller.calibrate()
        stream.data.extend(frame(179.5) + frame(-179.5))
        controller.update()
        self.assertTrue(controller.calibrated)
        self.assertEqual(controller.roll, 0)

    def test_calibration_cannot_start_with_stale_data(self):
        self.send(frame())
        self.clock.advance(1)
        self.assertFalse(self.controller.calibrate())

    def test_timeout_cancels_pending_calibration(self):
        self.send(frame())
        self.controller.calibrate()
        self.clock.advance(1)
        self.controller.update()
        self.assertFalse(self.controller.calibrating)
        self.assertFalse(self.controller.calibrated)

    def test_reconnect_forgets_calibration_and_old_jump(self):
        controller = self.make_controller(calibration_samples=1)
        controller.connect("FIRST_PORT")
        old_stream = self.streams[-1]
        old_stream.data.extend(frame(10))
        controller.update()
        controller.calibrate()
        old_stream.data.extend(frame(10))
        controller.update()
        self.assertTrue(controller.calibrated)
        controller.connect("SECOND_PORT")
        self.assertFalse(old_stream.is_open)
        self.assertFalse(controller.calibrated)
        self.assertEqual(controller.roll, 0)
        self.streams[-1].data.extend(frame(25, 0, 1))
        controller.update()
        self.assertEqual(controller.roll, 1)
        self.assertFalse(controller.jump)


class PySerialLoopbackTests(unittest.TestCase):
    def test_real_pyserial_driver_with_in_memory_loopback(self):
        import serial
        streams = []

        def factory(port, **options):
            stream = serial.serial_for_url(port, **options)
            streams.append(stream)
            return stream

        controller = SerialController(ControllerConfig(jump_mode="legacy"), serial_factory=factory)
        self.addCleanup(controller.close)
        self.assertTrue(controller.connect("loop://"))
        # The loopback sender simulates wire time; only this test writes data.
        # Receive operations on the controller retain timeout=0.
        streams[0].write_timeout = 1.0
        streams[0].write(frame(25) + frame(-25, 0, 1))
        controller.update()
        self.assertTrue(controller.connected)
        self.assertEqual(controller.roll, -1)
        self.assertTrue(controller.jump)
        controller.update()
        self.assertFalse(controller.jump)


if __name__ == "__main__":
    unittest.main()
