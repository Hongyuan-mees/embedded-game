"""Exercise the actual Stage 2 loop using device-timed serial frames and SDL."""

import atexit
import os
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
import pygame

from MotionGolf_Stage2_v3.controller import STM32SerialController
from MotionGolf_Stage1_v4.tests.test_serial_controller import FakeClock, FakeSerial
from MotionGolf_Stage1_v4.tests.test_upward_jump import v2_frame
import MotionGolf_Stage1_v4.settings as player_settings


class FastClock:
    def tick(self, fps):
        return 20


class Stage2IntegrationTests(unittest.TestCase):
    @staticmethod
    def key(key):
        return pygame.event.Event(pygame.KEYDOWN, key=key)

    @staticmethod
    def click(pos):
        return pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=pos)

    def run_game(self, plan, *, profile=None, hardware=True, frames=100):
        timer = FakeClock()
        streams = []
        observations = []
        deferred_actions = []
        frame = 0

        def factory(**options):
            stream = FakeSerial(**options)
            streams.append(stream)
            return stream

        controller = STM32SerialController(serial_factory=factory, clock=timer)

        def events():
            nonlocal frame
            frame += 1
            timer.advance(.02)
            game = sys._getframe(1).f_globals
            observations.append({
                'frame': frame, 'state': game['state'], 'mode': game['controller_mode'],
                'panel': game['controller_panel'].open, 'height': game['ball_height'],
                'x': game['ball_pos'].x, 'speed': game['ball_vel'].length(),
                'roll': game['roll'], 'pitch': game['pitch'],
                'level': game['current_level'], 'sinking': game['ball_sinking'],
                'calibrated': controller.calibrated, 'difficulty': game['difficulty_name'],
                'elapsed': game['current_elapsed'](),
            })
            if streams and streams[-1].is_open:
                packet = profile(frame, frame * 20) if profile else v2_frame(frame * 20)
                streams[-1].data.extend(packet)
            planned_actions = plan(frame, game)
            result = list(planned_actions)
            if frame == 2 and game['state'] == game['GAME_SELECT']:
                # Enter the golf menu before exercising the controller-focused
                # scenarios below. Defer same-frame menu clicks by one frame
                # because the main loop resolves clicks against the previous
                # rendered menu.
                deferred_actions.extend(planned_actions)
                result = [self.click((250, 300))]
            elif frame == 3 and deferred_actions:
                result = deferred_actions + result
                deferred_actions.clear()
            if frame >= frames:
                result.append(pygame.event.Event(pygame.QUIT))
            return result

        with tempfile.TemporaryDirectory() as folder, \
             patch.object(player_settings, 'SETTINGS_PATH', Path(folder) / 'settings.json'), \
             patch('MotionGolf_Stage2_v3.controller.STM32SerialController', new=lambda: controller), \
             patch.object(controller, 'available_ports', return_value=[('TEST', 'STM32 mock')] if hardware else []), \
             patch.object(controller, 'detect_port', return_value='TEST' if hardware else None), \
             patch('pygame.time.Clock', FastClock), \
             patch('pygame.time.get_ticks', new=lambda: frame * 20), \
             patch('pygame.event.get', new=events):
            game = runpy.run_module('MotionGolf_Stage2_v3.main', run_name='__main__')
        atexit.unregister(controller.disconnect)
        self.assertFalse(controller.is_open)
        return game, observations

    def test_stm32_calibration_normalized_tilt_and_real_ball_jump(self):
        def plan(n, game):
            return {2: [self.key(pygame.K_F4)],
                    40: [self.click((590, 329))]}.get(n, [])

        def profile(n, tick):
            return v2_frame(tick, roll=15 if n >= 45 else 0,
                            pitch=10 if n >= 45 else 0,
                            accel=(0, 0, 1.45 if 60 <= n <= 62 else 1))

        game, seen = self.run_game(plan, profile=profile)
        self.assertEqual(game['controller_mode'], 'STM32')
        self.assertEqual(game['state'], game['PLAYING'])
        self.assertGreater(max(r['height'] for r in seen), 0)
        self.assertGreater(max(r['x'] for r in seen), 120)
        self.assertTrue(all(abs(r['roll']) <= 1 and abs(r['pitch']) <= 1 for r in seen))
        self.assertLess(min(r['pitch'] for r in seen), 0)

    def test_menu_lift_does_not_leak_into_started_level(self):
        def plan(n, game):
            return {2: [self.key(pygame.K_F4)],
                    70: [self.click((590, 329))]}.get(n, [])

        def profile(n, tick):
            force = 1.45 if 50 <= n <= 52 or 90 <= n <= 92 else 1
            return v2_frame(tick, accel=(0, 0, force))

        _, seen = self.run_game(plan, profile=profile, frames=110)
        self.assertEqual(max(r['height'] for r in seen if r['frame'] < 90), 0)
        self.assertGreater(max(r['height'] for r in seen if r['frame'] > 90), 0)

    def test_space_is_keyboard_only_and_f3_keeps_backup_working(self):
        def plan(n, game):
            return {2: [self.key(pygame.K_F4)], 40: [self.click((590, 329))],
                    50: [self.key(pygame.K_SPACE)], 60: [self.key(pygame.K_F3)],
                    62: [self.key(pygame.K_SPACE)]}.get(n, [])

        game, seen = self.run_game(plan, frames=85)
        self.assertEqual(max(r['height'] for r in seen if r['frame'] <= 62), 0)
        self.assertGreater(max(r['height'] for r in seen), 0)
        self.assertEqual(game['controller_mode'], 'Keyboard')

    def test_missing_hardware_panel_can_close_and_keyboard_can_resume(self):
        def plan(n, game):
            return {2: [self.click((590, 329))], 4: [self.click((905, 103))],
                    6: [self.key(pygame.K_F3)], 7: [self.key(pygame.K_F1)],
                    8: [self.key(pygame.K_SPACE)]}.get(n, [])

        game, seen = self.run_game(plan, hardware=False, frames=30)
        self.assertTrue(any(r['state'] == game['PAUSED'] and r['panel'] for r in seen))
        self.assertFalse(next(r for r in seen if r['frame'] == 5)['panel'])
        self.assertEqual(game['state'], game['PLAYING'])
        self.assertGreater(max(r['height'] for r in seen), 0)

    def test_sensor_fault_retry_recalibrate_and_resume(self):
        def plan(n, game):
            return {2: [self.key(pygame.K_F4)], 40: [self.click((590, 329))],
                    80: [self.click((700, 205))], 83: [self.key(pygame.K_F4)],
                    115: [self.click((750, 100))]}.get(n, [])

        def profile(n, tick):
            if 70 <= n <= 74:
                return b'MPU6050_ERROR,HW_SCAN_COUNT:0,FIRST:0x00,WHO:0x00\r\n'
            return v2_frame(tick, accel=(0, 0, 1.45 if 125 <= n <= 127 else 1))

        game, seen = self.run_game(plan, profile=profile, frames=145)
        self.assertTrue(any(r['state'] == game['PAUSED'] and r['panel']
                            for r in seen if 71 <= r['frame'] <= 80))
        self.assertEqual(game['state'], game['PLAYING'])
        self.assertFalse(game['controller_panel'].open)
        self.assertGreater(max(r['height'] for r in seen if r['frame'] > 125), 0)

    def test_focus_loss_pauses_and_does_not_resume_automatically(self):
        def plan(n, game):
            return {1: [self.key(pygame.K_F3)], 2: [self.click((590, 329))],
                    3: [self.key(pygame.K_d)],
                    10: [pygame.event.Event(pygame.WINDOWFOCUSLOST)],
                    20: [pygame.event.Event(pygame.WINDOWFOCUSGAINED)],
                    25: [self.key(pygame.K_F1)]}.get(n, [])

        game, seen = self.run_game(plan, frames=40)
        self.assertTrue(all(r['state'] == game['PAUSED'] for r in seen if 11 <= r['frame'] <= 25))
        self.assertEqual(game['state'], game['PLAYING'])
        self.assertEqual(game['held_keys'], set())
        self.assertGreater(game['paused_total_ms'], 0)

    def test_controller_overlay_freezes_game_timer_and_close_resumes(self):
        def plan(n, game):
            return {1: [self.key(pygame.K_F3)], 2: [self.click((590, 329))],
                    10: [self.key(pygame.K_F5)], 30: [self.click((905, 103))]}.get(n, [])

        game, seen = self.run_game(plan, frames=40)
        self.assertFalse(game['controller_panel'].open)
        self.assertEqual(game['state'], game['PLAYING'])
        self.assertEqual(game['paused_total_ms'], 400)
        self.assertAlmostEqual(seen[-1]['elapsed'], .34)
        self.assertTrue(all(abs(r['elapsed'] - .14) < 1e-9
                            for r in seen if 11 <= r['frame'] <= 30))

    def test_final_level_sand_escape_sink_stars_and_game_complete(self):
        def plan(n, game):
            if n == 50:
                game['ball_pos'].update(605, 477)
                game['ball_vel'].update(0, 0)
            if n == 100:
                game['ball_pos'] = game['hole_point']()
                game['ball_vel'].update(0, 0)
                game['ball_height'] = game['jump_velocity'] = 0
            return {2: [self.key(pygame.K_F4)], 40: [self.click((590, 407))],
                    42: [self.click((590, 542))],
                    130: [self.click((430, 481))]}.get(n, [])

        def profile(n, tick):
            return v2_frame(tick, roll=25 if 50 <= n < 100 else 0,
                            accel=(0, 0, 1.45 if 70 <= n <= 72 else 1))

        game, seen = self.run_game(plan, profile=profile, frames=145)
        self.assertTrue(all(r['level'] == 4 for r in seen if r['frame'] >= 43))
        self.assertLessEqual(max(r['speed'] for r in seen if 51 <= r['frame'] <= 70), 14)
        self.assertGreater(max(r['height'] for r in seen if 71 <= r['frame'] < 100), 0)
        self.assertGreater(max(r['speed'] for r in seen if 75 <= r['frame'] < 100), 14)
        self.assertTrue(any(r['sinking'] for r in seen if 100 < r['frame'] < 125))
        self.assertEqual(game['stars_earned'], 3)
        self.assertEqual(game['state'], game['GAME_COMPLETE'])
        self.assertEqual(game['settings']['jump_power'], 370)

    def test_difficulty_settings_survive_controller_overlay(self):
        def plan(n, game):
            return {1: [self.key(pygame.K_F3)], 3: [self.click((590, 485))],
                    5: [self.click((320, 245))], 8: [self.key(pygame.K_F5)],
                    9: [self.click((860, 245))], 10: [self.key(pygame.K_F5)],
                    12: [self.click((80, 50))], 14: [self.click((590, 329))]}.get(n, [])

        game, seen = self.run_game(plan, frames=30)
        self.assertEqual(game['difficulty_name'], 'Easy')
        self.assertEqual(game['settings']['jump_power'], 390)
        self.assertEqual(game['settings']['max_speed'], 300)
        self.assertEqual(game['state'], game['PLAYING'])

    def test_legacy_held_jump_and_space_do_not_bypass_stm32_upward_mode(self):
        def plan(n, game):
            return {2: [self.key(pygame.K_F4)], 40: [self.click((590, 329))],
                    50: [self.key(pygame.K_SPACE)]}.get(n, [])

        def profile(n, tick):
            return f'ROLL:0,PITCH:0,JUMP:{int(n >= 50)}\n'.encode('ascii')

        game, seen = self.run_game(plan, profile=profile, frames=80)
        self.assertEqual(game['controller_mode'], 'STM32')
        self.assertEqual(max(r['height'] for r in seen), 0)


if __name__ == '__main__':
    unittest.main()
