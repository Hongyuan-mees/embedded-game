# 同步第二个游戏 Motion Rush

用户要求检查队友上传的第二个游戏，并拉取到本地。

- 已 fetch 并确认新内容位于 `origin/game-stage2`，最新提交 `5903be9`，功能提交 `58fd7d1`。
- 当前 `member4/pc-controller` 从 `d45b03a` 快进到 `5903be9`；本地 `game-stage2` 也同步到该提交。无合并冲突，无须覆盖本地修改。
- 新游戏为三赛道跑酷 Motion Rush，源码 `MotionGolf_Stage2_v3/runner.py`。原 `main.py` 新增游戏选择页，可选择 Motion Golf 或 Motion Rush。
- 根据实际主循环，STM32 已连接且校准就绪时调用 `set_motion_state(stm32_controller.roll, jump_event=stm32_controller.jump)`；现有向上事件接到跳跃，下滑仍由键盘 S / Down 控制。跑酷中键盘换道和跳跃也始终可用。
- 发现实际接口不匹配：共享控制器 roll 为 [-1, 1]，但 runner.py 的 `set_motion_state` 用 ±10.0 换道、±6.0 回中，相当于按角度解释。以 -1/+1 调用均保持中道，已通过实际调用复现，因此当前 STM32 倾斜换道不能正常工作。本次仅记录，未擅自修改。
- 入口仍为 `.venv/Scripts/python.exe MotionGolf_Stage2_v3/main.py`，没有新增依赖。
- 已执行现有 Stage 2 集成测试，10 项通过。新增临时检查最初以归一化 -1 输入断言左道失败，定位到上述单位不匹配；随后在 SDL dummy 下实际实例化 RunnerGame，用 ±15 角度输入检查左右换道，并检查菜单绘制、起跳、下滑、更新、游戏绘制和暂停/恢复，均通过。基础跑酷可运行不代表 STM32 换道适配通过。
- 本轮仅同步与基础验证，未修改队友源码，未改固件，未执行跑酷实物试玩，也未推送远端。已打开的旧游戏进程需要退出并重新启动才能加载本次更新。
