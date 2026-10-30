# STM32 Motion Controller

基于 STM32F103C8T6、MPU6050 兼容模块和 USB CDC 的体感游戏控制器。
固件以 50 Hz 读取六轴传感器，计算 Roll、Pitch，并检测跳跃动作后通过
Windows 虚拟串口发送给游戏程序。

## 已验证状态

- ST-LINK 下载、校验和复位正常。
- Windows 可识别为 `USB Serial Device (COM7)`（COM 号可能随电脑变化）。
- I2C1 使用重映射引脚：`PB8=SCL`、`PB9=SDA`。
- 传感器在地址 `0x68` 应答；本模块 `WHO_AM_I=0x74`，已验证兼容所用寄存器。
- 平放、约 35 度倾斜、跳跃动作和静止防误触均已实测通过。

## 当前实物接线

面包板两侧红蓝电源轨未使用，所有线均直接连接：

| MPU6050 | STM32 | 实际面包板跳线 |
|---|---|---|
| VCC（A32） | 5V（G22） | E32 -> J22 |
| GND（A33） | GND（G23） | E33 -> J23 |
| SCL（A34） | PB8（G20） | E34 -> J20 |
| SDA（A35） | PB9（G21） | E35 -> J21 |
| AD0（A38） | GND（G23） | E38 -> I23 |

`XDA`、`XCL`、`INT` 不连接。AD0 接地使 I2C 地址为 `0x68`。

## USB 串口协议

波特率可设为 `115200`（USB CDC 实际传输不依赖 UART 波特率）。每行一个数据包：

```text
ROLL:-12.3,PITCH:4.5,JUMP:0
```

- `ROLL`：横滚角，单位为度。
- `PITCH`：俯仰角，单位为度。
- `JUMP`：平时为 `0`；检测到跳跃动作后约 300 ms 内为 `1`。
- 更新频率：50 Hz。

游戏端应按换行符读取，再按逗号和冒号解析三个字段。不要写死 `COM7`，应允许
用户选择 Windows 当前分配的 COM 口。

## 供电与烧录

不要同时用 ST-LINK 3.3 V 和 Type-C 给核心板供电。

- 烧录：先拔 Type-C，再按原接线接通 ST-LINK，烧录
  `Debug/motion_controller.elf`。
- 运行：拔掉 ST-LINK USB，再接 Type-C；MPU6050 由核心板 5V 引脚供电。
- `BOOT0` 保持为 0。

不要在 STM32CubeMX 中直接执行 `Generate Code`，除非已经备份当前 USB CDC 和
I2C 修改；未同步的重新生成可能覆盖现有代码。


