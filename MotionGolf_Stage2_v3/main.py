import math
import sys
import pygame

pygame.init()
try:
    pygame.key.stop_text_input()
except Exception:
    pass

WIDTH, HEIGHT = 1180, 760
GAME_W = 860
HUD_X = GAME_W
FPS = 60

screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption('Motion Golf - Stage 2 v3')
clock = pygame.time.Clock()

FONT = pygame.font.SysFont('arial', 23)
SMALL = pygame.font.SysFont('arial', 17)
TINY = pygame.font.SysFont('arial', 14)
BIG = pygame.font.SysFont('arial', 48, bold=True)
TITLE = pygame.font.SysFont('arial', 62, bold=True)

BG=(22,28,31); PANEL=(31,38,42); PANEL2=(40,48,53); TEXT=(240,244,246); MUTED=(169,180,186)
ACCENT=(112,207,139); ACCENT2=(83,176,113); GRASS=(83,147,79); GRASS2=(73,134,70)
WHITE=(248,248,248); BLACK=(18,18,18); WALL=(99,100,103); WALL_EDGE=(55,57,60)
LOW_WALL=(132,112,84); SAND=(222,198,137); WATER=(64,148,204); WATER_LIGHT=(166,216,242)
RED=(224,95,95); YELLOW=(235,202,90)

PLAY_RECT = pygame.Rect(24, 90, GAME_W-48, HEIGHT-120)

MENU='menu'; LEVEL_SELECT='level_select'; SETTINGS='settings'; PLAYING='playing'; PAUSED='paused'; LEVEL_COMPLETE='level_complete'; GAME_COMPLETE='game_complete'
state = MENU
current_level = 0
held_keys = set()

settings = {
    'sensitivity':520.0,
    'max_speed':360.0,
    'grass_drag':0.985,
    'jump_power':370.0,
    'jump_gravity':900.0,
    'hole_speed_limit':95.0,

    # Sand trap behavior:
    # while grounded in sand, tilt has almost no effect and the ball stops quickly.
    # once airborne, normal movement returns so the player can jump out.
    'sand_accel_multiplier':0.025,
    'sand_ground_drag':0.50,
    'sand_max_speed':14.0,
}
difficulty_name = 'Normal'

levels = [
    {'name':'Level 1 - First Roll','spawn':(120,180),'hole':(720,530),'walls':[],'low_walls':[],'sand':[],'water':[],'par':24},
    {'name':'Level 2 - Around the Wall','spawn':(110,160),'hole':(710,520),'walls':[(350,160,38,310),(515,370,190,36)],'low_walls':[],'sand':[],'water':[],'par':36},
    {'name':'Level 3 - Sand Choice','spawn':(120,180),'hole':(720,520),'walls':[(520,145,34,175)],'low_walls':[],'sand':[(300,290,260,150)],'water':[],'par':42},
    {'name':'Level 4 - Water Hazard','spawn':(110,165),'hole':(720,530),'walls':[(360,170,34,190)],'low_walls':[],'sand':[(540,410,150,95)],'water':[(410,325,220,120)],'par':48},
    {'name':'Level 5 - Jump Challenge','spawn':(110,170),'hole':(730,520),'walls':[(520,120,35,175)],'low_walls':[(315,270,210,28)],'sand':[(530,430,150,95)],'water':[(600,250,140,105)],'par':58},
]

BALL_RADIUS=12; hole_radius=17; low_wall_clear_height=28.0
ball_pos=pygame.Vector2(levels[0]['spawn']); ball_vel=pygame.Vector2(); ball_height=0.0; jump_velocity=0.0
roll=0.0; pitch=0.0; water_penalty=0.0; start_ticks=pygame.time.get_ticks(); paused_total_ms=0; pause_started=None
level_finish_time=0.0; stars_earned=0
ball_sinking=False; sink_progress=0.0; sink_duration=0.45


def apply_difficulty(name):
    global difficulty_name
    difficulty_name=name

    if name=='Easy':
        settings.update({
            'sensitivity':430.0,
            'max_speed':300.0,
            'grass_drag':0.982,
            'jump_power':390.0,
            'hole_speed_limit':120.0,
            'sand_accel_multiplier':0.040,
            'sand_ground_drag':0.55,
            'sand_max_speed':18.0,
        })
    elif name=='Hard':
        settings.update({
            'sensitivity':620.0,
            'max_speed':430.0,
            'grass_drag':0.989,
            'jump_power':350.0,
            'hole_speed_limit':75.0,
            'sand_accel_multiplier':0.015,
            'sand_ground_drag':0.45,
            'sand_max_speed':10.0,
        })
    else:
        settings.update({
            'sensitivity':520.0,
            'max_speed':360.0,
            'grass_drag':0.985,
            'jump_power':370.0,
            'hole_speed_limit':95.0,
            'sand_accel_multiplier':0.025,
            'sand_ground_drag':0.50,
            'sand_max_speed':14.0,
        })


def rects_from(data): return [pygame.Rect(*r) for r in data]
def level(): return levels[current_level]
def spawn_point(): return pygame.Vector2(level()['spawn'])
def hole_point(): return pygame.Vector2(level()['hole'])

def set_state(s):
    global state, roll, pitch
    held_keys.clear(); state=s; roll=pitch=0.0

def reset_ball(penalty=0.0):
    global ball_pos, ball_height, jump_velocity, water_penalty
    global ball_sinking, sink_progress
    ball_pos=spawn_point()
    ball_vel.update(0,0)
    ball_height=0.0
    jump_velocity=0.0
    ball_sinking=False
    sink_progress=0.0
    water_penalty += penalty

def begin_level(i):
    global current_level,state,water_penalty,start_ticks,paused_total_ms,pause_started
    current_level=i; state=PLAYING; held_keys.clear(); water_penalty=0.0; start_ticks=pygame.time.get_ticks(); paused_total_ms=0; pause_started=None; reset_ball(0)

def restart_level(): begin_level(current_level)

def current_elapsed():
    now=pygame.time.get_ticks(); extra=0
    if state==PAUSED and pause_started is not None: extra=now-pause_started
    return max(0.0,(now-start_ticks-paused_total_ms-extra)/1000.0)

def toggle_pause():
    global state,pause_started,paused_total_ms
    now=pygame.time.get_ticks()
    if state==PLAYING:
        state=PAUSED; pause_started=now; held_keys.clear()
    elif state==PAUSED:
        state=PLAYING
        if pause_started is not None: paused_total_ms += now-pause_started
        pause_started=None

def complete_level():
    global state,level_finish_time,stars_earned
    level_finish_time=current_elapsed()+water_penalty
    par=level()['par']
    stars_earned=3 if level_finish_time<=par else 2 if level_finish_time<=par*1.35 else 1
    ball_vel.update(0,0); state=LEVEL_COMPLETE

def next_level():
    if current_level+1 < len(levels): begin_level(current_level+1)
    else: set_state(GAME_COMPLETE)

def circle_rect_collision(center,radius,rect):
    nx=max(rect.left,min(center.x,rect.right)); ny=max(rect.top,min(center.y,rect.bottom)); dx=center.x-nx; dy=center.y-ny
    return dx*dx+dy*dy < radius*radius

def point_in_any_rect(point,rects): return any(r.collidepoint(point.x,point.y) for r in rects)

def resolve_one_wall(old_pos,wall):
    global ball_pos, ball_vel
    tx=pygame.Vector2(ball_pos.x,old_pos.y); ty=pygame.Vector2(old_pos.x,ball_pos.y)
    hx=circle_rect_collision(tx,BALL_RADIUS,wall); hy=circle_rect_collision(ty,BALL_RADIUS,wall)
    if hx and not hy:
        ball_pos.x=old_pos.x
        ball_vel.x=-ball_vel.x*0.35
    elif hy and not hx:
        ball_pos.y=old_pos.y
        ball_vel.y=-ball_vel.y*0.35
    else:
        ball_pos=old_pos.copy()
        ball_vel.x=-ball_vel.x*0.25
        ball_vel.y=-ball_vel.y*0.25

def resolve_wall_collision(old_pos):
    for r in rects_from(level()['walls']):
        if circle_rect_collision(ball_pos,BALL_RADIUS,r): resolve_one_wall(old_pos,r)
    if ball_height < low_wall_clear_height:
        for r in rects_from(level()['low_walls']):
            if circle_rect_collision(ball_pos,BALL_RADIUS,r): resolve_one_wall(old_pos,r)

def update_input():
    global roll,pitch
    left=pygame.K_a in held_keys or pygame.K_LEFT in held_keys; right=pygame.K_d in held_keys or pygame.K_RIGHT in held_keys
    up=pygame.K_w in held_keys or pygame.K_UP in held_keys; down=pygame.K_s in held_keys or pygame.K_DOWN in held_keys
    roll=float(right)-float(left); pitch=float(down)-float(up)

def update_physics(dt):
    global ball_pos, ball_height, jump_velocity
    global ball_sinking, sink_progress

    if state!=PLAYING:
        return

    # Once the ball has fully entered the hole, stop normal physics and play
    # a short sinking animation before completing the level.
    if ball_sinking:
        ball_vel.update(0,0)
        sink_progress += dt / sink_duration
        if sink_progress >= 1.0:
            sink_progress = 1.0
            complete_level()
        return

    accel=pygame.Vector2(roll,pitch)
    if accel.length_squared()>1:
        accel=accel.normalize()

    sand_rects=rects_from(level()['sand'])

    # Sand only traps the ball while it is on/near the ground.
    # When airborne, the sand no longer applies its heavy resistance,
    # so the intended escape method is to jump while tilting.
    grounded_in_sand = ball_height < 8 and point_in_any_rect(ball_pos, sand_rects)

    if grounded_in_sand:
        ball_vel.xy = ball_vel + accel * settings['sensitivity'] * settings['sand_accel_multiplier'] * dt
        ball_vel.xy = ball_vel * (settings['sand_ground_drag'] ** (dt*60))
        if ball_vel.length() > settings['sand_max_speed']:
            ball_vel.scale_to_length(settings['sand_max_speed'])
    else:
        ball_vel.xy = ball_vel + accel * settings['sensitivity'] * dt
        ball_vel.xy = ball_vel * (settings['grass_drag'] ** (dt*60))
        if ball_vel.length() > settings['max_speed']:
            ball_vel.scale_to_length(settings['max_speed'])

    old=ball_pos.copy()
    ball_pos += ball_vel*dt

    if ball_pos.x-BALL_RADIUS<PLAY_RECT.left:
        ball_pos.x=PLAY_RECT.left+BALL_RADIUS
        ball_vel.x*=-0.35
    elif ball_pos.x+BALL_RADIUS>PLAY_RECT.right:
        ball_pos.x=PLAY_RECT.right-BALL_RADIUS
        ball_vel.x*=-0.35

    if ball_pos.y-BALL_RADIUS<PLAY_RECT.top:
        ball_pos.y=PLAY_RECT.top+BALL_RADIUS
        ball_vel.y*=-0.35
    elif ball_pos.y+BALL_RADIUS>PLAY_RECT.bottom:
        ball_pos.y=PLAY_RECT.bottom-BALL_RADIUS
        ball_vel.y*=-0.35

    resolve_wall_collision(old)

    if ball_height>0 or jump_velocity>0:
        jump_velocity -= settings['jump_gravity']*dt
        ball_height += jump_velocity*dt
        if ball_height<=0:
            ball_height=0
            jump_velocity=0

    if ball_height<12 and point_in_any_rect(ball_pos,rects_from(level()['water'])):
        reset_ball(3.0)
        return

    # Precise hole rule:
    # The whole ball must fit inside the visible hole, not merely touch it.
    # Geometrically that means:
    # distance(ball center, hole center) + ball radius <= hole radius.
    hole_capture_radius = max(1.0, hole_radius - BALL_RADIUS - 1.0)
    fully_inside_hole = ball_pos.distance_to(hole_point()) <= hole_capture_radius
    slow_enough = ball_vel.length() <= settings['hole_speed_limit']

    if ball_height==0 and fully_inside_hole and slow_enough:
        ball_sinking=True
        sink_progress=0.0
        ball_pos=hole_point()
        ball_vel.update(0,0)

class Button:
    def __init__(self,rect,text,action): self.rect=pygame.Rect(rect); self.text=text; self.action=action
    def draw(self):
        color=ACCENT2 if self.rect.collidepoint(pygame.mouse.get_pos()) else PANEL2
        pygame.draw.rect(screen,color,self.rect,border_radius=10); pygame.draw.rect(screen,(94,105,111),self.rect,1,border_radius=10)
        s=FONT.render(self.text,True,TEXT); screen.blit(s,s.get_rect(center=self.rect.center))
    def click(self,pos):
        if self.rect.collidepoint(pos): self.action(); return True
        return False

def centered(text,font,y,color=TEXT):
    s=font.render(text,True,color); screen.blit(s,s.get_rect(center=(WIDTH//2,y)))

def draw_menu():
    screen.fill(BG); centered('MOTION GOLF',TITLE,150); centered('STM32 Motion-Controlled Mini Golf',FONT,210,MUTED)
    bs=[Button((WIDTH//2-145,300,290,58),'Start Game',lambda:begin_level(0)),Button((WIDTH//2-145,378,290,58),'Level Select',lambda:set_state(LEVEL_SELECT)),Button((WIDTH//2-145,456,290,58),'Settings',lambda:set_state(SETTINGS)),Button((WIDTH//2-145,534,290,58),'Exit',lambda:sys.exit())]
    for b in bs:b.draw()
    return bs

def draw_level_select():
    screen.fill(BG); centered('SELECT LEVEL',BIG,90); bs=[]; y=155
    for i,lvl in enumerate(levels):
        b=Button((210,y,760,70),f"{i+1}. {lvl['name']}",lambda i=i:begin_level(i)); b.draw(); bs.append(b); y+=88
    back=Button((30,30,120,45),'Back',lambda:set_state(MENU)); back.draw(); bs.append(back); return bs

def draw_settings():
    screen.fill(BG); centered('SETTINGS',BIG,95); centered('Difficulty preset changes the game physics.',SMALL,140,MUTED)
    bs=[Button((210,215,220,58),'Easy',lambda:apply_difficulty('Easy')),Button((480,215,220,58),'Normal',lambda:apply_difficulty('Normal')),Button((750,215,220,58),'Hard',lambda:apply_difficulty('Hard'))]
    for b in bs:b.draw()
    lines=[
        f'Current difficulty: {difficulty_name}',
        f"Sensitivity: {settings['sensitivity']:.0f}",
        f"Maximum speed: {settings['max_speed']:.0f}",
        f"Grass drag: {settings['grass_drag']:.3f}",
        f"Sand movement: {settings['sand_accel_multiplier']*100:.1f}% input",
        f"Sand max speed: {settings['sand_max_speed']:.0f}",
        f"Jump power: {settings['jump_power']:.0f}",
        f"Hole entry speed: {settings['hole_speed_limit']:.0f}",
    ]
    for i,line in enumerate(lines): screen.blit(FONT.render(line,True,TEXT if i==0 else MUTED),(370,340+i*42))
    back=Button((30,30,120,45),'Back',lambda:set_state(MENU)); back.draw(); bs.append(back); return bs

def draw_game():
    screen.fill(BG); pygame.draw.rect(screen,PANEL,(0,0,WIDTH,64)); screen.blit(FONT.render('MOTION GOLF',True,TEXT),(24,19)); screen.blit(FONT.render(level()['name'],True,ACCENT),(410,19))
    pygame.draw.rect(screen,GRASS,PLAY_RECT,border_radius=18)
    for y in range(PLAY_RECT.top+18,PLAY_RECT.bottom-8,54): pygame.draw.line(screen,GRASS2,(PLAY_RECT.left+16,y),(PLAY_RECT.right-16,y),2)
    for r in rects_from(level()['sand']): pygame.draw.ellipse(screen,SAND,r)
    for r in rects_from(level()['water']):
        pygame.draw.ellipse(screen,WATER,r)
        for yy in range(r.top+20,r.bottom-10,28): pygame.draw.arc(screen,WATER_LIGHT,(r.left+12,yy,r.width-24,16),math.pi,math.tau,2)
    for r in rects_from(level()['walls']): pygame.draw.rect(screen,WALL_EDGE,r.inflate(5,5),border_radius=5); pygame.draw.rect(screen,WALL,r,border_radius=4)
    for r in rects_from(level()['low_walls']):
        pygame.draw.rect(screen,WALL_EDGE,r.inflate(5,5),border_radius=5); pygame.draw.rect(screen,LOW_WALL,r,border_radius=4)
        tag=TINY.render('JUMP',True,WHITE); screen.blit(tag,tag.get_rect(center=r.center))
    hp=hole_point(); pygame.draw.circle(screen,BLACK,hp,hole_radius); pygame.draw.line(screen,WHITE,(int(hp.x),int(hp.y)),(int(hp.x),int(hp.y-58)),3); pygame.draw.polygon(screen,RED,[(hp.x,hp.y-58),(hp.x+34,hp.y-47),(hp.x,hp.y-36)])
    if ball_sinking:
        draw_radius=max(1,int(BALL_RADIUS*(1.0-sink_progress)))
        if draw_radius>0:
            pygame.draw.circle(screen,WHITE,(int(ball_pos.x),int(ball_pos.y)),draw_radius)
    else:
        shadow=max(5,BALL_RADIUS-int(ball_height/22))
        pygame.draw.ellipse(screen,(50,70,55),(int(ball_pos.x-shadow),int(ball_pos.y+8-shadow/2),shadow*2,shadow))
        by=int(ball_pos.y-ball_height*0.20)
        pygame.draw.circle(screen,WHITE,(int(ball_pos.x),by),BALL_RADIUS)
        pygame.draw.circle(screen,(190,195,200),(int(ball_pos.x-4),by-4),2)

    grounded_in_sand = ball_height < 8 and point_in_any_rect(ball_pos, rects_from(level()['sand']))
    if grounded_in_sand and not ball_sinking:
        hint=FONT.render('SAND TRAP - JUMP TO ESCAPE',True,BLACK)
        hint_bg=hint.get_rect(center=(GAME_W//2,105))
        hint_bg.inflate_ip(26,12)
        pygame.draw.rect(screen,SAND,hint_bg,border_radius=9)
        screen.blit(hint,hint.get_rect(center=hint_bg.center))
    pygame.draw.rect(screen,PANEL,(HUD_X,64,WIDTH-HUD_X,HEIGHT-64)); screen.blit(FONT.render('CONTROLLER',True,TEXT),(HUD_X+28,95)); screen.blit(SMALL.render('Mode: Keyboard simulator',True,ACCENT),(HUD_X+28,130))
    vals=[f'Roll:  {roll:+.0f}',f'Pitch: {pitch:+.0f}',f'Speed: {ball_vel.length():.0f}',f"Jump:  {'AIR' if ball_height>0 else 'READY'}"]
    for i,line in enumerate(vals): screen.blit(FONT.render(line,True,TEXT),(HUD_X+28,180+i*38))
    box=pygame.Rect(HUD_X+36,355,235,105); pygame.draw.rect(screen,PANEL2,box,border_radius=12); c=pygame.Vector2(box.center); angle=roll*8; rad=math.radians(angle); dx=math.cos(rad)*72; dy=math.sin(rad)*72; pygame.draw.line(screen,ACCENT,(c.x-dx,c.y-dy),(c.x+dx,c.y+dy),4); dot=c+pygame.Vector2(roll*24,pitch*17); pygame.draw.circle(screen,WHITE,dot,8)
    t=current_elapsed()+water_penalty; screen.blit(FONT.render(f'Time: {t:05.1f}s',True,TEXT),(HUD_X+28,500)); screen.blit(SMALL.render(f'Water penalty: +{water_penalty:.0f}s',True,MUTED),(HUD_X+28,536)); screen.blit(SMALL.render(f'Difficulty: {difficulty_name}',True,MUTED),(HUD_X+28,565))
    bs=[Button((HUD_X+25,615,120,45),'Pause',toggle_pause),Button((HUD_X+160,615,120,45),'Restart',restart_level),Button((HUD_X+25,675,255,45),'Main Menu',lambda:set_state(MENU))]
    for b in bs:b.draw()
    screen.blit(TINY.render('WASD/Arrows: tilt   Space: jump   F1/F2: pause/restart',True,MUTED),(26,728))
    if state==PAUSED:
        ov=pygame.Surface((GAME_W,HEIGHT),pygame.SRCALPHA); ov.fill((0,0,0,125)); screen.blit(ov,(0,0)); s=BIG.render('PAUSED',True,WHITE); screen.blit(s,s.get_rect(center=(GAME_W//2,HEIGHT//2)))
    return bs

def draw_level_complete():
    draw_game(); ov=pygame.Surface((GAME_W,HEIGHT),pygame.SRCALPHA); ov.fill((0,0,0,155)); screen.blit(ov,(0,0)); s=BIG.render('LEVEL COMPLETE!',True,WHITE); screen.blit(s,s.get_rect(center=(GAME_W//2,265))); st='★'*stars_earned+'☆'*(3-stars_earned); s=BIG.render(st,True,YELLOW); screen.blit(s,s.get_rect(center=(GAME_W//2,330))); s=FONT.render(f'Final Time: {level_finish_time:.1f}s',True,WHITE); screen.blit(s,s.get_rect(center=(GAME_W//2,395)))
    bs=[Button((GAME_W//2-125,455,250,52),'Next Level',next_level),Button((GAME_W//2-125,523,250,52),'Retry',restart_level),Button((GAME_W//2-125,591,250,52),'Main Menu',lambda:set_state(MENU))]
    for b in bs:b.draw()
    return bs

def draw_game_complete():
    screen.fill(BG); centered('GAME COMPLETE',TITLE,185); centered('You finished all five courses.',FONT,255,MUTED); centered('Final course complete!',BIG,350,ACCENT)
    bs=[Button((WIDTH//2-145,470,290,58),'Play Again',lambda:begin_level(0)),Button((WIDTH//2-145,548,290,58),'Main Menu',lambda:set_state(MENU))]
    for b in bs:b.draw()
    return bs

def draw_current():
    if state==MENU:return draw_menu()
    if state==LEVEL_SELECT:return draw_level_select()
    if state==SETTINGS:return draw_settings()
    if state in (PLAYING,PAUSED):return draw_game()
    if state==LEVEL_COMPLETE:return draw_level_complete()
    if state==GAME_COMPLETE:return draw_game_complete()
    return []

buttons=[]; running=True
while running:
    dt=min(clock.tick(FPS)/1000.0,0.05)
    for event in pygame.event.get():
        if event.type==pygame.QUIT: running=False
        elif event.type==pygame.WINDOWFOCUSLOST: held_keys.clear()
        elif event.type==pygame.KEYDOWN:
            held_keys.add(event.key)
            if event.key==pygame.K_ESCAPE:
                if state in (PLAYING,PAUSED,LEVEL_COMPLETE): set_state(MENU)
                else: running=False
            elif event.key==pygame.K_SPACE and state==PLAYING and ball_height==0 and not ball_sinking:
                jump_velocity=settings['jump_power']
            elif event.key in (pygame.K_F1,pygame.K_p) and state in (PLAYING,PAUSED): toggle_pause()
            elif event.key in (pygame.K_F2,pygame.K_r) and state in (PLAYING,PAUSED,LEVEL_COMPLETE): restart_level()
        elif event.type==pygame.KEYUP: held_keys.discard(event.key)
        elif event.type==pygame.MOUSEBUTTONDOWN and event.button==1:
            for b in reversed(buttons):
                if b.click(event.pos): break
    if state in (PLAYING,PAUSED): update_input()
    else: roll=pitch=0.0
    update_physics(dt)
    buttons=draw_current(); pygame.display.flip()

pygame.quit()
