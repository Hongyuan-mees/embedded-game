# SerialController 实现与验证

日期：2026-11-06。分支：`member4/pc-controller`。

## 授权与 Git 节点

用户同意实施独立控制器、测试、依赖更新及开发记录，并授权在实施前提交准备阶段。

- 准备阶段已提交：`61ea139`，`chore: save member4 setup and hardware reference documents`。
- 该提交包含 `.gitignore`、`AGENT.md`、两份已重命名的传感器 PDF 和前期核对笔记。
- 本轮控制器实现已获用户授权保存为本地Git提交，提交号以Git日志为准；包括用户本次更新的本地提交及文件修改规则。未推送、合并。
- `main.py`、固件、物理参数、地图与 UI 均未修改。

## 已确认的握持约定

- 双手端平，标记前端并朝向屏幕；压低哪侧，小球向哪侧加速。
- 前端压低对应屏幕上方，后端压低对应屏幕下方。
- 回到中立位置停止施加控制加速度，小球继续受现有惯性、阻力影响；反向倾斜用于制动。
- 短促上抬后停住约定为跳跃动作；固件实际按加速度模长识别，不能保证只响应此动作。
- 默认死区4度、满量程25度，可通过配置调整。最终轴向与正负号需实物确认。

## 文件与职责

- `MotionGolf_Stage1_v4/controller/__init__.py`：公开接口。
- `MotionGolf_Stage1_v4/controller/serial_controller.py`：独立串口控制器及协议解析。
- `MotionGolf_Stage1_v4/tests/test_serial_controller.py`：无硬件单元测试、pyserial 软件回环。
- `MotionGolf_Stage1_v4/requirements.txt`：新增 `pyserial>=3.5`。
- 当前项目 `.venv` 已安装 pyserial 3.5；pygame-ce 保持2.5.8。

## 接口用法

从游戏目录导入 `controller`，或在仓库根目录导入 `MotionGolf_Stage1_v4.controller`。

```python
from MotionGolf_Stage1_v4.controller import ControllerConfig, SerialController

controller = SerialController(ControllerConfig(
    dead_zone_deg=4.0,
    full_scale_deg=25.0,
    swap_axes=False,
    invert_roll=False,
    invert_pitch=False,
))

ports = controller.available_ports()  # (device, description) 列表
# 从 ports 选择实际端口，再调用 controller.connect(selected_port)。
# 每帧调用 controller.update()，随后读取 roll、pitch、jump。
# 有效数据到达后可以请求 controller.calibrate()，继续每帧 update。
# 退出、切换设备时调用 controller.close()。
```

主要约定：

- 导入和构造均不打开串口；`connect(port)`、`calibrate()` 返回是否成功。
- `is_open` 表示系统串口已打开；`connected` 表示最近的 update 已确认有效控制数据未超时。
- `roll/pitch` 为每轴归一化控制量；`raw_roll/raw_pitch` 为原始角度，失效时为None。
- swap先于invert；invert对应交换后的输出轴。默认正Roll向右、正Pitch向下，物理对应方向尚未验证。
- 每帧调用一次 `update()`；它会先清除上一帧Jump。解析同一批数据时保留最新角度，锁存任一新Jump到本帧结束。
- 首包或恢复后的 `JUMP:1` 不触发；必须先观察到合法的 `JUMP:0`，才对其后的0到1产生事件。
- 初始零点为0度；调用 `calibrate()` 后收集连续25个Jump为0的稳定样本，约对应正常50 Hz下0.5秒。两轴窗口跨度均不超过2度才完成，摇动会清空样本重新等待。采集期间方向和Jump均保持中性。
- Roll校准与差值使用环绕角处理，避免正负180度边界出错。
- 默认有效数据超时250 ms；状态行、非法值不会续期。超时清除旧方向、Jump和片段，并丢弃驱动积压数据，下次update可继续接收。
- `MPU6050_ERROR` 立即使输入失效；普通启动、恢复提示行不当作控制输入。
- 断连/OSError会释放串口并清空输入。没有自动重连，下一轮UI可按用户选择调用connect。
- 重新连接会清除校准；同一连接的数据超时会取消正在进行的校准，但保留已经成功的零点。
- 每次update最多读取4096字节；行长度最多256字节。过长行丢弃至换行，超出读取预算的积压直接丢弃并归零。
- 固件没有采样时间戳；PC无法证明每个缓冲包的实际采样时间，预算与超时处理用于限制旧输入影响。

## 已执行验证

在仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s MotionGolf_Stage1_v4/tests -v
```

最终结果：33项测试通过。覆盖正常字段与原始度数、字段顺序、状态行、坏包、非有限数、越界值、所有单一切分位置、连续包、Jump去重与帧间清除、映射/反向/轴交换、稳定校准/抖动/环绕、超时/初始无数据/片段过期、传感器错误、端口占用、断连异常与重连。

软件回环使用pyserial的 `loop://`。回环测试的模拟发送端单独设置1秒写超时以满足回环的线速模拟；控制器接收始终保持 `timeout=0`。这不是实际USB或COM口测试。

## 下一步

本轮已达到独立控制器验收目标，用户要求先提交，再说明下一步具体工作。33项测试已复核通过。

下一轮拟定范围（方案，尚未实施）：

1. 在主循环的输入更新位置接入模式选择，每帧先更新串口，再将选定输入交给现有物理。
2. 用户已明确STM32为主要控制方式，启动默认STM32模式；键盘仅作辅助、调试和备用，保留原有按键。拟用F3切换模式、F4校准，实际操作设计在实施前确认。
3. 键盘空格和硬件Jump共用起跳入口，统一检查暂停、通关及落地状态。
4. 暂停、失焦、重开、切关和模式切换时丢弃旧Jump，防止恢复后补跳；串口持续接收以维护边沿状态。
5. 在HUD中显示模式、连接/数据状态和校准状态；提供明确的实际COM口选择方式，不写死COM7。
6. 先用模拟输入验证小球运动及跳跃，并回归原键盘玩法。实物到手后验证最终握持轴向、校准效果、死区与满量程、Jump误触及真实USB拔插。

需修改main.py，并按实际方案补充输入模块、针对性集成测试和游戏README。保持固件、关卡与物理参数不变；实施前向用户确认具体文件范围。

## 用户补充：STM32优先

用户明确键盘是辅助，主要使用STM32控制。该决定取代先前提出的默认键盘模式方案，业务代码尚未实施切换。

后续流程建议围绕“启动STM32模式、选择/连接控制器、稳定校准、进入游戏”设计。未连接或未完成校准时不给游戏施加硬件输入；键盘移动及空格只在用户主动切入键盘模式后生效，菜单和暂停等通用操作仍可使用键盘/鼠标。没有设备时提供明确的键盘备用入口，不静默改变模式。软件模拟仅作为明确标识的开发验收手段。

断连后至少使输入归零并提示；是否自动暂停游戏作为下一轮实施前的具体交互建议，不视为用户已确认的规则。
