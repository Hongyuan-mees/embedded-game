# Motion Arcade - Stage 2

The application now starts at a game-selection screen:

- `Motion Golf`: the existing five-course tilt golf game.
- `Motion Rush`: a three-lane obstacle runner inspired by endless runner games.

## Motion Rush

Motion Rush currently runs with keyboard simulation:

- `A / D` or `Left / Right`: switch between three lanes.
- `W`, `Up`, or `Space`: jump over low barriers.
- `S` or `Down`: slide under overhead gates.
- `P / F1`: pause or resume.
- `R / F2`: restart.
- `Esc`: leave the run or return to the game-selection screen.

The runner exposes `set_motion_state()` for future STM32 input integration. Roll is
already mapped to the three lanes, and the method accepts jump and slide events.
The firmware still needs to distinguish upward and downward motion gestures before
those events can be connected to the live controller.

新增：
- 正式主菜单
- Start Game / Level Select / Settings
- Easy / Normal / Hard 三档难度
- 5 个关卡
- 墙、低墙、沙坑、水池、球洞
- Jump 越过低墙
- 通关星级评分
- Next Level / Retry / Main Menu
- Game Complete 界面
- 正式 HUD 和简单倾斜动画
- 保留 Stage 1 v4 已验证稳定的键盘控制

运行：

```powershell
python main.py
```

控制：
- WASD / 方向键：模拟倾斜
- Space：Jump
- P / F1：Pause / Resume
- R / F2：Restart
- Esc：返回菜单 / 退出


## Stage 2 v3
- Precise full-ball hole entry
- Hole sinking animation
- Strong sand trap requiring jump escape
- Difficulty-specific sand behavior
