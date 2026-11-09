"""Exercise the actual game loop with SDL dummy video and simulated serial IO."""

import atexit
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame

from MotionGolf_Stage1_v4.controller import ControllerConfig, SerialController
from MotionGolf_Stage1_v4.controller_panel import ControllerPanel
from MotionGolf_Stage1_v4.tests.test_serial_controller import FakeSerial, FakeClock
from MotionGolf_Stage1_v4.tests.test_upward_jump import v2_frame
import MotionGolf_Stage1_v4.settings as settings


class GameIntegrationTests(unittest.TestCase):
    def run_game(self, hardware, event_plan, frames=60, profile=None):
        clock = FakeClock()
        streams = []

        def factory(**options):
            stream = FakeSerial(**options)
            streams.append(stream)
            return stream

        c = SerialController(ControllerConfig(invert_pitch=True, jump_mode="upward"),
                             serial_factory=factory, clock=clock)
        observations = []
        counter = 0

        def events():
            nonlocal counter
            counter += 1
            clock.advance(0.02)
            namespace = sys._getframe(1).f_globals
            observations.append({"frame": counter, "x": namespace["ball_pos"].x,
                                 "height": namespace["ball_height"], "paused": namespace["paused"],
                                 "mode": namespace["controller_panel"].mode,
                                 "tests": namespace["controller_panel"].jump_tests})
            if streams and streams[-1].is_open:
                packet = profile(counter, int(clock.now * 1000)) if profile else v2_frame(int(clock.now * 1000))
                streams[-1].data.extend(packet)
            result = event_plan(counter)
            if counter >= frames:
                result.append(pygame.event.Event(pygame.QUIT))
            return result

        with tempfile.TemporaryDirectory() as folder, \
             patch.object(settings, "SETTINGS_PATH", Path(folder) / "settings.json"), \
             patch("MotionGolf_Stage1_v4.controller.SerialController", new=lambda config: c), \
             patch.object(c, "available_ports", return_value=[("TEST", "mock")] if hardware else []), \
             patch.object(c, "detect_port", return_value="TEST" if hardware else None), \
             patch("pygame.event.get", new=events), patch("sys.exit"):
            namespace = runpy.run_module("MotionGolf_Stage1_v4.main", run_name="__main__")
        atexit.unregister(c.close)
        self.assertFalse(c.is_open)
        return namespace, observations

    @staticmethod
    def key(key):
        return pygame.event.Event(pygame.KEYDOWN, key=key)

    def test_stm32_calibrate_tilt_jump_and_focus_loss_in_actual_loop(self):
        def events(n):
            if n == 2:
                return [self.key(pygame.K_F4)]
            if n == 28:
                return [self.key(pygame.K_F5)]
            if n == 54:
                return [pygame.event.Event(pygame.WINDOWFOCUSLOST)]
            if n == 55:
                return [pygame.event.Event(pygame.WINDOWFOCUSGAINED)]
            return []

        def profile(n, tick):
            force = 1.45 if 50 <= n <= 52 else 1
            return v2_frame(tick, roll=25 if n >= 28 else 0, accel=(0, 0, force))

        namespace, observations = self.run_game(True, events, profile=profile)
        self.assertEqual(namespace["controller_panel"].mode, "STM32")
        self.assertGreater(max(row["x"] for row in observations), 110)
        self.assertGreater(max(row["height"] for row in observations), 0)
        self.assertTrue(observations[-1]["paused"])

    def test_keyboard_backup_and_switch_to_unavailable_hardware(self):
        def events(n):
            return {1: [self.key(pygame.K_F3)], 2: [self.key(pygame.K_F5)],
                    3: [self.key(pygame.K_d), self.key(pygame.K_SPACE)],
                    8: [self.key(pygame.K_F3)]}.get(n, [])

        namespace, observations = self.run_game(False, events, frames=12)
        self.assertGreater(max(row["x"] for row in observations), 110)
        self.assertGreater(max(row["height"] for row in observations), 0)
        self.assertEqual(namespace["controller_panel"].mode, "STM32")
        self.assertTrue(namespace["paused"])
        self.assertEqual((namespace["roll"], namespace["pitch"]), (0, 0))

    def test_lift_soon_after_start_reuses_calibrated_gravity_reference(self):
        def events(n):
            return {2: [self.key(pygame.K_F4)],
                    50: [pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                             pos=(750, 100))]}.get(n, [])

        def profile(n, tick):
            return v2_frame(tick, accel=(0, 0, 1.45 if 57 <= n <= 59 else 1))

        namespace, observations = self.run_game(True, events, frames=80, profile=profile)
        self.assertFalse(namespace["controller_panel"].open)
        self.assertFalse(namespace["paused"])
        self.assertGreater(max(row["height"] for row in observations), 0)

    def test_settings_test_lift_does_not_jump_in_game(self):
        def events(n):
            return [self.key(pygame.K_F4)] if n == 2 else []

        def profile(n, tick):
            return v2_frame(tick, accel=(0, 0, 1.45 if 50 <= n <= 52 else 1))

        namespace, observations = self.run_game(True, events, profile=profile)
        self.assertEqual(namespace["controller_panel"].jump_tests, 1)
        self.assertTrue(namespace["controller_panel"].open)
        self.assertEqual(max(row["height"] for row in observations), 0)

    def test_legacy_firmware_jump_cannot_bypass_upward_mode(self):
        def events(n):
            return {2: [self.key(pygame.K_F4)], 28: [self.key(pygame.K_F5)],
                    40: [self.key(pygame.K_SPACE)]}.get(n, [])

        def profile(n, tick):
            return f"ROLL:0,PITCH:0,JUMP:{int(n >= 40)}\n".encode()

        namespace, observations = self.run_game(True, events, profile=profile)
        self.assertEqual(max(row["height"] for row in observations), 0)
        self.assertFalse(namespace["controller_panel"].open)

    def test_sensor_error_pauses_game_and_clears_input(self):
        def events(n):
            return {2: [self.key(pygame.K_F4)], 28: [self.key(pygame.K_F5)]}.get(n, [])

        def profile(n, tick):
            if n >= 40:
                return b"MPU6050_ERROR,I2C_READ_FAILED\r\n"
            return v2_frame(tick, roll=25 if n >= 28 else 0)

        namespace, observations = self.run_game(True, events, frames=45, profile=profile)
        self.assertGreater(max(row["x"] for row in observations), 110)
        self.assertTrue(namespace["paused"])
        self.assertEqual((namespace["roll"], namespace["pitch"]), (0, 0))

    def test_panel_presets_and_drag_save_player_threshold(self):
        c = SerialController()
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(settings, "SETTINGS_PATH", Path(folder) / "settings.json"), \
             patch.object(c, "available_ports", return_value=[]), \
             patch.object(c, "detect_port", return_value=None):
            panel = ControllerPanel(c)
            panel.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                                  pos=panel.buttons["firm"].center))
            self.assertEqual(c.detector.threshold_g, 0.45)
            self.assertEqual(settings.load_settings()["jump_threshold_g"], 0.45)
            panel.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                                  pos=(panel.slider.left, panel.slider.centery)))
            panel.handle_event(pygame.event.Event(pygame.MOUSEMOTION,
                                                  pos=(panel.slider.right, panel.slider.centery)))
            panel.finish_edit()
            self.assertEqual(c.detector.threshold_g, 0.80)
            self.assertEqual(settings.load_settings()["jump_threshold_g"], 0.80)

    def test_settings_can_close_without_controller_data(self):
        def events(n):
            return [self.key(pygame.K_F5)] if n == 2 else []

        namespace, _ = self.run_game(False, events, frames=4)
        self.assertFalse(namespace["controller_panel"].open)
        self.assertTrue(namespace["paused"])

    def test_retry_recalibrate_and_resume_after_sensor_fault(self):
        def click(position):
            return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=position)

        def events(n):
            return {2: [self.key(pygame.K_F4)], 28: [self.key(pygame.K_F5)],
                    46: [self.key(pygame.K_F5)], 47: [click((700, 205))],
                    49: [self.key(pygame.K_F4)], 76: [click((750, 100))]}.get(n, [])

        def profile(n, tick):
            if 40 <= n <= 44:
                return b"MPU6050_ERROR,HW_SCAN_COUNT:0,FIRST:0x00,WHO:0x00\n"
            return v2_frame(tick, roll=25 if n >= 77 else 0)

        namespace, _ = self.run_game(True, events, frames=84, profile=profile)
        self.assertFalse(namespace["controller_panel"].open)
        self.assertFalse(namespace["paused"])
        self.assertGreater(namespace["ball_pos"].x, 110)


if __name__ == "__main__":
    unittest.main()
