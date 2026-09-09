"""CampusLightSim 智能照明控制算法。

负责人：吴。

本模块只负责一件事：根据环境数据（光照 lux、人员 occupancy，以及道路场景
需要的时刻 timestamp）计算目标亮度 brightness（0~100 的百分比数值）。

不做的事情（按 interfaces.md 的模块边界）：
    - 不生成/模拟环境数据（由 ``simulator/environment.py`` 完成，本模块只
      接收调用方传入的 lux / occupancy）。
    - 不操作设备对象、不计算功率（由 ``simulator/device.py`` 的
      ``VirtualLightingNode.set_brightness`` / ``calculate_power`` 完成，
      本模块算好的 brightness 通过它传给设备）。
    - 不访问数据库、不模拟 LoRa/网关通信、不涉及 Streamlit 页面。

所有区域按 config.ZONES 中的 control_mode 复用三类规则；阈值统一来自
config.LIGHTING_RULES，本文件不按区域编号硬编码，便于扩展代表仿真节点：

Z01 主楼典型教室（LIGHT_OCCUPANCY，光照 + 人员）::

    lux < 450 且 有人   → 100%
    lux > 550           → 0%
    无人（lux 不在关灯区间时）→ 0%
    450 ~ 550           → 保持上一次的输出（迟滞/滞回控制）

Z02 主楼一层公共走廊（OCCUPANCY，仅人员）::

    有人 → 100%
    无人 → 20%（基础照明，不关到 0，方便夜间通行辨识）

Z03 主楼附近道路（TIME_LIGHT_OCCUPANCY，时间 + 光照 + 人员）::

    白天（lux >= day_lux_threshold）→ 0%
    夜间 + 有人 → 100%
    夜间 + 无人 → 40%（基础路灯照明）

    "白天/夜间"用环境光照 lux 是否达到 config 中的
    ``day_lux_threshold``（默认 50 lux）判断，而不是按时钟时间——这样更
    贴近真实路灯光敏传感器的工作方式，阴天、日食等异常光照也能正确处理；
    传入的 timestamp 目前只用于教室滞回状态按“同一物理设备的时间线”做
    合法性校验（禁止时间倒退导致状态错乱），不参与亮度判断本身。
"""

from __future__ import annotations

from datetime import datetime
from math import isfinite
from numbers import Real

from config import get_lighting_rule, get_zone


# ---------------------------------------------------------------------------
# 教室滞回（450~550 lux 保持上一状态）需要跨调用记住“上一次的亮度”。
# auto_control 是无状态函数接口（interfaces.md 规定的签名里没有 self /
# device 对象），因此用一个模块级字典按 zone_id 维护最近一次输出的亮度，
# 并记录该 zone 上一次调用的时间，用于校验时间线是否单调递增，避免
# 引擎/页面乱序调用把两个不同时间点的状态混在一起。
# ---------------------------------------------------------------------------
_last_brightness: dict[str, float] = {}
_last_timestamp: dict[str, datetime] = {}


def reset_state(zone_id: str | None = None) -> None:
    """清空迟滞记忆。

    zone_id 为 None 时清空全部区域；用于单元测试之间互不影响，或者仿真
    重新从某个起点开始时避免沿用上一轮遗留的状态。正常仿真/引擎运行过程
    中不需要调用本函数。
    """
    if zone_id is None:
        _last_brightness.clear()
        _last_timestamp.clear()
    else:
        _last_brightness.pop(zone_id, None)
        _last_timestamp.pop(zone_id, None)


def _validate_inputs(zone_id: str, lux: float, occupancy: bool) -> None:
    if not isinstance(zone_id, str) or not zone_id.strip():
        raise ValueError("zone_id 必须是非空字符串")
    if not isinstance(lux, Real) or isinstance(lux, bool) or not isfinite(lux):
        raise ValueError("lux 必须是有限数值")
    if lux < 0:
        raise ValueError("lux 不能小于 0")
    if not isinstance(occupancy, bool):
        raise ValueError("occupancy 必须是 bool")


def _check_timeline(zone_id: str, timestamp: datetime | None) -> None:
    """timestamp 非空时校验同一 zone 的调用时间不倒退，保护迟滞状态。"""
    if timestamp is None:
        return
    if not isinstance(timestamp, datetime):
        raise TypeError("timestamp 必须是 datetime 或 None")
    previous = _last_timestamp.get(zone_id)
    if previous is not None and timestamp < previous:
        raise ValueError(f"{zone_id} 的照明控制调用时间不能倒退：{timestamp} < {previous}")
    _last_timestamp[zone_id] = timestamp


def _control_classroom(zone_id: str, lux: float, occupancy: bool) -> float:
    """Z01 教室：光照 + 人员联合控制，450~550 lux 之间迟滞保持。"""
    rule = get_lighting_rule(zone_id)
    lux_on = float(rule["lux_on_threshold"])    # 450：低于此值且有人才可能开满
    lux_off = float(rule["lux_off_threshold"])  # 550：高于此值强制关灯
    on_brightness = float(rule["occupied_brightness"])      # 100
    off_brightness = float(rule["unoccupied_brightness"])   # 0

    if lux > lux_off:
        # 天光已经足够亮，不论是否有人都不需要人工照明。
        brightness = off_brightness
    elif lux < lux_on:
        # 天光不够亮：有人才开灯，无人直接关灯。
        brightness = on_brightness if occupancy else off_brightness
    else:
        # 450 <= lux <= 550：迟滞区间，沿用该区域上一次的输出，避免灯具
        # 在阈值附近因光照小幅波动而频繁开关闪烁。第一次调用没有历史状态
        # 时，按“无人则关、有人则开”的保守规则兜底。
        brightness = _last_brightness.get(zone_id, on_brightness if occupancy else off_brightness)

    _last_brightness[zone_id] = brightness
    return brightness


def _control_corridor(zone_id: str, occupancy: bool) -> float:
    """Z02 走廊：只看人员，无人时保留基础照明，不完全熄灭。"""
    rule = get_lighting_rule(zone_id)
    on_brightness = float(rule["occupied_brightness"])      # 100
    off_brightness = float(rule["unoccupied_brightness"])   # 20
    return on_brightness if occupancy else off_brightness


def _control_road(zone_id: str, lux: float, occupancy: bool) -> float:
    """Z03 道路：先按天光判断白天/夜间，夜间再按人员区分基础/加强照明。"""
    rule = get_lighting_rule(zone_id)
    day_threshold = float(rule["day_lux_threshold"])
    day_brightness = float(rule["day_brightness"])                        # 0
    night_occupied = float(rule["night_occupied_brightness"])             # 100
    night_unoccupied = float(rule["night_unoccupied_brightness"])         # 40

    is_daytime = lux >= day_threshold
    if is_daytime:
        return day_brightness
    return night_occupied if occupancy else night_unoccupied


def auto_control(
    zone_id: str,
    lux: float,
    occupancy: bool,
    timestamp: datetime | None = None,
) -> float:
    """计算目标亮度（0~100 的百分比）。

    参数：
        zone_id：区域编号，如 ``"Z01"``。
        lux：环境光照强度（lux），来自 ``environment.get_lux`` 或传感器。
        occupancy：是否有人，来自 ``environment.get_occupancy`` 或传感器。
        timestamp：可选，当前时刻。仅用于校验同一区域的调用时间线单调
            递增，从而保护教室迟滞状态不被乱序调用破坏；不参与亮度计算。

    返回：
        float，范围 0~100 的目标亮度百分比。

    异常：
        KeyError：zone_id 不在 config.LIGHTING_RULES 中。
        ValueError / TypeError：lux、occupancy、timestamp 类型或取值非法。
    """
    _validate_inputs(zone_id, lux, occupancy)
    zone = get_zone(zone_id)
    get_lighting_rule(zone_id)
    _check_timeline(zone_id, timestamp)
    control_mode = zone.get("control_mode")
    if control_mode == "LIGHT_OCCUPANCY":
        brightness = _control_classroom(zone_id, float(lux), occupancy)
    elif control_mode == "OCCUPANCY":
        brightness = _control_corridor(zone_id, occupancy)
    elif control_mode == "TIME_LIGHT_OCCUPANCY":
        brightness = _control_road(zone_id, float(lux), occupancy)
    else:
        raise ValueError(f"{zone_id} 使用了不支持的控制模式: {control_mode}")
    return max(0.0, min(100.0, brightness))


__all__ = ["auto_control", "reset_state"]


if __name__ == "__main__":
    # 简单自检：对应 interfaces.md 第 17 节里的第一条链路示例。
    demo_time = datetime(2026, 9, 9, 10, 0)
    print("Z01 lux=320 有人 →", auto_control("Z01", 320.0, True, demo_time))   # 100.0
    print("Z01 lux=600 有人 →", auto_control("Z01", 600.0, True, demo_time))   # 0.0

    reset_state("Z01")  # 演示迟滞：先清空历史，看“无历史时的兜底规则”。
    print("Z01 lux=500 有人（迟滞区，无历史，兜底=开）→", auto_control("Z01", 500.0, True, demo_time))   # 100.0
    print("Z01 lux=480 无人（迟滞区，沿用上一次=开）→", auto_control("Z01", 480.0, False, demo_time))    # 100.0（沿用，不因为这一刻无人就关）
    print("Z01 lux=600 有人（跳出迟滞区，强制关）→", auto_control("Z01", 600.0, True, demo_time))        # 0.0

    print("Z02 无人 →", auto_control("Z02", 0.0, False))                       # 20.0
    print("Z02 有人 →", auto_control("Z02", 0.0, True))                        # 100.0
    print("Z03 白天 →", auto_control("Z03", 300.0, True))                      # 0.0
    print("Z03 夜间有人 →", auto_control("Z03", 5.0, True))                    # 100.0
    print("Z03 夜间无人 →", auto_control("Z03", 5.0, False))                   # 40.0
