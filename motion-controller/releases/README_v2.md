# v2：六轴采样上报固件

`motion_controller_v2.elf` 和 `motion_controller_v2.hex` 为当前Core源码构建的v2产物。原有 `motion_controller.elf` 和 `motion_controller_project.zip` 保留，可用于回退及获取HAL/USB依赖。

本次只扩展数据上报与USB发送缓冲保护，不更改I2C接线、传感器量程或原始姿态算法。旧JUMP检测保留为兼容诊断字段；新版游戏根据六轴数据独立判断向上提拉，不再使用这个旧字段触发跳跃。

## 协议

正常目标约50Hz，ASCII，每条以CRLF结束：

```text
ROLL:0.4,PITCH:-1.6,JUMP:0,V:2,T:12340,AX:0,AY:0,AZ:16384,GX:0,GY:0,GZ:0
```

- `V:2`：协议版本；示例数值仅用于说明格式。
- `T`：本轮读取前取得的HAL_GetTick毫秒时间戳，uint32，允许正常回绕。
- `AX/AY/AZ`：有符号16位原始加速度，正负2g，16384 LSB/g，包含重力。
- `GX/GY/GZ`：有符号16位原始角速度，正负250度/秒，131 LSB/(度/秒)。
- `ROLL/PITCH`仍为带一位小数的角度，`JUMP`仍为旧算法的300ms脉冲。

整行会跨越USB的64字节包，接收端必须按换行拼接，不能将一次read当成一条完整记录。CDC发送端使用160字节私有缓冲，在发送期间保护数据不被主循环覆盖。

新版PC解析器接受完整v2或原v1三字段协议，不接受缺失部分六轴字段的半套v2。原来的严格三字段解析器不能直接使用扩展行，需要同步更新PC代码。

## 从源码构建

使用Python和GNU Tools for STM32，不需要重新生成CubeMX工程：

```powershell
python motion-controller/build_v2.py --toolchain "你的工具链路径/bin/arm-none-eabi-gcc.exe"
```

脚本将原ZIP依赖解压到仓库的 `tmp/firmware-v2/`，覆盖为当前Core和链接脚本后编译，生成新的v2 ELF/HEX。原ZIP与旧ELF不变。本次工具链为GNU Tools for STM32 13.3.rel1；编译有原工程的未使用函数/参数警告。

## 烧录与验收

1. 退出游戏和串口监听，拔掉核心板Type-C，按原接线接入ST-LINK。
2. 使用STM32CubeProgrammer以SWD连接，下载 `motion_controller_v2.elf` 并校验、复位。HEX同样带地址；不要把ELF当成裸二进制指定偏移。
3. 拔掉ST-LINK的USB，恢复Type-C正常运行。沿用PROJECT_GUIDE的供电规则。
4. 串口应出现包含 `V:2,T:...,AX:...,GX:...` 的扩展行；游戏设置面板应显示Upward lift detection available。
5. 重新校准，在面板试跳。分别验证上提、下压及刹停、横向甩动、普通倾斜，并调整舒适阈值。

产物已构建不等于板上已更新。游戏应在识别到V2后才启用方向手势；实际手感和误触率仍需真实六轴数据验收。
