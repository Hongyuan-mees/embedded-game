# Motion Golf - Stage 2

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

运行（建议从完整仓库根目录运行）：

```powershell
.\.venv\Scripts\python.exe -m pip install -r MotionGolf_Stage2_v3/requirements.txt
.\.venv\Scripts\python.exe MotionGolf_Stage2_v3/main.py
```

控制：
- 默认STM32主控；连接设备后F4保持自然握持校准，点击Start Game进入游戏。
- F3：STM32 / Keyboard备用模式切换。
- F4：中立姿态校准；F5或主菜单Controller：端口、连接、力度和试跳设置。
- STM32：倾斜控制滚动，向上动作触发Jump，需要v2六轴固件。
- Keyboard模式：WASD / 方向键模拟倾斜，Space触发Jump。
- P / F1：Pause / Resume
- R / F2：Restart
- Esc：返回菜单 / 退出

## STM32兼容层

`controller.py`保留Stage 2的`STM32SerialController`名称，复用仓库内
`MotionGolf_Stage1_v4/controller`的分帧、超时、校准、归一化和向上手势检测。
两版游戏共用`MotionGolf_Stage1_v4/user_settings.json`中的玩家力度与端口偏好，
避免搬动已验证模块或维护两套串口算法；请保留完整仓库目录。

从本目录执行`python main.py`，或从根目录执行
`python -m MotionGolf_Stage2_v3.main`也支持。

接口输出Roll/Pitch为[-1,1]归一化输入，实物方向沿用Roll同号、Pitch反转；
Jump为一次事件。固件旧JUMP电平不直接控制小球。v1数据可用于倾斜，硬件上提
需要[v2固件](../motion-controller/releases/README_v2.md)。

串口在菜单、暂停和通关页也持续读取，未完成手势不会积压到下一关。
输入失效时自动暂停并打开控制器设置；同一端口数据恢复后，必要时Connect / Retry、
F4重新校准，再点击Start / Resume。Close / F5始终可关闭设置，输入尚不可用时
游戏保持暂停，可切Keyboard继续。切出窗口会暂停，回到窗口后手动Resume。

控制器设置是独立覆盖面板；原Settings菜单仍用于Easy / Normal / Hard物理难度。
打开控制器面板时游戏计时暂停。菜单中该面板的Start按钮可直接开始当前关卡，
Close返回菜单；游戏中Start / Resume继续游戏。

当前跳跃沿用玩家选择的“易触发优先”：取消横向及翻腕否决，明显下压仅短暂抑制，
有效跳跃后固定冷却。允许少量误跳，具体规则见[共享控制说明](../MotionGolf_Stage1_v4/README.md)。
球仍需落地且未在入洞动画中才能再次起跳；没有改动队友的沙坑、低墙、难度或星级规则。

## 验证与已知限制

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s MotionGolf_Stage2_v3/tests -v
.\.venv\Scripts\python.exe -m unittest discover -s MotionGolf_Stage1_v4/tests -v
```

测试运行真实Stage 2主循环，使用模拟串口；覆盖菜单手势隔离、第五关沙坑起跳、
入洞动画与通关、断流/校准/恢复、设置计时及键盘备用，不等于完整实物通关验收。
已知硬件I²C间歇故障仍可能导致`MPU6050_ERROR`；本次仅适配PC游戏，
没有改写STM32固件或加入固件自动GPIO总线恢复。

需要记录实际游戏中的手势和场景状态时，退出其他游戏/串口监听后，从根目录运行：

```powershell
.\.venv\Scripts\python.exe "AI Notes/diagnostics/launch_gesture_diagnostic.py" --stage2
```


## Stage 2 v3
- Precise full-ball hole entry
- Hole sinking animation
- Strong sand trap requiring jump escape
- Difficulty-specific sand behavior
