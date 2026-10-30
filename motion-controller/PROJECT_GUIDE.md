# STM32 体感控制器：项目结构与使用指南

本文面向第一次接触本工程的组员。项目功能是使用 STM32F103C8T6 读取
MPU6050 兼容六轴传感器，计算 Roll/Pitch 和跳跃事件，再通过 USB CDC
虚拟串口发送给电脑端游戏。

## 1. 项目当前状态

以下功能均已在实物上验证：

- ST-LINK 下载、校验和复位正常；
- Windows 能识别 USB 虚拟串口；
- MPU6050 兼容模块能通过 I2C 正常读取；
- 平放和倾斜时 Roll/Pitch 变化正确；
- 跳跃动作能够输出 `JUMP:1`，静止时无误触发；
- 数据更新频率为 50 Hz。

当前模块使用 I2C 地址 `0x68`，其 `WHO_AM_I` 返回 `0x74`。虽然不是标准
MPU6050 的 `0x68`，但所需寄存器和六轴数据已经实测兼容。

## 2. 目录结构

```text
motion_controller/
├─ Core/
│  ├─ Inc/                         STM32 应用层头文件
│  ├─ Src/
│  │  ├─ main.c                    传感器读取、姿态计算、跳跃检测、USB 输出
│  │  ├─ stm32f1xx_hal_msp.c       I2C1 的 PB8/PB9 重映射配置
│  │  ├─ usbd_cdc_interface.c      USB CDC 接口
│  │  └─ ...                       时钟、GPIO、中断等代码
│  └─ Startup/                     STM32F103 启动文件
├─ Drivers/                        CMSIS 和 STM32F1 HAL 驱动
├─ Middlewares/
│  └─ ST/STM32_USB_Device_Library/ USB Device 与 CDC 中间件
├─ Debug/                          CubeIDE 编译结果（可重新生成）
│  └─ motion_controller.elf        可直接烧录的已验证固件
├─ docs/                           早期调试图片和示意图
├─ motion_controller.ioc           STM32CubeMX 工程配置
├─ STM32F103C8TX_FLASH.ld          Flash 链接脚本
├─ .project / .cproject            STM32CubeIDE 工程文件
├─ README.md                       项目简介、接线和通信协议
└─ PROJECT_GUIDE.md                本使用指南
```

> 注意：`docs/mpu6050_breadboard_wiring.*` 是早期示意图，与最终实物插孔
> 不完全一致。接线必须以本文和 `README.md` 的表格为准。

## 3. 最终硬件接线

I2C1 使用重映射引脚 `PB8=SCL`、`PB9=SDA`。面包板两侧红蓝电源轨未使用，
所有线均直接连接。

| MPU6050 引脚 | STM32 引脚 | 实际面包板跳线 |
|---|---|---|
| VCC（A32） | 5V（G22） | E32 -> J22 |
| GND（A33） | GND（G23） | E33 -> J23 |
| SCL（A34） | PB8（G20） | E34 -> J20 |
| SDA（A35） | PB9（G21） | E35 -> J21 |
| AD0（A38） | GND（G23） | E38 -> I23 |

- `XDA`、`XCL`、`INT` 不连接；
- AD0 接地，因此设备地址为 `0x68`；
- `BOOT0` 保持为 0；
- 本项目实测所用模块必须由核心板 5V 引脚供电。

## 4. 最重要的供电规则

不要同时使用 ST-LINK 3.3 V 和 Type-C 给核心板供电。

### 烧录模式

1. 先拔掉核心板 Type-C；
2. 按原接线连接 ST-LINK（3.3V、GND、SWDIO、SWCLK）；
3. 将 ST-LINK 插入电脑；
4. 编译并下载固件；
5. 等待下载与校验完成。

### 正常运行模式

1. 拔掉 ST-LINK 的 USB；
2. 保持 MPU6050 接线不动；
3. 用 Type-C 数据线连接核心板和电脑；
4. Windows 将出现 USB Serial Device（COM 号由电脑动态分配）。

## 5. 在 STM32CubeIDE 中打开工程

### 使用 GitHub 中的完整工程包

1. 下载 `motion-controller/releases/motion_controller_project.zip`；
2. 解压到不含特殊符号的本地目录；
3. 打开 STM32CubeIDE；
4. 选择 `File > Open Projects from File System...`；
5. 选择包含 `.project` 和 `.cproject` 的解压目录；
6. 确认工程 `motion_controller` 后点击 `Finish`；
7. 点击锤子图标执行 Build。

也可以直接克隆仓库，然后导入仓库中的 `motion-controller` 目录。

### VS Code 扩展提示

如果 VS Code 提示 Microsoft C/C++ IntelliSense 与 `stm32-cube-clangd` 冲突，
选择“禁用 IntelliSense”，保留 `stm32-cube-clangd`。这只影响代码补全，
不会影响编译或固件。

### 不要直接重新生成代码

不要在 STM32CubeMX 中直接点击 `Generate Code`。当前 USB CDC、I2C 重映射和
传感器逻辑已经手工整合，未同步的重新生成可能覆盖这些修改。若确实需要重新
生成，必须先备份工程并检查 `USER CODE` 区域和 USB 文件差异。

## 6. 编译和烧录

### 从源码编译

1. 在 CubeIDE 的 Project Explorer 中选择 `motion_controller`；
2. 点击锤子图标，确认控制台出现 `Finished building target`；
3. 进入烧录模式；
4. 点击绿色 Run 按钮下载；
5. 等待 Download verified successfully 或等价成功提示。

权威构建输出为：

```text
Debug/motion_controller.elf
```

### 直接烧录已验证固件

不修改代码时，可直接使用 GitHub 中的：

```text
motion-controller/releases/motion_controller.elf
```

在 STM32CubeProgrammer 中选择 SWD，连接芯片后选择该 ELF，执行 Download，
并勾选或执行下载后的复位。

## 7. USB 串口数据协议

核心板通过 USB CDC 每 20 ms 发送一行，即约 50 Hz。数据示例：

```text
ROLL:-12.3,PITCH:4.5,JUMP:0
```

字段定义：

| 字段 | 含义 | 单位/范围 |
|---|---|---|
| `ROLL` | 横滚角 | 度，带一位小数 |
| `PITCH` | 俯仰角 | 度，带一位小数 |
| `JUMP` | 跳跃状态 | `0` 或 `1` |

- 行尾是 `\r\n`；
- 串口工具可以设置为 115200、8N1；USB CDC 实际传输不依赖 UART 波特率；
- 启动或重连时可能先收到状态行，游戏端应忽略不含三个控制字段的行；
- COM 号不是固定的，不要在游戏程序里写死 `COM7`。

## 8. 游戏端如何解析

推荐处理流程：

1. 让用户从可用串口列表中选择设备；
2. 按行读取串口；
3. 只处理同时包含 `ROLL:`、`PITCH:`、`JUMP:` 的行；
4. 以逗号分成三个字段，再以冒号分出名称和值；
5. 将 Roll/Pitch 映射为角色或小球的移动方向；
6. 将 `JUMP` 的 `0 -> 1` 上升沿作为一次跳跃。

跳跃状态会保持约 300 ms，因此一跳会收到多行 `JUMP:1`。游戏端不要对每一行
都重复执行跳跃，应只响应上升沿，或在触发后设置一次性锁定，等 `JUMP` 回到 0
再允许下一跳。

伪代码：

```text
previousJump = 0

for each serialLine:
    if line does not contain ROLL, PITCH and JUMP:
        continue

    roll, pitch, jump = parse(line)
    horizontalInput = applyDeadZone(roll, 3 to 5 degrees)
    verticalInput   = applyDeadZone(pitch, 3 to 5 degrees)

    if jump == 1 and previousJump == 0:
        triggerJumpOnce()

    previousJump = jump
```

如果游戏中的运动方向与预期相反，直接在游戏端使用 `-roll` 或 `-pitch` 即可，
无需重新烧录控制器。

## 9. 快速验收方法

1. Type-C 连接后，在设备管理器中找到新的 COM 口；
2. 用串口终端打开该 COM 口；
3. 平放时 Roll/Pitch 应接近 0，允许几度安装误差；
4. 抬起面包板一侧，Roll 或 Pitch 应随倾角稳定变化；
5. 双手拿稳控制器并快速向上抬动后停住，应短暂出现 `JUMP:1`；
6. 放回桌面静止时，`JUMP` 应保持为 0。

## 10. 常见问题

### Windows 没有出现 COM 口

- 确认使用的是支持数据传输的 Type-C 线，不是纯充电线；
- 尝试更换 USB 口；
- 确认已切换到正常运行模式，而不是只连接 ST-LINK；
- 查看设备管理器中是否有未知 USB 设备。

### ST-LINK 提示 `No debug probe detected`

- 确认 ST-LINK 的 USB 已插入电脑；
- 检查 SWDIO、SWCLK、GND 和 3.3V；
- 烧录前拔掉 Type-C；
- 必要时重新插拔 ST-LINK 后再次连接。

### 出现 `MPU6050_ERROR`

- 检查 VCC 是否接核心板 5V；
- 检查 GND 是否共地；
- 检查 SCL 是否接 PB8、SDA 是否接 PB9；
- 检查 AD0 是否接地；
- 确认没有使用早期错误接线图。

### 串口被占用

同一 COM 口通常不能被串口终端和游戏程序同时打开。先关闭串口终端，再启动
游戏程序；如果程序异常退出，重新插拔 Type-C 后再试。

### 角度有少量零偏

平放时出现约 1 到 3 度的偏差属于正常安装误差。游戏端建议设置 3 到 5 度
死区，避免角色在静止时缓慢移动。

## 11. 组员交接清单

交付或提交项目时至少保留：

- `Core/`；
- `Drivers/`；
- `Middlewares/`；
- `.project`、`.cproject`、`.mxproject`、`.settings/`；
- `motion_controller.ioc`；
- `STM32F103C8TX_FLASH.ld`；
- `README.md` 和 `PROJECT_GUIDE.md`；
- 可选：已验证的 `motion_controller.elf`。

不要提交 `tmp/`、浏览器缓存或大量可重新生成的 Debug 中间文件。


