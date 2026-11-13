from __future__ import annotations

import math
import random
from dataclasses import dataclass

import pygame


@dataclass
class Obstacle:
    kind: str
    lane: int
    z: float
    resolved: bool = False


@dataclass
class Pickup:
    lane: int
    z: float
    collected: bool = False


class RunnerGame:
    WIDTH = 1180
    HEIGHT = 760
    GAME_W = 860
    HUD_X = 860
    ROAD_TOP = 100
    PLAYER_Y = 650
    VIEW_DISTANCE = 100.0
    LANE_WIDTH = 244.0
    RUN_SPEED = 20.0
    LANE_TILT_THRESHOLD = 0.40
    AIR_LANE_TILT_THRESHOLD = 0.55
    LANE_CENTER_THRESHOLD = 0.10
    LANE_REPEAT_DELAY = 0.60
    LANE_REPEAT_INTERVAL = 0.35
    SLIDE_TILT_THRESHOLD = 0.60
    SLIDE_RELEASE_THRESHOLD = 0.30
    SLIDE_HOLD_THRESHOLD = 0.45
    SLIDE_CONFIRM_SECONDS = 0.16
    JUMP_BUFFER_SECONDS = 0.20

    BG = (15, 18, 28)
    PANEL = (27, 32, 43)
    PANEL_2 = (39, 46, 61)
    TEXT = (239, 244, 248)
    MUTED = (154, 168, 184)
    CYAN = (78, 220, 218)
    BLUE = (55, 115, 210)
    GREEN = (102, 220, 145)
    GOLD = (255, 205, 83)
    ORANGE = (242, 142, 60)
    RED = (234, 84, 91)
    ROAD = (39, 45, 59)
    ROAD_EDGE = (18, 22, 31)
    LANE_LINE = (83, 98, 121)

    def __init__(self) -> None:
        self.title = pygame.font.SysFont("arial", 58, bold=True)
        self.big = pygame.font.SysFont("arial", 42, bold=True)
        self.font = pygame.font.SysFont("arial", 23)
        self.small = pygame.font.SysFont("arial", 17)
        self.tiny = pygame.font.SysFont("arial", 14, bold=True)
        self.rng = random.Random()
        self.status = "menu"
        self.best_score = 0
        self.mouse_actions: list[tuple[pygame.Rect, str]] = []
        self.pending_result: str | None = None
        self._reset_run()

    def _reset_run(self) -> None:
        self.score = 0
        self.distance = 0.0
        self.lives = 3
        self.combo = 0
        self.pickups = 0
        self.speed = self.RUN_SPEED
        self.player_lane = 1.0
        self.target_lane = 1
        self.mode = "running"
        self.player_height = 0.0
        self.jump_velocity = 0.0
        self.slide_timer = 0.0
        self.action_lock = 0.0
        self.invulnerable = 0.0
        self.hit_flash = 0.0
        self.stumble_timer = 0.0
        self.spawn_timer = 1.2
        self.obstacles: list[Obstacle] = []
        self.pickups_list: list[Pickup] = []
        self.reset_motion_input()

    def reset_motion_input(self) -> None:
        """Require neutral before new commands after a scene/input transition."""
        self.sensor_roll = 0.0
        self._lane_armed = False
        self._lane_direction = 0
        self._lane_repeat_time = 0.0
        self._lane_threshold = self.LANE_TILT_THRESHOLD
        self._slide_armed = False
        self._slide_confirm_time = None
        self._jump_buffer_time = 0.0

    def show_menu(self) -> None:
        self.status = "menu"
        self.mouse_actions.clear()

    def start(self) -> None:
        self._reset_run()
        self.status = "playing"

    def restart(self) -> None:
        self.start()

    def pause(self) -> None:
        if self.status == "playing":
            self.status = "paused"

    def resume(self) -> None:
        if self.status == "paused":
            self.status = "playing"

    def move_lane(self, delta: int) -> None:
        if self.status == "playing":
            self.target_lane = max(0, min(2, self.target_lane + delta))

    def request_jump(self) -> bool:
        if (
            self.status != "playing"
            or self.mode not in ("running", "sliding")
            or self.action_lock > 0
        ):
            return False
        self.slide_timer = 0.0
        self.mode = "jumping"
        self.jump_velocity = 7.2
        self.player_height = 0.01
        self._jump_buffer_time = 0.0
        self._slide_confirm_time = None
        return True

    def request_slide(self) -> bool:
        if (
            self.status != "playing"
            or self.mode != "running"
            or self.action_lock > 0
        ):
            return False
        self.mode = "sliding"
        self.slide_timer = 0.72
        return True

    def set_motion_state(
        self,
        roll: float,
        jump_event: bool = False,
        slide_event: bool = False,
        *,
        pitch: float = 0.0,
        jump_preparing: bool = False,
    ) -> None:
        """Normalized tilt: lane steps/repeat, and delayed rear-tilt slides."""
        self.sensor_roll = roll
        if self.status != "playing":
            return

        lift_active = self.mode == "jumping" or jump_event or jump_preparing or self._jump_buffer_time > 0
        self._lane_threshold = self.AIR_LANE_TILT_THRESHOLD if lift_active else self.LANE_TILT_THRESHOLD

        if abs(roll) <= self.LANE_CENTER_THRESHOLD:
            self._lane_armed = True
            self._lane_direction = 0
            self._lane_repeat_time = 0.0
        elif abs(roll) >= self._lane_threshold:
            direction = -1 if roll < 0 else 1
            if self._lane_armed or (self._lane_direction and direction != self._lane_direction):
                self._lane_direction = direction
                self.move_lane(direction)
                self._lane_repeat_time = self.LANE_REPEAT_DELAY
                self._lane_armed = False
        elif self._lane_direction:
            self._lane_repeat_time = self.LANE_REPEAT_DELAY

        if pitch <= self.SLIDE_RELEASE_THRESHOLD:
            self._slide_armed = True
            self._slide_confirm_time = None
        elif self._slide_armed and pitch >= self.SLIDE_TILT_THRESHOLD:
            if self._slide_confirm_time is None:
                self._slide_confirm_time = self.SLIDE_CONFIRM_SECONDS
        elif pitch < self.SLIDE_HOLD_THRESHOLD or not self._slide_armed:
            self._slide_confirm_time = None

        if jump_event:
            self._slide_confirm_time = None
            self._slide_armed = False
            if not self.request_jump():
                self._jump_buffer_time = self.JUMP_BUFFER_SECONDS
        if slide_event:
            self.request_slide()

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self._handle_click(event.pos)
            return self._consume_result()

        if event.type != pygame.KEYDOWN:
            return None

        key = event.key
        if self.status == "menu":
            if key in (pygame.K_RETURN, pygame.K_SPACE):
                self.start()
            elif key == pygame.K_ESCAPE:
                return "exit"
            return None

        if self.status == "playing":
            if key in (pygame.K_LEFT, pygame.K_a):
                self.move_lane(-1)
            elif key in (pygame.K_RIGHT, pygame.K_d):
                self.move_lane(1)
            elif key in (pygame.K_UP, pygame.K_w, pygame.K_SPACE):
                self.request_jump()
            elif key in (pygame.K_DOWN, pygame.K_s):
                self.request_slide()
            elif key in (pygame.K_p, pygame.K_F1):
                self.pause()
            elif key in (pygame.K_r, pygame.K_F2):
                self.restart()
            elif key == pygame.K_ESCAPE:
                self.show_menu()
            return None

        if self.status == "paused":
            if key in (pygame.K_p, pygame.K_F1):
                self.resume()
            elif key in (pygame.K_r, pygame.K_F2):
                self.restart()
            elif key == pygame.K_ESCAPE:
                self.show_menu()
            return None

        if self.status == "game_over":
            if key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_r, pygame.K_F2):
                self.restart()
            elif key == pygame.K_ESCAPE:
                self.show_menu()
        return None

    def update(self, dt: float) -> None:
        if self.status != "playing":
            return

        if self._jump_buffer_time > 0:
            self._jump_buffer_time = max(0.0, self._jump_buffer_time - dt)
            if self._jump_buffer_time > 1e-9:
                self.request_jump()

        lane_threshold = self.AIR_LANE_TILT_THRESHOLD if self.mode == "jumping" else self._lane_threshold
        if self._lane_direction and abs(self.sensor_roll) >= lane_threshold:
            self._lane_repeat_time -= dt
            if self._lane_repeat_time <= 1e-9:
                self.move_lane(self._lane_direction)
                self._lane_repeat_time = self.LANE_REPEAT_INTERVAL
        if self._slide_confirm_time is not None:
            self._slide_confirm_time = max(0.0, self._slide_confirm_time - dt)
            # A confirmed rear tilt remains valid while held. Do not consume it
            # during a jump/landing lock; release or a new jump cancels it above.
            if self._slide_confirm_time <= 1e-9 and self.request_slide():
                self._slide_confirm_time = None
                self._slide_armed = False

        self.invulnerable = max(0.0, self.invulnerable - dt)
        self.hit_flash = max(0.0, self.hit_flash - dt)
        self.stumble_timer = max(0.0, self.stumble_timer - dt)
        self.action_lock = max(0.0, self.action_lock - dt)

        self.player_lane += (self.target_lane - self.player_lane) * min(1.0, dt * 15.0)
        if abs(self.player_lane - self.target_lane) < 0.01:
            self.player_lane = float(self.target_lane)

        if self.mode == "jumping":
            self.jump_velocity -= 18.0 * dt
            self.player_height += self.jump_velocity * dt
            if self.player_height <= 0:
                self.player_height = 0.0
                self.jump_velocity = 0.0
                self.mode = "running"
                self.action_lock = 0.08
        elif self.mode == "sliding":
            self.slide_timer -= dt
            if self.slide_timer <= 0:
                self.slide_timer = 0.0
                self.mode = "running"
                self.action_lock = 0.08

        self.speed = self.RUN_SPEED
        travel_speed = self.speed
        self.distance += travel_speed * dt
        self.score += travel_speed * dt * 12.0

        for obstacle in self.obstacles:
            obstacle.z -= travel_speed * dt
        for pickup in self.pickups_list:
            pickup.z -= travel_speed * dt

        self._check_collisions()
        self.obstacles = [o for o in self.obstacles if o.z > -3.0]
        self.pickups_list = [p for p in self.pickups_list if p.z > -3.0]

        self.spawn_timer -= dt
        if self.spawn_timer <= 0 and self.distance > 45:
            self._spawn_pattern()
            self.spawn_timer = max(1.55, 2.15 - self.distance / 7000.0)

        if self.lives <= 0:
            self.best_score = max(self.best_score, int(self.score))
            self.status = "game_over"

    def _check_collisions(self) -> None:
        for obstacle in self.obstacles:
            if obstacle.resolved or not (-2.2 <= obstacle.z <= 2.8):
                continue

            in_lane = abs(self.player_lane - obstacle.lane) < 0.46
            if not in_lane:
                continue

            cleared = False
            if obstacle.kind == "jump":
                cleared = self.player_height > 0.32
            elif obstacle.kind == "slide":
                cleared = self.mode == "sliding"

            if not cleared:
                obstacle.resolved = True
                self._take_hit()

        for pickup in self.pickups_list:
            if (
                not pickup.collected
                and -2.0 <= pickup.z <= 2.5
                and abs(self.player_lane - pickup.lane) < 0.5
            ):
                pickup.collected = True
                self.pickups += 1
                self.combo += 1
                self.score += 80 + min(self.combo, 20) * 4

    def _take_hit(self) -> None:
        if self.invulnerable > 0:
            return
        self.lives -= 1
        self.combo = 0
        self.invulnerable = 1.0
        self.hit_flash = 0.22
        self.stumble_timer = 0.55
        if self.mode == "sliding":
            self.mode = "running"
            self.slide_timer = 0.0

    def _spawn_pattern(self) -> None:
        patterns = ["block1", "jump1"]
        if self.distance > 120:
            patterns.extend(["slide1", "block2"])
        if self.distance > 280:
            patterns.extend(["jump3", "slide3", "mixed"])

        pattern = self.rng.choice(patterns)
        z = self.VIEW_DISTANCE
        safe_lane = self.rng.randrange(3)

        if pattern == "block1":
            self.obstacles.append(Obstacle("block", self.rng.randrange(3), z))
        elif pattern == "jump1":
            self.obstacles.append(Obstacle("jump", self.rng.randrange(3), z))
        elif pattern == "slide1":
            self.obstacles.append(Obstacle("slide", self.rng.randrange(3), z))
        elif pattern == "block2":
            for lane in range(3):
                if lane != safe_lane:
                    self.obstacles.append(Obstacle("block", lane, z))
        elif pattern == "jump3":
            for lane in range(3):
                self.obstacles.append(Obstacle("jump", lane, z))
        elif pattern == "slide3":
            for lane in range(3):
                self.obstacles.append(Obstacle("slide", lane, z))
        elif pattern == "mixed":
            for lane in range(3):
                if lane != safe_lane:
                    self.obstacles.append(Obstacle("block", lane, z))
            self.obstacles.append(Obstacle("jump", safe_lane, z))

        if self.rng.random() < 0.55:
            pickup_lane = safe_lane if pattern in ("block2", "mixed") else self.rng.randrange(3)
            for index in range(3):
                self.pickups_list.append(
                    Pickup(pickup_lane, self.VIEW_DISTANCE + index * 4.5)
                )

    def _handle_click(self, pos: tuple[int, int]) -> None:
        for rect, action in reversed(self.mouse_actions):
            if not rect.collidepoint(pos):
                continue
            if action == "start":
                self.start()
            elif action == "pause":
                self.pause()
            elif action == "resume":
                self.resume()
            elif action == "restart":
                self.restart()
            elif action == "menu":
                self.show_menu()
            elif action == "exit":
                self.pending_result = "exit"
            break

    def _consume_result(self) -> str | None:
        result = self.pending_result
        self.pending_result = None
        return result

    def draw(self, screen: pygame.Surface) -> None:
        self.mouse_actions.clear()
        if self.status == "menu":
            self._draw_menu(screen)
        else:
            self._draw_game(screen)
            if self.status == "paused":
                self._draw_pause_overlay(screen)
            elif self.status == "game_over":
                self._draw_game_over_overlay(screen)

    def _button(
        self,
        screen: pygame.Surface,
        rect: pygame.Rect,
        label: str,
        action: str,
        primary: bool = False,
    ) -> None:
        hovered = rect.collidepoint(pygame.mouse.get_pos())
        if primary:
            color = (50, 157, 165) if hovered else (39, 127, 139)
        else:
            color = (53, 64, 81) if hovered else self.PANEL_2
        pygame.draw.rect(screen, color, rect, border_radius=12)
        pygame.draw.rect(screen, (100, 119, 143), rect, 1, border_radius=12)
        label_surface = self.font.render(label, True, self.TEXT)
        screen.blit(label_surface, label_surface.get_rect(center=rect.center))
        self.mouse_actions.append((rect.copy(), action))

    def _draw_menu(self, screen: pygame.Surface) -> None:
        screen.fill(self.BG)
        for index in range(8):
            y = 135 + index * 72
            color = (19, 27, 43) if index % 2 == 0 else (21, 31, 49)
            pygame.draw.polygon(
                screen,
                color,
                [(90 + index * 58, y), (770 - index * 38, y), (820, y + 50), (40, y + 50)],
            )

        title = self.title.render("MOTION RUSH", True, self.CYAN)
        screen.blit(title, title.get_rect(center=(self.WIDTH // 2, 120)))
        subtitle = self.font.render(
            "Three lanes. One motion controller. Keep moving.",
            True,
            self.MUTED,
        )
        screen.blit(subtitle, subtitle.get_rect(center=(self.WIDTH // 2, 177)))

        card = pygame.Rect(self.WIDTH // 2 - 350, 230, 700, 225)
        pygame.draw.rect(screen, self.PANEL, card, border_radius=20)
        pygame.draw.rect(screen, (64, 78, 98), card, 1, border_radius=20)

        hints = [
            ("TILT LEFT/RIGHT or A/D", "Tilt steps; hold repeats"),
            ("LIFT or W / SPACE", "Jump over low barriers"),
            ("TILT BACK or S / DOWN", "Hold back briefly to slide"),
        ]
        for index, (key, description) in enumerate(hints):
            y = 270 + index * 52
            key_surface = self.small.render(key, True, self.CYAN)
            desc_surface = self.small.render(description, True, self.TEXT)
            screen.blit(key_surface, (self.WIDTH // 2 - 285, y))
            screen.blit(desc_surface, (self.WIDTH // 2 + 10, y))

        self._button(
            screen,
            pygame.Rect(self.WIDTH // 2 - 160, 505, 320, 60),
            "START RUN",
            "start",
            primary=True,
        )
        self._button(
            screen,
            pygame.Rect(self.WIDTH // 2 - 160, 583, 320, 52),
            "BACK TO GAME SELECT",
            "exit",
        )

        footer = self.small.render(
            "F4 calibrate | F3 control mode | F5 controller settings",
            True,
            self.MUTED,
        )
        screen.blit(footer, footer.get_rect(center=(self.WIDTH // 2, 695)))

    def _draw_game(self, screen: pygame.Surface) -> None:
        screen.fill((20, 28, 46))
        pygame.draw.rect(screen, (20, 23, 35), (0, 0, self.WIDTH, 64))
        title = self.font.render("MOTION RUSH", True, self.TEXT)
        screen.blit(title, (24, 19))
        controls = self.small.render(
            "Tilt: lane step / back slide | Lift: jump | A/D W/S backup | P pause",
            True,
            self.MUTED,
        )
        screen.blit(controls, (290, 24))

        self._draw_road(screen)
        self._draw_world(screen)
        self._draw_player(screen)
        self._draw_game_hud(screen)
        self._draw_side_hud(screen)

        if self.hit_flash > 0:
            flash = pygame.Surface((self.GAME_W, self.HEIGHT), pygame.SRCALPHA)
            flash.fill((255, 60, 60, int(85 * self.hit_flash / 0.22)))
            screen.blit(flash, (0, 0))

    def _draw_road(self, screen: pygame.Surface) -> None:
        center = self.GAME_W // 2
        top_half = self._road_half_width(0.0)
        bottom_half = self._road_half_width(1.0)
        pygame.draw.polygon(
            screen,
            self.ROAD_EDGE,
            [
                (center - top_half - 24, self.ROAD_TOP),
                (center + top_half + 24, self.ROAD_TOP),
                (center + bottom_half + 24, self.HEIGHT),
                (center - bottom_half - 24, self.HEIGHT),
            ],
        )
        pygame.draw.polygon(
            screen,
            self.ROAD,
            [
                (center - top_half, self.ROAD_TOP),
                (center + top_half, self.ROAD_TOP),
                (center + bottom_half, self.HEIGHT),
                (center - bottom_half, self.HEIGHT),
            ],
        )

        lane_colors = ((39, 46, 60),) * 3
        for lane in range(3):
            left_ratio = lane / 3.0
            right_ratio = (lane + 1) / 3.0
            top_left = center - top_half + 2 * top_half * left_ratio
            top_right = center - top_half + 2 * top_half * right_ratio
            bottom_left = center - bottom_half + 2 * bottom_half * left_ratio
            bottom_right = center - bottom_half + 2 * bottom_half * right_ratio
            pygame.draw.polygon(
                screen,
                lane_colors[lane],
                [
                    (top_left, self.ROAD_TOP),
                    (top_right, self.ROAD_TOP),
                    (bottom_right, self.HEIGHT),
                    (bottom_left, self.HEIGHT),
                ],
            )

        for side in (-1, 1):
            top_x = center + side * top_half
            bottom_x = center + side * bottom_half
            pygame.draw.line(
                screen,
                (24, 61, 78),
                (top_x, self.ROAD_TOP),
                (bottom_x, self.HEIGHT),
                8,
            )
            pygame.draw.line(
                screen,
                self.CYAN,
                (top_x, self.ROAD_TOP),
                (bottom_x, self.HEIGHT),
                2,
            )

        for boundary in (1, 2):
            top_x = center + (boundary - 1.5) * (2 * top_half / 3)
            bottom_x = center + (boundary - 1.5) * (2 * bottom_half / 3)
            pygame.draw.line(
                screen,
                (44, 54, 70),
                (top_x, self.ROAD_TOP),
                (bottom_x, self.HEIGHT),
                5,
            )
            pygame.draw.line(
                screen,
                self.LANE_LINE,
                (top_x, self.ROAD_TOP),
                (bottom_x, self.HEIGHT),
                3,
            )

        phase = (self.distance * 9.0) % 46.0
        for index in range(20):
            p = (index * 46.0 + phase) / 920.0
            if not (0.0 <= p <= 1.0):
                continue
            y = self.ROAD_TOP + p * (self.HEIGHT - self.ROAD_TOP)
            half = self._road_half_width(p)
            shade = int(51 + 10 * p)
            pygame.draw.line(
                screen,
                (shade, shade + 7, shade + 17),
                (center - half + 8, y),
                (center + half - 8, y),
                1,
            )

        for boundary in (1, 2):
            top_x = center + (boundary - 1.5) * (2 * top_half / 3)
            bottom_x = center + (boundary - 1.5) * (2 * bottom_half / 3)
            pygame.draw.line(screen, self.CYAN, (top_x, self.ROAD_TOP), (bottom_x, self.HEIGHT), 1)

    def _road_half_width(self, p: float) -> float:
        return 1.5 * self.LANE_WIDTH

    def _project(self, z: float) -> tuple[float, float, float]:
        p = max(0.0, min(1.0, 1.0 - z / self.VIEW_DISTANCE))
        y = self.ROAD_TOP + p * (self.PLAYER_Y + 18 - self.ROAD_TOP)
        return p, y, self.LANE_WIDTH

    def _lane_x(self, lane: int | float, lane_width: float) -> float:
        return self.GAME_W / 2 + (lane - 1) * lane_width

    def _draw_world(self, screen: pygame.Surface) -> None:
        entities: list[tuple[float, str, object]] = []
        entities.extend((o.z, "obstacle", o) for o in self.obstacles if o.z <= self.VIEW_DISTANCE)
        entities.extend(
            (p.z, "pickup", p)
            for p in self.pickups_list
            if p.z <= self.VIEW_DISTANCE and not p.collected
        )
        entities.sort(key=lambda item: item[0], reverse=True)

        for _, kind, entity in entities:
            if kind == "obstacle":
                self._draw_obstacle(screen, entity)
            else:
                self._draw_pickup(screen, entity)

    def _draw_obstacle(self, screen: pygame.Surface, obstacle: Obstacle) -> None:
        p, y, lane_width = self._project(obstacle.z)
        if p < 0.035:
            return
        x = self._lane_x(obstacle.lane, lane_width)
        scale = lane_width / (2 * self._road_half_width(1.0) / 3)

        if obstacle.kind == "block":
            width = lane_width * 0.68
            height = 142.0 * scale
            body = pygame.Rect(0, 0, int(width), int(height))
            body.midbottom = (int(x), int(y))
            shadow_pad = max(2, int(body.width * 0.04))
            pygame.draw.ellipse(
                screen,
                (10, 13, 19),
                (
                    body.left - shadow_pad,
                    body.bottom - max(3, int(8 * scale)),
                    body.width + shadow_pad * 2,
                    max(5, int(18 * scale)),
                ),
            )
            pygame.draw.rect(screen, (63, 71, 87), body, border_radius=max(3, int(7 * scale)))
            inner = body.inflate(-max(4, int(12 * scale)), -max(4, int(12 * scale)))
            pygame.draw.rect(screen, (98, 64, 83), inner, border_radius=max(2, int(5 * scale)))
            pygame.draw.line(screen, self.RED, (body.left + 5, body.top + 5), (body.right - 5, body.top + 5), max(1, int(3 * scale)))
        elif obstacle.kind == "jump":
            width = lane_width * 0.7
            height = 62.0 * scale
            body = pygame.Rect(0, 0, int(width), max(7, int(height)))
            body.midbottom = (int(x), int(y))
            pygame.draw.rect(screen, (113, 64, 34), body, border_radius=max(2, int(5 * scale)))
            pygame.draw.rect(screen, self.ORANGE, (body.left, body.top, body.width, max(3, int(9 * scale))), border_radius=max(1, int(3 * scale)))
            if p > 0.48:
                arrow = self.tiny.render("JUMP", True, self.TEXT)
                screen.blit(arrow, arrow.get_rect(center=(int(x), body.top - 13)))
        else:
            width = lane_width * 0.72
            bar_height = max(8, int(25 * scale))
            bar_y = int(y - 92 * scale)
            pygame.draw.rect(screen, (107, 49, 67), (int(x - width / 2), bar_y, int(width), bar_height), border_radius=max(2, int(4 * scale)))
            pygame.draw.rect(screen, self.RED, (int(x - width / 2), bar_y, int(width), max(3, int(8 * scale))), border_radius=max(2, int(4 * scale)))
            post_width = max(3, int(9 * scale))
            pygame.draw.rect(screen, (82, 40, 57), (int(x - width / 2), bar_y, post_width, int(y - bar_y)))
            pygame.draw.rect(screen, (82, 40, 57), (int(x + width / 2 - post_width), bar_y, post_width, int(y - bar_y)))
            if p > 0.48:
                arrow = self.tiny.render("SLIDE", True, self.TEXT)
                screen.blit(arrow, arrow.get_rect(center=(int(x), bar_y - 13)))

    def _draw_pickup(self, screen: pygame.Surface, pickup: Pickup) -> None:
        p, y, lane_width = self._project(pickup.z)
        if p < 0.03:
            return
        x = self._lane_x(pickup.lane, lane_width)
        scale = lane_width / (2 * self._road_half_width(1.0) / 3)
        radius = max(2, int(13 * scale))
        pickup_y = int(y - 25 * scale)
        pygame.draw.circle(screen, (246, 177, 45), (int(x), pickup_y), radius)
        pygame.draw.circle(
            screen,
            (255, 239, 166),
            (int(x - radius * 0.25), pickup_y - max(1, int(radius * 0.25))),
            max(1, radius // 3),
        )

    def _draw_player(self, screen: pygame.Surface) -> None:
        lane_width = self.LANE_WIDTH
        x = self._lane_x(self.player_lane, lane_width)
        y = self.PLAYER_Y
        vertical_offset = self.player_height * 55.0
        shadow_width = int(max(18, 42 - vertical_offset * 0.18))
        pygame.draw.ellipse(
            screen,
            (10, 15, 20),
            (int(x - shadow_width), y + 5, shadow_width * 2, max(8, shadow_width // 2)),
        )

        flicker = self.invulnerable > 0 and int(self.invulnerable * 18) % 2 == 0
        if flicker:
            return

        if self.mode == "sliding":
            body = pygame.Rect(0, 0, 52, 28)
            body.center = (int(x), int(y - 12))
            pygame.draw.ellipse(screen, self.CYAN, body)
            pygame.draw.ellipse(screen, (205, 255, 255), body, 2)
        else:
            center = (int(x), int(y - 16 - vertical_offset))
            pygame.draw.circle(screen, (32, 107, 117), center, 26)
            pygame.draw.circle(screen, self.CYAN, center, 21)
            pygame.draw.circle(screen, (225, 255, 255), (center[0] - 6, center[1] - 7), 7)

        if self.mode == "jumping":
            pygame.draw.arc(
                screen,
                (117, 245, 242),
                (int(x - 31), int(y - 25), 62, 30),
                math.pi,
                math.tau,
                2,
            )

    def _draw_game_hud(self, screen: pygame.Surface) -> None:
        overlay = pygame.Surface((self.GAME_W, 70), pygame.SRCALPHA)
        overlay.fill((8, 11, 18, 155))
        screen.blit(overlay, (0, 64))
        screen.blit(self.small.render("SCORE", True, self.MUTED), (26, 76))
        screen.blit(self.font.render(f"{int(self.score):07d}", True, self.TEXT), (26, 98))
        screen.blit(self.small.render("DISTANCE", True, self.MUTED), (225, 76))
        screen.blit(self.font.render(f"{int(self.distance)} m", True, self.TEXT), (225, 98))
        screen.blit(self.small.render("COMBO", True, self.MUTED), (400, 76))
        screen.blit(self.font.render(f"x{1 + self.combo // 10}", True, self.GOLD), (400, 98))

        for index in range(3):
            color = self.RED if index < self.lives else (65, 71, 85)
            center = (665 + index * 34, 98)
            pygame.draw.circle(screen, color, center, 11)
            pygame.draw.circle(screen, (255, 184, 184) if index < self.lives else (91, 98, 116), center, 11, 1)

    def _draw_side_hud(self, screen: pygame.Surface) -> None:
        pygame.draw.rect(screen, self.PANEL, (self.HUD_X, 64, self.WIDTH - self.HUD_X, self.HEIGHT - 64))
        screen.blit(self.font.render("RUN STATUS", True, self.TEXT), (self.HUD_X + 28, 94))
        screen.blit(self.small.render("Keyboard simulator active", True, self.CYAN), (self.HUD_X + 28, 130))

        action_text = self.mode.upper()
        details = [
            f"Lane: {self.target_lane + 1} / 3",
            f"Action: {action_text}",
            f"Speed: {self.speed:.0f}",
            f"Pickups: {self.pickups}",
            f"Best: {self.best_score}",
        ]
        for index, line in enumerate(details):
            screen.blit(self.small.render(line, True, self.MUTED), (self.HUD_X + 28, 176 + index * 31))

        meter = pygame.Rect(self.HUD_X + 28, 352, 250, 115)
        pygame.draw.rect(screen, self.PANEL_2, meter, border_radius=12)
        pygame.draw.line(screen, (91, 109, 135), (meter.left + 35, meter.centery), (meter.right - 35, meter.centery), 2)
        for lane in range(3):
            x = meter.left + 35 + lane * (meter.width - 70) / 2
            pygame.draw.line(screen, (91, 109, 135), (x, meter.centery - 10), (x, meter.centery + 10), 2)
        dot_x = meter.left + 35 + self.player_lane * (meter.width - 70) / 2
        pygame.draw.circle(screen, self.CYAN, (int(dot_x), meter.centery), 10)
        screen.blit(self.tiny.render("LANE POSITION", True, self.MUTED), (meter.left + 12, meter.top + 10))

        action_y = 497
        jump_color = self.CYAN if self.mode != "jumping" else self.ORANGE
        slide_color = self.CYAN if self.mode != "sliding" else self.ORANGE
        pygame.draw.circle(screen, jump_color, (self.HUD_X + 39, action_y + 11), 6)
        screen.blit(self.small.render("Jump action", True, self.TEXT), (self.HUD_X + 54, action_y))
        pygame.draw.circle(screen, slide_color, (self.HUD_X + 39, action_y + 45), 6)
        screen.blit(self.small.render("Slide action", True, self.TEXT), (self.HUD_X + 54, action_y + 34))

        self._button(
            screen,
            pygame.Rect(self.HUD_X + 28, 596, 118, 45),
            "PAUSE",
            "pause",
        )
        self._button(
            screen,
            pygame.Rect(self.HUD_X + 160, 596, 118, 45),
            "RESTART",
            "restart",
        )
        self._button(
            screen,
            pygame.Rect(self.HUD_X + 28, 657, 250, 45),
            "GAME SELECT",
            "exit",
        )

    def _draw_pause_overlay(self, screen: pygame.Surface) -> None:
        overlay = pygame.Surface((self.WIDTH, self.HEIGHT), pygame.SRCALPHA)
        overlay.fill((4, 7, 13, 185))
        screen.blit(overlay, (0, 0))
        title = self.title.render("PAUSED", True, self.TEXT)
        screen.blit(title, title.get_rect(center=(self.WIDTH // 2, 235)))
        hint = self.font.render("Put the controller back near neutral before resuming.", True, self.MUTED)
        screen.blit(hint, hint.get_rect(center=(self.WIDTH // 2, 300)))
        self._button(
            screen,
            pygame.Rect(self.WIDTH // 2 - 135, 365, 270, 58),
            "RESUME",
            "resume",
            primary=True,
        )
        self._button(
            screen,
            pygame.Rect(self.WIDTH // 2 - 135, 440, 270, 52),
            "RESTART",
            "restart",
        )
        self._button(
            screen,
            pygame.Rect(self.WIDTH // 2 - 135, 510, 270, 52),
            "BACK TO MENU",
            "menu",
        )

    def _draw_game_over_overlay(self, screen: pygame.Surface) -> None:
        overlay = pygame.Surface((self.WIDTH, self.HEIGHT), pygame.SRCALPHA)
        overlay.fill((4, 7, 13, 195))
        screen.blit(overlay, (0, 0))
        title = self.big.render("RUN COMPLETE", True, self.TEXT)
        screen.blit(title, title.get_rect(center=(self.WIDTH // 2, 210)))
        score = self.title.render(f"{int(self.score)}", True, self.CYAN)
        screen.blit(score, score.get_rect(center=(self.WIDTH // 2, 285)))
        detail = self.font.render(
            f"Distance {int(self.distance)} m   |   Pickups {self.pickups}   |   Best {self.best_score}",
            True,
            self.MUTED,
        )
        screen.blit(detail, detail.get_rect(center=(self.WIDTH // 2, 345)))
        self._button(
            screen,
            pygame.Rect(self.WIDTH // 2 - 135, 420, 270, 58),
            "RUN AGAIN",
            "restart",
            primary=True,
        )
        self._button(
            screen,
            pygame.Rect(self.WIDTH // 2 - 135, 495, 270, 52),
            "BACK TO MENU",
            "menu",
        )
