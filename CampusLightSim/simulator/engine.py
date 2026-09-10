"""CampusLightSim 仿真核心引擎：把环境、照明、设备、LoRa、网关、故障和数据库
模块按 interfaces.md 第 9 节规定的数据流串起来。

负责人：梁 + 吴。

对外只暴露 ``run_simulation``（以及供细粒度复用的 ``simulate_step``）。每个
时间点、每个设备依次完成以下步骤：

    1  获取当前模拟时间        循环步进 start_time + index * step_minutes
    2  获取区域光照            simulator.environment.get_environment
    3  获取人员状态            同上（lux / occupancy 一次返回）
    4  更新设备数据            VirtualLightingNode.update_environment
    5  执行智能照明策略        control.lighting.auto_control（仅 AUTO 模式）
    6  算亮度                  VirtualLightingNode.set_brightness
    7  算功率                  VirtualLightingNode.calculate_power（内部自动调用）
    8~12  执行LoRa发送 / 算RSSI / 算SNR / 判丢包 / Gateway接收
                              委托给 FaultManager.sample_network——它在内部调用
                              simulator.gateway.select_gateway →
                              simulator.lora.calculate_link 完成三网关选路、
                              RSSI/SNR/丢包判定和接收，engine 不再重复计算，
                              也不提前叠加信号损耗（interfaces.md 第 11 节的
                              明确要求）。旧的单网关 LoRaGateway.receive 是
                              兼容入口，三网关配置下不由 engine 直接调用。
    13 写入数据库              database.db.save_device / save_alarm
    14 检查告警                FaultManager.sample_network 内部的 check_fault，
                              结果随 result["alarms"] 一并返回

engine.py 不重新实现任何被调用模块内部的算法，只负责按顺序编排调用，并把
结果汇总成 interfaces.md 第 3 节规定的 Telemetry 列表返回给调用方（Streamlit
页面、测试或命令行）。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from config import DEVICES, RANDOM_SEED, SIMULATION_STEP_MINUTES
from control.lighting import auto_control, reset_state
from database import db
from simulator.device import VirtualLightingNode
from simulator.environment import get_environment
from simulator.fault import FaultManager

# 告警状态更新时用于选出“当前最值得关注”的那一条，写入 devices.fault_type。
_SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}


def _select_device_ids(device_ids: Iterable[str] | None) -> list[str]:
    """校验并规范化参与仿真的设备编号；默认使用全部 10 个代表节点。"""
    if device_ids is None:
        return list(DEVICES)
    selected = list(device_ids)
    if not selected:
        raise ValueError("至少需要一个设备参与仿真")
    unknown = [device_id for device_id in selected if device_id not in DEVICES]
    if unknown:
        raise KeyError(f"未知设备编号: {', '.join(unknown)}")
    return selected


def _apply_brightness(node: VirtualLightingNode, brightness: float) -> None:
    """按 device.py 暴露的公开接口设置亮度，同时同步开关状态。

    device.py 的 calculate_power 依据 lamp_state 判断是否输出功率，所以必须
    先用 turn_on()/turn_off() 同步开关，再调用 set_brightness 写入目标亮度，
    两者都会各自触发一次功率重算，顺序调换会导致功率短暂读到旧亮度。
    """
    if brightness > 0:
        node.turn_on()
    else:
        node.turn_off()
    node.set_brightness(brightness)


def simulate_step(
    node: VirtualLightingNode,
    zone_id: str,
    timestamp: datetime,
    *,
    fault_manager: FaultManager,
    gateways: dict | None = None,
) -> dict:
    """推进单个设备一个采样周期，返回 FaultManager.sample_network 的完整快照。

    步骤 1~7（时间→环境→人员→更新设备→智能照明→亮度→功率）在本函数内完成；
    步骤 8~12、14（LoRa/RSSI/SNR/丢包/Gateway接收、检查告警）委托给
    FaultManager.sample_network。返回值中 ``telemetry`` 为本周期数据，
    ``device`` 为设备快照，``alarms`` 为当前全部告警（供上层持久化）。
    """
    raw_environment = get_environment(zone_id, timestamp)
    # 先叠加传感器故障：sensor_abnormal 注入时 lux 会被替换成非法值，
    # sensor_valid=False 时不得参与后续的智能照明决策。
    environment = fault_manager.apply_sensor(node.device_id, raw_environment)
    sensor_valid = environment["sensor_valid"]

    auto_control_ok = False
    if sensor_valid:
        lux, occupancy = float(environment["lux"]), bool(environment["occupancy"])
        node.update_environment(lux, occupancy)
        if node.mode == "AUTO":
            brightness = auto_control(zone_id, lux, occupancy, timestamp)
            # auto_control 真正被调用且未抛异常后才置 True，不能仅凭 Lux 合法
            # 就推定控制成功（interfaces.md 第 11 节的要求）。
            auto_control_ok = True
        else:
            # MANUAL 模式亮度由远程控制另行设置，这里保持现状不重新计算。
            brightness = node.brightness
        _apply_brightness(node, brightness)
    # 传感器非法时保留设备上一周期的亮度/功率/缓存环境值，形成故障期间的
    # “保持最后已知状态”的安全兜底，而不是拿非法读数继续计算。

    telemetry = {
        "lux": environment["lux"],
        "occupancy": environment["occupancy"],
        "brightness": node.brightness,
        "power": node.power,
    }

    result = fault_manager.sample_network(
        node.to_dict(), telemetry,
        timestamp=timestamp, gateways=gateways, auto_control_ok=auto_control_ok,
    )

    # 把本周期选中的网关/距离写回设备对象，供下一周期及页面展示使用。
    link_telemetry = result["telemetry"]
    node.update_link({
        "gateway_id": link_telemetry.get("gateway_id"),
        "distance_m": link_telemetry.get("distance_m"),
    })
    return result


def _build_telemetry(device_id: str, zone_id: str, telemetry: dict) -> dict:
    """按 interfaces.md 第 3 节的 Telemetry 数据契约整理返回结果。"""
    return {
        "timestamp": telemetry["timestamp"],
        "device_id": device_id,
        "zone_id": zone_id,
        "lux": telemetry["lux"],
        "occupancy": telemetry["occupancy"],
        "brightness": telemetry["brightness"],
        "power": telemetry["power"],
        "rssi": telemetry.get("rssi"),
        "snr": telemetry.get("snr"),
        "delay_ms": telemetry.get("delay_ms"),
        "packet_success": telemetry.get("packet_success"),
        # 额外字段：不在 V1 契约中强制要求，但对页面/分析有用，保留不影响
        # 只读取标准字段的调用方。
        "gateway_id": telemetry.get("gateway_id"),
        "pdr": telemetry.get("pdr"),
    }


def _persist(device_id: str, result: dict, persisted_alarm_status: dict[str, str]) -> None:
    """写入数据库：设备快照（含通信指标）与告警快照的增量保存。"""
    telemetry = result["telemetry"]
    device_alarms = sorted(
        (alarm for alarm in result["alarms"]
         if alarm["device_id"] == device_id and alarm["status"] == "OPEN"),
        key=lambda alarm: _SEVERITY_ORDER.get(alarm["severity"], 9),
    )
    pdr = telemetry.get("pdr")
    db.save_device({
        **result["device"],
        "rssi": telemetry.get("rssi"),
        "snr": telemetry.get("snr"),
        "packet_loss": round(1 - pdr, 4) if pdr is not None else None,
        "fault": bool(device_alarms),
        "fault_type": device_alarms[0]["alarm_type"] if device_alarms else None,
    })
    # 告警快照按 alarm_id 幂等更新；只在状态变化时才重新写入，避免同一设备
    # 反复保存别的设备/网关未变化的历史告警。
    for alarm in result["alarms"]:
        if persisted_alarm_status.get(alarm["alarm_id"]) != alarm["status"]:
            db.save_alarm(alarm)
            persisted_alarm_status[alarm["alarm_id"]] = alarm["status"]


def run_simulation(
    start_time: datetime,
    hours: float = 24,
    device_ids: Iterable[str] | None = None,
    *,
    step_minutes: int = SIMULATION_STEP_MINUTES,
    gateways: dict | None = None,
    fault_manager: FaultManager | None = None,
    nodes: dict[str, VirtualLightingNode] | None = None,
    seed: int = RANDOM_SEED,
    persist: bool = True,
    reset_lighting_state: bool = True,
) -> list[dict]:
    """运行一段仿真，返回按时间→设备顺序排列的 Telemetry 列表。

    参数：
        start_time：仿真起始时刻。
        hours：仿真时长（小时），默认 24；按 step_minutes 换算成采样点数。
        device_ids：参与仿真的设备编号；默认全部 10 个代表节点，也可以只传
            一期的 ["CL-N01", "CL-N02", "CL-N03"] 做小范围验证。
        step_minutes：采样步长（分钟），默认取 config.SIMULATION_STEP_MINUTES（5）。
        gateways：自定义网关拓扑；默认 None 时 FaultManager 内部使用
            config.GATEWAYS。
        fault_manager / nodes：传入已有实例可以延续同一场会话的迟滞、故障注入
            和链路状态（例如 Streamlit 按步推进仿真时间）；不传时各自新建。
        seed：fault_manager 为 None 时用于创建新 FaultManager 的随机种子。
        persist：是否把设备快照和告警写入数据库（database.db）；测试/预览
            可以传 False 跳过数据库开销。
        reset_lighting_state：是否在开始前清空 control.lighting 的教室迟滞
            记忆（用法与 pages/03_智能照明.py 的 _build_day_series 一致）。
            默认 True，独立调用之间互不污染；如果要用 fault_manager / nodes
            延续同一场会话跨多次调用推进时间，需显式传入 False，否则会清空
            迟滞记忆但不影响正确性（只是丢失了迟滞连续性）。

    返回：
        list[dict]，每个元素满足 interfaces.md 第 3 节的 Telemetry 契约
        （并附带 gateway_id / pdr 两个便于分析的额外字段）。
    """
    if not isinstance(start_time, datetime):
        raise TypeError("start_time 必须是 datetime")
    if hours < 0:
        raise ValueError("hours 不能小于 0")
    if step_minutes <= 0:
        raise ValueError("step_minutes 必须大于 0")

    selected_ids = _select_device_ids(device_ids)

    manager = fault_manager if fault_manager is not None else FaultManager(seed=seed)
    active_nodes = nodes if nodes is not None else {}
    for device_id in selected_ids:
        active_nodes.setdefault(device_id, VirtualLightingNode.from_config(device_id))

    if reset_lighting_state:
        for device_id in selected_ids:
            reset_state(DEVICES[device_id]["zone_id"])

    if persist:
        db.init_database()

    steps = int(hours * 60 // step_minutes)
    persisted_alarm_status: dict[str, str] = {}
    telemetry_list: list[dict] = []

    # 外层按时间推进、内层遍历设备：保证每个设备（及其所在 zone 的迟滞状态）
    # 收到的时间戳严格递增，同时符合“每一个时间点”依次跑完全部设备的要求。
    for index in range(steps):
        timestamp = start_time + timedelta(minutes=index * step_minutes)
        for device_id in selected_ids:
            zone_id = DEVICES[device_id]["zone_id"]
            node = active_nodes[device_id]
            result = simulate_step(
                node, zone_id, timestamp,
                fault_manager=manager, gateways=gateways,
            )
            telemetry_list.append(_build_telemetry(device_id, zone_id, result["telemetry"]))
            if persist:
                _persist(device_id, result, persisted_alarm_status)

    return telemetry_list


__all__ = ["run_simulation", "simulate_step"]


if __name__ == "__main__":
    # 自检：先用 simulate_step 手动跑通 interfaces.md 第 17 节要求的
    # “一条完整链”（单设备单时间点，不写库、便于逐行打印），再用
    # run_simulation 扩展到一期 3 个节点、288 个时间点（约 864 条 Telemetry，
    # 这一步会写入数据库）。
    demo_time = datetime(2026, 9, 9, 10, 0)
    demo_manager = FaultManager(seed=RANDOM_SEED)
    demo_node = VirtualLightingNode.from_config("CL-N01")
    reset_state("Z01")
    demo_result = simulate_step(demo_node, "Z01", demo_time, fault_manager=demo_manager)
    demo_telemetry = demo_result["telemetry"]
    print("10:00")
    print("→ CL-N01")
    print(f"→ lux = {demo_telemetry['lux']}")
    print(f"→ occupancy = {demo_telemetry['occupancy']}")
    print(f"→ brightness = {demo_telemetry['brightness']:.0f}%")
    print(f"→ power = {demo_telemetry['power']:.1f}W")
    print(f"→ RSSI = {demo_telemetry['rssi']:.1f}dBm")
    print(f"→ SNR = {demo_telemetry['snr']:.1f}dB")
    if demo_telemetry["packet_success"]:
        print(f"→ packet = SUCCESS")
        print(f"→ {demo_telemetry['gateway_id']} received")
    else:
        print("→ packet = FAIL（本次丢包，未被网关接收）")

    print()
    print("扩展：一期 3 个节点 × 24 小时 × 5 分钟步长 …")
    phase_one = run_simulation(
        demo_time.replace(hour=0, minute=0),
        hours=24,
        device_ids=["CL-N01", "CL-N02", "CL-N03"],
        persist=True,
    )
    print(f"共生成 Telemetry {len(phase_one)} 条"
          f"（预期 288 × 3 = {288 * 3}）")
    success_rate = sum(item["packet_success"] for item in phase_one) / len(phase_one)
    print(f"整体收包率 ≈ {success_rate:.1%}")