
import math
import sys
import pygame

pygame.init()

# Disable text-input/IME composition for this game window.
# We only need physical game-control keys.
try:
    pygame.key.stop_text_input()
except Exception:
    pass

WIDTH, HEIGHT = 1100, 720
GAME_W = 820
HUD_X = GAME_W
FPS = 60

screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Motion Golf - Stage 1 v4")
clock = pygame.time.Clock()

FONT = pygame.font.SysFont("arial", 22)
SMALL = pygame.font.SysFont("arial", 17)
BIG = pygame.font.SysFont("arial", 44, bold=True)

BG = (24, 30, 35)
GRASS = (79, 143, 78)
GRASS_2 = (70, 132, 70)
WHITE = (245, 245, 245)
BLACK = (20, 20, 20)
WALL = (92, 92, 92)
WALL_EDGE = (55, 55, 55)
LOW_WALL = (38, 48, 55)
LOW_WALL_EDGE = (16, 21, 25)
LOW_WALL_HIGHLIGHT = (72, 84, 92)
SAND = (220, 195, 132)
WATER = (65, 145, 200)
PANEL = (32, 39, 45)
TEXT = (235, 239, 242)
MUTED = (170, 180, 187)
ACCENT = (120, 210, 145)
RED = (220, 95, 95)
BUTTON = (58, 70, 78)
BUTTON_HOVER = (72, 86, 95)

PLAY_RECT = pygame.Rect(20, 80, GAME_W - 40, 560)

LEVELS = [
    {
        "name": "Fairway Start",
        "spawn": (110, 155),
        "hole": (715, 520),
        "walls": [
            pygame.Rect(310, 205, 36, 230),
            pygame.Rect(500, 120, 190, 34),
        ],
        "low_walls": [],
        "sand": [pygame.Rect(430, 420, 170, 95)],
        "water": [pygame.Rect(590, 260, 150, 100)],
    },
    {
        "name": "Twisted Path",
        "spawn": (110, 155),
        "hole": (745, 550),
        "walls": [
            pygame.Rect(235, 80, 30, 330),
            pygame.Rect(385, 330, 30, 310),
            pygame.Rect(530, 80, 30, 340),
            pygame.Rect(265, 205, 120, 24),
            pygame.Rect(415, 255, 115, 24),
            pygame.Rect(560, 455, 155, 24),
            pygame.Rect(75, 300, 25, 150),
            pygame.Rect(650, 95, 26, 180),
            pygame.Rect(165, 520, 75, 24),
        ],
        "low_walls": [],
        "sand": [pygame.Rect(290, 470, 85, 65)],
        "water": [pygame.Rect(445, 440, 60, 65)],
    },
    {
        "name": "Hazard Circuit",
        "spawn": (100, 150),
        "hole": (735, 565),
        "walls": [
            pygame.Rect(190, 80, 28, 265),
            pygame.Rect(320, 300, 28, 340),
            pygame.Rect(450, 80, 28, 300),
            pygame.Rect(580, 280, 28, 360),
            pygame.Rect(220, 410, 100, 24),
            pygame.Rect(355, 500, 80, 24),
            pygame.Rect(478, 185, 102, 24),
            pygame.Rect(610, 390, 120, 24),
            pygame.Rect(45, 430, 120, 24),
        ],
        "low_walls": [
            pygame.Rect(218, 300, 102, 10),
            pygame.Rect(348, 350, 102, 10),
            pygame.Rect(478, 250, 102, 10),
            pygame.Rect(608, 500, 150, 10),
        ],
        "sand": [
            pygame.Rect(225, 380, 85, 55),
            pygame.Rect(365, 220, 70, 60),
            pygame.Rect(630, 440, 80, 60),
        ],
        "water": [
            pygame.Rect(55, 250, 80, 70),
            pygame.Rect(485, 405, 80, 65),
            pygame.Rect(665, 530, 65, 55),
        ],
    },
]

current_level = 0
walls = []
low_walls = []
sand_rects = []
water_rects = []
hole_pos = pygame.Vector2()
hole_radius = 16

BALL_RADIUS = 12
spawn_pos = pygame.Vector2()
ball_pos = spawn_pos.copy()
ball_vel = pygame.Vector2()
ball_height = 0.0
jump_velocity = 0.0

roll = 0.0
pitch = 0.0

sensitivity = 520.0
grass_drag = 0.985
sand_drag = 0.91
max_speed = 360.0
jump_power = 370.0
jump_gravity = 900.0
low_wall_clear_height = 28.0

paused = False
level_complete = False
water_penalty = 0.0
start_ticks = pygame.time.get_ticks()
pause_started = None
paused_total_ms = 0

# IMPORTANT:
# Do NOT use pygame.key.get_pressed().
# We maintain our own held-key set from KEYDOWN / KEYUP.
held_keys = set()

last_event = "Waiting for input"
status_message = "Keyboard control ready"

pause_btn = pygame.Rect(HUD_X + 28, 607, 105, 42)
restart_btn = pygame.Rect(HUD_X + 145, 607, 105, 42)
prev_level_btn = pygame.Rect(HUD_X + 28, 155, 105, 38)
next_level_btn = pygame.Rect(HUD_X + 147, 155, 105, 38)


def reset_ball(penalty=0.0):
    global ball_pos, ball_vel, ball_height, jump_velocity, water_penalty
    ball_pos = spawn_pos.copy()
    ball_vel.update(0, 0)
    ball_height = 0.0
    jump_velocity = 0.0
    water_penalty += penalty


def load_level(index):
    global current_level, walls, low_walls, sand_rects, water_rects
    global hole_pos, spawn_pos, paused, level_complete
    global start_ticks, pause_started, paused_total_ms, water_penalty
    global last_event, status_message

    current_level = max(0, min(index, len(LEVELS) - 1))
    level = LEVELS[current_level]
    walls = [wall.copy() for wall in level["walls"]]
    low_walls = [wall.copy() for wall in level["low_walls"]]
    sand_rects = [sand.copy() for sand in level["sand"]]
    water_rects = [water.copy() for water in level["water"]]
    hole_pos = pygame.Vector2(level["hole"])
    spawn_pos = pygame.Vector2(level["spawn"])

    held_keys.clear()
    paused = False
    level_complete = False
    water_penalty = 0.0
    start_ticks = pygame.time.get_ticks()
    pause_started = None
    paused_total_ms = 0
    reset_ball(0)
    last_event = "Level loaded"
    status_message = f"Level {current_level + 1}: {level['name']}"


def restart_game():
    global paused, level_complete, water_penalty
    global start_ticks, pause_started, paused_total_ms
    global status_message
    held_keys.clear()
    paused = False
    level_complete = False
    water_penalty = 0.0
    start_ticks = pygame.time.get_ticks()
    pause_started = None
    paused_total_ms = 0
    reset_ball(0)
    status_message = f"Level {current_level + 1} restarted"


def toggle_pause():
    global paused, pause_started, paused_total_ms, status_message
    now = pygame.time.get_ticks()
    if not paused:
        paused = True
        pause_started = now
        held_keys.clear()
        status_message = "Paused"
    else:
        paused = False
        if pause_started is not None:
            paused_total_ms += now - pause_started
        pause_started = None
        status_message = "Resumed"


def switch_level(delta):
    target = max(0, min(current_level + delta, len(LEVELS) - 1))
    if target != current_level:
        load_level(target)


def circle_rect_collision(center, radius, rect):
    nearest_x = max(rect.left, min(center.x, rect.right))
    nearest_y = max(rect.top, min(center.y, rect.bottom))
    dx = center.x - nearest_x
    dy = center.y - nearest_y
    return dx * dx + dy * dy < radius * radius


def point_in_any_rect(point, rects):
    return any(r.collidepoint(point.x, point.y) for r in rects)


def resolve_rect_collision(rect, old_pos):
    global ball_pos, ball_vel

    if not circle_rect_collision(ball_pos, BALL_RADIUS, rect):
        return

    test_x = pygame.Vector2(ball_pos.x, old_pos.y)
    test_y = pygame.Vector2(old_pos.x, ball_pos.y)
    hit_x = circle_rect_collision(test_x, BALL_RADIUS, rect)
    hit_y = circle_rect_collision(test_y, BALL_RADIUS, rect)

    if hit_x and not hit_y:
        ball_pos.x = old_pos.x
        ball_vel.x *= -0.35
    elif hit_y and not hit_x:
        ball_pos.y = old_pos.y
        ball_vel.y *= -0.35
    else:
        ball_pos = old_pos.copy()
        ball_vel *= -0.25


def resolve_wall_collision(old_pos):
    for wall in walls:
        resolve_rect_collision(wall, old_pos)

    if ball_height < low_wall_clear_height:
        for low_wall in low_walls:
            resolve_rect_collision(low_wall, old_pos)


def update_input_from_held():
    global roll, pitch

    left = pygame.K_a in held_keys or pygame.K_LEFT in held_keys
    right = pygame.K_d in held_keys or pygame.K_RIGHT in held_keys
    up = pygame.K_w in held_keys or pygame.K_UP in held_keys
    down = pygame.K_s in held_keys or pygame.K_DOWN in held_keys

    roll = float(right) - float(left)
    pitch = float(down) - float(up)


def update_physics(dt):
    global ball_pos, ball_vel, ball_height, jump_velocity, level_complete

    if paused or level_complete:
        return

    accel = pygame.Vector2(roll, pitch)
    if accel.length_squared() > 1:
        accel = accel.normalize()

    ball_vel += accel * sensitivity * dt

    drag = sand_drag if point_in_any_rect(ball_pos, sand_rects) else grass_drag
    ball_vel *= drag ** (dt * 60)

    if ball_vel.length() > max_speed:
        ball_vel.scale_to_length(max_speed)

    old_pos = ball_pos.copy()
    ball_pos += ball_vel * dt

    if ball_pos.x - BALL_RADIUS < PLAY_RECT.left:
        ball_pos.x = PLAY_RECT.left + BALL_RADIUS
        ball_vel.x *= -0.35
    elif ball_pos.x + BALL_RADIUS > PLAY_RECT.right:
        ball_pos.x = PLAY_RECT.right - BALL_RADIUS
        ball_vel.x *= -0.35

    if ball_pos.y - BALL_RADIUS < PLAY_RECT.top:
        ball_pos.y = PLAY_RECT.top + BALL_RADIUS
        ball_vel.y *= -0.35
    elif ball_pos.y + BALL_RADIUS > PLAY_RECT.bottom:
        ball_pos.y = PLAY_RECT.bottom - BALL_RADIUS
        ball_vel.y *= -0.35

    resolve_wall_collision(old_pos)

    if ball_height > 0 or jump_velocity > 0:
        jump_velocity -= jump_gravity * dt
        ball_height += jump_velocity * dt
        if ball_height <= 0:
            ball_height = 0
            jump_velocity = 0

    if ball_height < 12 and point_in_any_rect(ball_pos, water_rects):
        reset_ball(3.0)

    if (
        ball_height == 0
        and ball_pos.distance_to(hole_pos) < hole_radius + 4
        and ball_vel.length() < 95
    ):
        level_complete = True
        ball_vel.update(0, 0)


def current_elapsed_seconds():
    now = pygame.time.get_ticks()
    extra_pause = 0
    if paused and pause_started is not None:
        extra_pause = now - pause_started
    active_ms = now - start_ticks - paused_total_ms - extra_pause
    return max(0.0, active_ms / 1000.0)


def draw_button(rect, label, enabled=True):
    mouse = pygame.mouse.get_pos()
    if enabled:
        color = BUTTON_HOVER if rect.collidepoint(mouse) else BUTTON
        text_color = TEXT
        border_color = MUTED
    else:
        color = (42, 48, 53)
        text_color = (92, 102, 109)
        border_color = (70, 78, 84)
    pygame.draw.rect(screen, color, rect, border_radius=8)
    pygame.draw.rect(screen, border_color, rect, 1, border_radius=8)
    txt = SMALL.render(label, True, text_color)
    screen.blit(txt, txt.get_rect(center=rect.center))


def draw_course():
    screen.fill(BG)

    pygame.draw.rect(screen, PANEL, (0, 0, WIDTH, 62))
    screen.blit(FONT.render("MOTION GOLF", True, TEXT), (24, 10))
    screen.blit(SMALL.render("COURSE SELECT EDITION", True, MUTED), (24, 39))
    screen.blit(
        FONT.render(f"LEVEL {current_level + 1:02d} / {len(LEVELS):02d}", True, ACCENT),
        (570, 10),
    )
    screen.blit(
        SMALL.render(LEVELS[current_level]["name"].upper(), True, TEXT),
        (570, 39),
    )

    pygame.draw.rect(screen, GRASS, PLAY_RECT, border_radius=18)

    for y in range(PLAY_RECT.top + 18, PLAY_RECT.bottom - 10, 52):
        pygame.draw.line(
            screen, GRASS_2,
            (PLAY_RECT.left + 16, y),
            (PLAY_RECT.right - 16, y),
            2
        )

    for r in sand_rects:
        pygame.draw.ellipse(screen, SAND, r)

    for r in water_rects:
        pygame.draw.ellipse(screen, WATER, r)

    for wall in walls:
        pygame.draw.rect(screen, WALL_EDGE, wall.inflate(5, 5), border_radius=5)
        pygame.draw.rect(screen, WALL, wall, border_radius=4)

    for low_wall in low_walls:
        pygame.draw.rect(screen, LOW_WALL_EDGE, low_wall.inflate(3, 3), border_radius=2)
        pygame.draw.rect(screen, LOW_WALL, low_wall, border_radius=2)
        pygame.draw.line(
            screen,
            LOW_WALL_HIGHLIGHT,
            (low_wall.left + 4, low_wall.top + 2),
            (low_wall.right - 4, low_wall.top + 2),
            1,
        )

    pygame.draw.circle(screen, BLACK, hole_pos, hole_radius)
    pygame.draw.line(
        screen, WHITE,
        (int(hole_pos.x), int(hole_pos.y)),
        (int(hole_pos.x), int(hole_pos.y - 55)),
        3
    )
    pygame.draw.polygon(
        screen, RED,
        [
            (hole_pos.x, hole_pos.y - 55),
            (hole_pos.x + 34, hole_pos.y - 44),
            (hole_pos.x, hole_pos.y - 34),
        ],
    )

    shadow_scale = max(5, BALL_RADIUS - int(ball_height / 22))
    pygame.draw.ellipse(
        screen,
        (50, 70, 55),
        (
            int(ball_pos.x - shadow_scale),
            int(ball_pos.y + 8 - shadow_scale / 2),
            shadow_scale * 2,
            shadow_scale,
        ),
    )

    draw_y = int(ball_pos.y - ball_height * 0.20)
    pygame.draw.circle(screen, WHITE, (int(ball_pos.x), draw_y), BALL_RADIUS)
    pygame.draw.circle(screen, (190, 195, 200), (int(ball_pos.x - 4), draw_y - 4), 2)

    pygame.draw.rect(screen, PANEL, (HUD_X, 62, WIDTH - HUD_X, HEIGHT - 62))
    screen.blit(FONT.render("LEVEL SELECT", True, TEXT), (HUD_X + 28, 92))
    screen.blit(SMALL.render("Choose your course", True, ACCENT), (HUD_X + 28, 124))

    draw_button(prev_level_btn, "< PREV", current_level > 0)
    draw_button(next_level_btn, "NEXT >", current_level < len(LEVELS) - 1)

    for index in range(len(LEVELS)):
        dot_color = ACCENT if index == current_level else (82, 94, 102)
        pygame.draw.circle(screen, dot_color, (HUD_X + 37 + index * 17, 209), 5)

    screen.blit(
        FONT.render(f"{current_level + 1:02d}  {LEVELS[current_level]['name']}", True, TEXT),
        (HUD_X + 28, 222),
    )

    values = [
        f"Roll:  {roll:+.0f}",
        f"Pitch: {pitch:+.0f}",
        f"Speed: {ball_vel.length():.0f}",
        f"Jump:  {'AIR' if ball_height > 0 else 'READY'}",
    ]
    for i, line in enumerate(values):
        screen.blit(FONT.render(line, True, TEXT), (HUD_X + 28, 260 + i * 30))

    screen.blit(SMALL.render("Last event:", True, MUTED), (HUD_X + 28, 382))
    screen.blit(SMALL.render(last_event[:28], True, TEXT), (HUD_X + 28, 404))
    screen.blit(SMALL.render(status_message[:30], True, MUTED), (HUD_X + 28, 426))

    indicator = pygame.Rect(HUD_X + 35, 452, 210, 80)
    pygame.draw.rect(screen, (42, 49, 55), indicator, border_radius=12)
    center = pygame.Vector2(indicator.center)
    pygame.draw.line(screen, MUTED, (center.x - 70, center.y), (center.x + 70, center.y), 2)
    pygame.draw.line(screen, MUTED, (center.x, center.y - 25), (center.x, center.y + 25), 2)
    dot = center + pygame.Vector2(roll * 18, pitch * 14)
    pygame.draw.circle(screen, ACCENT, dot, 8)

    final_time = current_elapsed_seconds() + water_penalty
    screen.blit(FONT.render(f"Time: {final_time:05.1f}s", True, TEXT), (HUD_X + 28, 542))
    screen.blit(SMALL.render(f"Water penalty: +{water_penalty:.0f}s", True, MUTED), (HUD_X + 28, 574))

    draw_button(pause_btn, "Resume" if paused else "Pause")
    draw_button(restart_btn, "Restart")

    screen.blit(SMALL.render("WASD = tilt | Space = jump", True, MUTED), (HUD_X + 28, 665))
    footer_hint = "Thin dark wall = jumpable" if low_walls else "[ / ] = level | Space = jump"
    screen.blit(SMALL.render(footer_hint, True, MUTED), (HUD_X + 28, 688))

    if paused:
        overlay = pygame.Surface((GAME_W, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 115))
        screen.blit(overlay, (0, 0))
        txt = BIG.render("PAUSED", True, WHITE)
        screen.blit(txt, txt.get_rect(center=(GAME_W // 2, HEIGHT // 2)))

    if level_complete:
        overlay = pygame.Surface((GAME_W, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 145))
        screen.blit(overlay, (0, 0))
        txt = BIG.render("LEVEL COMPLETE!", True, WHITE)
        screen.blit(txt, txt.get_rect(center=(GAME_W // 2, 320)))
        if current_level < len(LEVELS) - 1:
            message = "Click NEXT to play the next level"
        else:
            message = "Click PREV to revisit a level"
        sub = FONT.render(message, True, ACCENT)
        screen.blit(sub, sub.get_rect(center=(GAME_W // 2, 380)))


load_level(0)
running = True

while running:
    dt = min(clock.tick(FPS) / 1000.0, 0.05)

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

        elif event.type == pygame.WINDOWFOCUSLOST:
            held_keys.clear()
            last_event = "Window focus lost"

        elif event.type == pygame.WINDOWFOCUSGAINED:
            last_event = "Window focus gained"

        elif event.type == pygame.KEYDOWN:
            last_event = f"KEYDOWN {pygame.key.name(event.key)}"
            held_keys.add(event.key)

            if event.key == pygame.K_ESCAPE:
                running = False

            elif event.key == pygame.K_LEFTBRACKET:
                switch_level(-1)

            elif event.key == pygame.K_RIGHTBRACKET:
                switch_level(1)

            elif event.key == pygame.K_SPACE:
                if not paused and not level_complete and ball_height == 0:
                    jump_velocity = jump_power
                    status_message = "Jump triggered"

            # F-keys are used as optional shortcuts because they bypass most IME text handling.
            elif event.key == pygame.K_F1:
                toggle_pause()

            elif event.key == pygame.K_F2:
                restart_game()

            # P/R kept as optional shortcuts only.
            elif event.key == pygame.K_p:
                toggle_pause()

            elif event.key == pygame.K_r:
                restart_game()

        elif event.type == pygame.KEYUP:
            last_event = f"KEYUP {pygame.key.name(event.key)}"
            held_keys.discard(event.key)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            last_event = f"Mouse click {event.pos}"
            if prev_level_btn.collidepoint(event.pos) and current_level > 0:
                switch_level(-1)
            elif (
                next_level_btn.collidepoint(event.pos)
                and current_level < len(LEVELS) - 1
            ):
                switch_level(1)
            elif pause_btn.collidepoint(event.pos):
                toggle_pause()
            elif restart_btn.collidepoint(event.pos):
                restart_game()

    update_input_from_held()
    update_physics(dt)
    draw_course()
    pygame.display.flip()

pygame.quit()
sys.exit()
