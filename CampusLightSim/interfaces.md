# CampusLightSim V1 模块接口与数据结构规范

> 项目：北邮本部主楼智能照明 LoRa 云运维仿真平台  
> 版本：V1.0  
> 维护负责人：梁

## 1. 总体数据流

```text
environment.py
    ↓ lux / occupancy
lighting.py
    ↓ brightness
device.py
    ↓ power / status
lora.py
    ↓ RSSI / SNR / delay / packet_success
gateway.py
    ↓
database/db.py
    ├── analysis/energy.py
    ├── tests/test_system.py
    └── Streamlit pages

device + LoRa + gateway status
    ↓
fault.py
    ↓
alarms / operation_logs
```

`engine.py` 统一调度：更新时间 → 环境光照 → 人员状态 → 自动照明 → 灯具亮度 → 功率 → LoRa → RSSI/SNR/丢包 → 网关 → 数据库 → 告警。

每个节点 5 分钟一个时间点、24 小时 288 点；一期 3 个节点为 864 条，
全校 10 个代表节点为 2880 条。二、三期代表节点均为“仿真估算”。

## 2. 统一 ID

| zone_id | 名称 | 场景 | 控制模式 |
|---|---|---|---|
| Z01 | 主楼典型教室 | indoor_classroom | LIGHT_OCCUPANCY |
| Z02 | 主楼一层公共走廊 | indoor_corridor | OCCUPANCY |
| Z03 | 主楼附近道路 | outdoor_road | TIME_LIGHT_OCCUPANCY |
| Z04 | 教学楼群典型教室 | indoor_classroom | LIGHT_OCCUPANCY |
| Z05 | 图书馆典型阅览区 | indoor_library | LIGHT_OCCUPANCY |
| Z06 | 体育场馆典型场地 | outdoor_sports | TIME_LIGHT_OCCUPANCY |
| Z07 | 学生公寓典型公共走廊 | indoor_dormitory_corridor | OCCUPANCY |
| Z08 | 科研楼典型公共区 | indoor_research_common | LIGHT_OCCUPANCY |
| Z09 | 校园主干道与校门 | outdoor_road | TIME_LIGHT_OCCUPANCY |
| Z10 | 校医院及家属区公共道路 | outdoor_public_service | TIME_LIGHT_OCCUPANCY |

| device_id | zone_id | 功率 | 网关距离 | SF | 通信 |
|---|---|---:|---:|---:|---|
| CL-N01 | Z01 | 80W | 60m | 7 | LoRaWAN |
| CL-N02 | Z02 | 50W | 120m | 9 | LoRaWAN |
| CL-N03 | Z03 | 120W | 350m | 12 | LoRaWAN + NB-IoT补充 |
| CL-N04 | Z04 | 72W | 260m | 10 | LoRaWAN |
| CL-N05 | Z05 | 96W | 220m | 9 | LoRaWAN |
| CL-N06 | Z06 | 400W | 360m | 11 | LoRaWAN |
| CL-N07 | Z07 | 48W | 480m | 12 | LoRaWAN |
| CL-N08 | Z08 | 72W | 320m | 10 | LoRaWAN |
| CL-N09 | Z09 | 120W | 520m | 12 | LoRaWAN + NB-IoT补充 |
| CL-N10 | Z10 | 80W | 450m | 12 | LoRaWAN |

`GW-01 / GW-02 / GW-03` 为三个 LoRa 网关。上表固定距离仅保留为旧单网关
实验参考值，新通信链路不使用该字段，改由节点与各网关三维坐标计算。

### 三网关版本（2026-09-10）

保持现有 PA01–PA08 八个片区、Z01–Z10 十个代表区域及其归属不变。
校园仿真坐标范围 500 × 750 m，西北角为 (0, 0)，x 向东、y 向南。
原校园底图保留；新坐标示意不表示已完成底图地理配准。

| 网关 | 位置 | (x, y, height)，单位 m |
|---|---|---|
| GW-01 | 图书馆楼顶 | (250, 220, 25) |
| GW-02 | 教三楼附近高点/楼顶 | (145, 520, 22) |
| GW-03 | 可靠网络通信协同创新中心楼顶 | (355, 520, 25) |

`AREA_GATEWAY_PLAN` 保存用户指定的片区主备规划，不作为选路白名单。
`DEVICE_POSITIONS` 是新增代表节点位置估算，不改变既有片区规划。
PA07 可用同一代表节点的不同坐标测试北门、西门、东门链路，无需新增区域。

```python
from simulator.gateway import select_gateway
from simulator.device import VirtualLightingNode

node = VirtualLightingNode.from_config("CL-N05")
link = select_gateway(node.to_dict(), gateways, timestamp=now)
node.update_link(link)
# link['gateway_links'] 含每个网关的距离、RSSI、SNR、丢包概率和收包结果。
# link['gateway_id'] 是当前最优可达在线网关，无可达网关时为 None。
# 数据库 save_device(node) 保存 gateway_id 和当前选中链路 distance。
```

每条链路使用三维距离、对数路径损耗、节点建筑遮挡及确定性随机阴影模型。
低于当前 SF 接收灵敏度的链路不可达，不使用固定覆盖半径。
同节点/网关/时刻/种子产生相同随机结果，离线其他网关不改变剩余链路。
LoRaWAN 上行可被多个网关同时接收；本项目以 RSSI 最大的可达在线链路作为
页面和数据库中的“最佳接收网关”摘要，不表示终端预先绑定或执行蜂窝式切换。
该摘要选择不参考本次收包结果，不能通过挑选成功包虚增 PDR。
链路同时返回 `sensitivity_dbm / link_margin_db / radio_reachable / airtime_ms`；
空中时间按 125 kHz、4/5 编码率和 20-byte 二进制遥测负载估算，`delay_ms`
在此基础上增加简化的网络处理时间，不代表完整 LoRaWAN 往返时延。
SNR 由 RSSI 与模拟噪声底计算，页面值限制在 SX127x PacketSnr 可报告范围；
`raw_snr` 保留未限制的模型计算值供测试和分析。
这是简化软件模型，没有模拟 LoRaWAN MAC、碰撞和真实建筑三维传播。

故障流程使用 `FaultManager.sample_network(device, telemetry, timestamp=now,
gateways=gateways, auto_control_ok=...)`。此处 telemetry 是环境及灯具本周期
数据，正常 LoRa 计算由该入口委托给 gateway/lora；不要提前叠加信号损耗。
网关离线影响该网关链路，终端自动切换；全不可达时连续三个无效周期产生
节点离线告警。网关恢复须经该网关重新成功上传并满足恢复条件，备用网关
成功不能关闭其他网关告警。旧 `sample` / `check_fault` 单链路入口保留，
新增关键字 `gateway_id` 指定检测对象，其缺省 GW-01 仅用于兼容旧调用。

数据库 `init_db` 增量增加设备的 `gateway_id / height` 字段，补齐缺失坐标，
首次迁移清除失效的旧中心网关距离，保留其他设备运行状态及告警、维修记录。
新设备未选路时 `gateway_id / distance` 为 NULL。

> 一期参数为仿真设计值；Z04~Z10 的距离、功率、SF、光照系数和人员时段为
> 基于校园地图与场景类型的“仿真估算”，均不是北邮现场实测数据。

## 3. 核心数据结构

### EnvironmentData

```python
{
    "timestamp": datetime,
    "zone_id": str,
    "lux": float,
    "occupancy": bool
}
```

### Telemetry

全系统统一使用：

```python
{
    "timestamp": datetime,
    "device_id": str,
    "zone_id": str,
    "lux": float,
    "occupancy": bool,
    "brightness": float,
    "power": float,
    "rssi": float,
    "snr": float,
    "delay_ms": float,
    "packet_success": bool
}
```

### Alarm

```python
{
    "alarm_id": str,
    "timestamp": datetime,
    "device_id": str,
    "alarm_type": str,
    "severity": str,
    "message": str,
    "status": str
}
```

`severity`: `INFO / WARNING / CRITICAL`

建议 `alarm_type`：
`node_offline / low_rssi / very_low_rssi / low_pdr / sensor_abnormal / gateway_offline`

`status`: `OPEN / ACKNOWLEDGED / CLOSED`

### OperationLog

```python
{
    "timestamp": datetime,
    "device_id": str,
    "operation": str,
    "result": str
}
```

## 4. environment.py

负责人：方。

```python
def get_environment(zone_id: str, timestamp: datetime) -> dict:
    ...
```

返回：

```python
{
    "timestamp": timestamp,
    "zone_id": zone_id,
    "lux": 320.0,
    "occupancy": True
}
```

可提供：

```python
def get_lux(zone_id: str, timestamp: datetime) -> float:
    ...

def get_occupancy(zone_id: str, timestamp: datetime) -> bool:
    ...
```

环境模块只负责光照和人员模拟，不负责灯光控制、LoRa、数据库和页面。

## 5. lighting.py

负责人：吴。

```python
def auto_control(
    zone_id: str,
    lux: float,
    occupancy: bool,
    timestamp: datetime | None = None
) -> float:
    ...
```

规则按 `ZONES[zone_id]["control_mode"]` 复用，具体阈值来自 `LIGHTING_RULES`：

```text
LIGHT_OCCUPANCY（Z01/Z04/Z05/Z08）：
lux > lux_off_threshold → unoccupied_brightness
lux < lux_on_threshold + 有人 → occupied_brightness
lux < lux_on_threshold + 无人 → unoccupied_brightness
两个阈值之间 → 保持上一状态（滞回）

OCCUPANCY（Z02/Z07）：
有人 → 100%
无人 → 配置的基础亮度

TIME_LIGHT_OCCUPANCY（Z03/Z06/Z09/Z10）：
白天 → 0%
夜间 + 有人 → 100%
夜间 + 无人 → 配置的基础亮度
```

只负责计算 `brightness`，不负责数据库、LoRa、页面。

## 6. device.py

负责人：吴。

```python
class VirtualLamp:
    def __init__(
        self,
        device_id: str,
        zone_id: str,
        rated_power: float
    ):
        ...
```

必须保存：

```text
device_id / zone_id / rated_power / status / mode / brightness / power
```

接口：

```python
def set_brightness(self, brightness: float) -> None:
    ...

def calculate_power(self) -> float:
    ...
```

功率：

```text
power = rated_power × brightness / 100
```

模式：

```text
AUTO / MANUAL
```

## 7. lora.py

负责人：吴。

```python
def simulate_lora(
    distance_m: float,
    sf: int,
    obstacle: str,
    tx_power_dbm: float = 14.0
) -> dict:
    ...
```

返回：

```python
{
    "rssi": -94.3,
    "snr": 5.2,
    "delay_ms": 220.0,
    "packet_success": True
}
```

输入因素：距离、SF、障碍环境、发射功率。

输出：RSSI、SNR、时延、是否成功。

## 8. gateway.py

负责人：吴。

```python
class LoRaGateway:
    def __init__(self, gateway_id: str):
        ...

    def receive(self, telemetry: dict) -> dict:
        ...
```

规则：

```text
packet_success=True
→ 接收并允许保存

packet_success=False
→ 记录丢包
→ 不更新设备最新通信数据
```

## 9. engine.py

负责人：梁 + 吴。

```python
def run_simulation(
    start_time: datetime,
    hours: int = 24
) -> list[dict]:
    ...
```

单时间步：

```text
environment
→ lighting
→ device
→ lora
→ gateway
→ database
→ fault
```

最终返回 `list[Telemetry]`。

## 10. database/db.py

当前第一版已实现 `devices / alarms / maintenance`，启动调用
`init_database()` 或兼容别名 `init_db()`，自动创建 `config.DATABASE_PATH`。
下面原规划中的遥测、操作日志接口留待引擎接入时实现。

```python
from database.db import (
    init_database, save_device, get_device, get_all_devices, delete_device,
    add_alarm, save_alarm, get_alarms, update_alarm_status, delete_alarm,
    add_maintenance_record, get_maintenance_records,
    update_maintenance_record, delete_maintenance_record,
)

init_database()
# save_device 接受 VirtualLightingNode 或字典，按编号更新已提供字段。
# get_device 未找到返回 None；列表查询返回 list[dict]。
alarm_id = add_alarm("CL-N01", "low_rssi", "WARNING", "RSSI 太低")
update_alarm_status(alarm_id, "ACKNOWLEDGED")
record_id = add_maintenance_record("CL-N01", "信号弱", "调整天线", "张三")
```

设备保存当前模型字段，并支持 `area/x/y/rssi/snr/packet_loss/fault/fault_type`；
`zone/area` 缺失一方时互相补齐，未提供的测量值为 NULL，不推断故障。
告警编号使用 TEXT UUID，与 `fault.py` 一致；`save_alarm` 接受其快照并按编号
更新，查询同时返回 `alarm_type/severity/timestamp` 和 `fault_type/level/created_at`。
时间返回 ISO 文本。告警状态为 `OPEN/ACKNOWLEDGED/CLOSED`；状态更新不自动
推断恢复时间，恢复时间由故障快照提供。维修默认状态为 `COMPLETED`，支持自定义
非空状态。更新、删除接口返回是否找到记录；删除设备保留历史告警和维修记录。

负责人：吴。

```python
def init_db() -> None: ...
def save_device(device: dict) -> None: ...
def save_telemetry(telemetry: dict) -> None: ...
def save_alarm(alarm: dict) -> None: ...
def save_operation_log(log: dict) -> None: ...

def get_latest_telemetry(device_id: str) -> dict | None: ...
def get_telemetry(device_id: str | None = None,
                  start_time=None,
                  end_time=None) -> list[dict]: ...
def get_alarms(status: str | None = None) -> list[dict]: ...
```

主要表：

```text
devices
telemetry
alarms
operation_logs
```

## 11. fault.py

负责人：熊。

```python
def check_fault(
    device: dict,
    telemetry: dict,
    gateway_status: str = "ONLINE"
) -> list[dict]:
    ...
```

检测：

```text
节点离线
RSSI <= -115 dBm → WARNING；RSSI <= -120 dBm → CRITICAL
PDR < 0.90 → WARNING；PDR < 0.80 → CRITICAL（PDR 使用 0~1 比例）
Lux < 0 或 Lux > 100000，以及缺失/非有限光照值 → CRITICAL
网关离线
```

故障模块负责“检测并生成 Alarm”，数据库保存由 `db.py` 完成。

2026-09-09 售后运维初稿实现保留上述 `check_fault` 调用形式，并补充
`FaultManager` 管理跨周期状态。连续 3 个周期无有效数据产生离线告警，
同一 RSSI/PDR 指标只生成最高级别的告警。`check_fault` 本身无状态，
跨周期去重、确认和恢复请使用管理器。接入示例：

```python
from simulator.fault import FaultManager

faults = FaultManager()  # 每次仿真/页面会话创建一次并持有
faults.inject_fault("CL-N01", "signal_attenuation", timestamp=now)

# 每周期：先处理传感器，再执行照明控制，然后计算正常 LoRa 结果。
environment = faults.apply_sensor("CL-N01", environment)
if environment["sensor_valid"]:
    # 调用 lighting，实际成功后令 auto_control_ok=True
    pass

result = faults.sample(
    device, telemetry, gateway_status="ONLINE",
    timestamp=now, auto_control_ok=auto_control_ok,
)
# telemetry 是本周期的数据，包含处理后的 Lux 和正常 LoRa 模块输出。
# 丢包/无数据也必须调用 sample（无数据传 None），每节点时间严格递增。
# result['device'] 给出有效 ONLINE/OFFLINE 状态，不修改原始设备字典。
# result['telemetry'] 是受故障影响的当次结果，PDR 为最近 20 次上传实测值。
# 仅 result['accept_telemetry'] 为 True 时保存为正常遥测。
# result['latest_telemetry'] 保留最近一次成功上传的有效数据。

faults.recover_device("CL-N01", timestamp=now)  # 此时仅 PENDING
# 后续 sample 收到新正常数据、RSSI > -115、PDR >= 0.9，且
# auto_control_ok=True 才关闭告警；外部设备仍离线时不会恢复。
# 网关恢复需要网关在线并通过至少一个节点的正常上传/控制验证。
alarms = faults.get_alarms()
logs = faults.get_operation_logs()
```

注入类型：`node_offline / signal_attenuation / high_packet_loss /
sensor_abnormal / gateway_offline`。默认额外损耗 25 dB、额外丢包概率 40%、
非法光照 -1 Lux；99999 Lux 在此标准下合法，不能用于非法值注入。
额外丢包只会把原本成功的包变成丢包，不会让正常 LoRa 已丢失的包恢复。

`acknowledge_alarm(alarm_id, description)` 确认告警，可记录分析原因；
`record_manual_control(device_id, result, description)` 记录设备模块报告的
实际手动控制结果（SUCCESS/FAILED），不直接控制灯具。

Alarm 增加 `fault_code`，关闭后增加 `recovered_at`；OperationLog 在原有
字段上补充 `fault_type / severity / description`。告警列表包含历史记录，
数据库应按 `alarm_id` 更新；日志列表是累计快照，调用方应按已保存位置
增量持久化，避免重复插入。数据库已提供 `save_alarm`；管理器仍仅保存在内存，
由调用方显式保存快照。操作日志持久化接口尚待实现。

## 12. analysis/energy.py

负责人：胡。

```python
def calculate_energy(
    power_w: float,
    step_minutes: int = 5
) -> float:
    ...

def calculate_total_energy(
    telemetry_list: list[dict]
) -> float:
    ...

def calculate_saving_rate(
    traditional_energy: float,
    smart_energy: float
) -> float:
    ...

def simulate_smart_daily_energy(
    simulation_day: date | datetime,
    device_ids: Iterable[str] | None = None
) -> dict:
    ...
```

`simulate_smart_daily_energy` 将每个代表节点接入环境、自动调光和功率计算，
返回设备、区域、规划片区及全校代表回路的逐日仿真估算能耗。

公式：

```text
E(Wh) = P(W) × Δt(h)

节能率 =
(传统照明能耗 - 智能照明能耗)
/ 传统照明能耗 × 100%
```

## 13. tests/test_system.py

负责人：胡。

至少包含：

```python
test_lighting_classroom()
test_lighting_corridor()
test_lighting_road()
test_device_power()
test_lora_result()
test_gateway_receive()
test_energy()
test_full_simulation()
```

验证照明逻辑、LoRa指标、网关、24小时864条数据、数据库、能耗和故障。

## 14. Streamlit 页面

梁负责总集成，各模块负责人提供数据。

```text
pages/
├── 01_系统总览.py
├── 02_区域监控.py
├── 03_设备管理.py
├── 04_LoRa网络.py
├── 05_网关监控.py
├── 06_能耗分析.py
├── 07_告警中心.py
├── 08_运维管理.py
└── 09_实验测试.py
```

页面只展示数据，不重新实现底层算法。

## 15. 模块边界

| 人员 | 主责 |
|---|---|
| 梁 | `config.py`、`app.py`、接口规范、系统集成、Git、页面导航 |
| 方 | `environment.py`、区域参数、区域监控 |
| 吴 | `device.py`、`lighting.py`、`lora.py`、`gateway.py`、`engine.py`、`db.py` |
| 胡 | `test_system.py`、`energy.py`、测试页面、测试数据 |
| 熊 | `fault.py`、告警、远程控制、运维日志 |

禁止：

```text
environment.py → database
lighting.py → Streamlit
lora.py → Streamlit
fault.py → 直接修改设备亮度
pages/*.py → 自己重新计算LoRa
```

## 16. Git 协作规则

分支：

```text
main
├── liang
├── fang
├── wu
├── hu
└── xiong
```

流程：

```text
个人分支
→ 本地测试
→ git push
→ Pull Request
→ 梁检查
→ Merge into main
```

Commit 示例：

```text
初始化项目结构
完成环境模拟
完成照明控制
完成设备模型
完成LoRa通信
完成网关模型
完成仿真引擎
完成数据库
完成能耗分析
完成故障检测
增加测试
修复LoRa PDR计算
```

## 17. 第一软件里程碑

暂时不要做漂亮网页。

先让终端跑通一条完整链：

```text
10:00
→ CL-N01
→ lux = 320
→ occupancy = True
→ brightness = 100%
→ power = 80W
→ RSSI = -82dBm
→ SNR = 7.4dB
→ packet = SUCCESS
→ GW-01 received
→ database saved
```

成功后扩展：

```text
5分钟步长
→ 24小时
→ 288时间点
→ 3节点
→ 约864条Telemetry
```

然后再进入 Streamlit 和高级运维功能。

## 18. 接口修改规则

如果发现接口需要改变：

1. 先提出修改。
2. 梁确认。
3. 更新本文件。
4. 再修改代码。
5. Commit 中注明接口变化。

所有模块必须以本文件的 V1 接口为准。
