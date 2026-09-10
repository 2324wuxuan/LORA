"""可重复执行的系统质量检测用例与 CSV 导出。

本模块只调用各业务模块的公开接口，不访问业务数据库，也不修改 Streamlit
会话中的设备或故障状态。页面和 unittest 共用这里的用例，避免展示结果与
自动化测试采用两套不同口径。
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from analysis.energy import calculate_energy
from config import DEVICES, FAULTS, GATEWAYS, TEST_RESULTS_CSV
from control.lighting import auto_control, reset_state
from simulator.device import VirtualLightingNode
from simulator.fault import check_fault
from simulator.lora import calculate_link


def _result(
    case_id: str,
    category: str,
    name: str,
    test_input: str,
    expected: str,
    actual: str,
    passed: bool,
    basis: str,
) -> dict:
    return {
        "用例": case_id,
        "类别": category,
        "检测内容": name,
        "测试输入": test_input,
        "期望结果": expected,
        "实际结果": actual,
        "是否通过": "通过" if passed else "失败",
        "判定依据": basis,
    }


def _run_case(builder: Callable[[], dict], case_id: str, category: str, name: str) -> dict:
    """让单个用例失败时仍能继续展示其他质量检测结果。"""
    try:
        return builder()
    except Exception as exc:  # 页面需要把异常变成可审查的失败记录
        return _result(case_id, category, name, "执行公开接口", "无异常并满足断言",
                       f"{type(exc).__name__}: {exc}", False, "执行过程中出现异常")


def run_quality_checks(simulation_day: date | datetime | None = None) -> list[dict]:
    """运行文档规定的 T01～T07 功能验收用例。"""
    day = simulation_day.date() if isinstance(simulation_day, datetime) else simulation_day
    day = day or date.today()
    timestamp = datetime.combine(day, datetime.min.time()).replace(hour=10)

    def t01() -> dict:
        reset_state("Z01")
        brightness = auto_control("Z01", 300.0, True, timestamp)
        return _result("T01", "智能照明", "教室自动开灯", "Z01，300 lux，有人",
                       "亮度 100%", f"亮度 {brightness:.0f}%", brightness == 100,
                       "低于开灯阈值且有人")

    def t02() -> dict:
        reset_state("Z01")
        brightness = auto_control("Z01", 700.0, True, timestamp)
        return _result("T02", "智能照明", "教室自动关灯", "Z01，700 lux，有人",
                       "亮度 0%", f"亮度 {brightness:.0f}%", brightness == 0,
                       "高于关灯阈值")

    def t03() -> dict:
        node = VirtualLightingNode.from_config("CL-N01")
        node.set_mode("MANUAL")
        node.set_brightness(60)
        node.turn_on()
        expected_power = node.rated_power * 0.60
        passed = node.mode == "MANUAL" and node.brightness == 60 and node.power == expected_power
        return _result("T03", "远程控制", "MANUAL 亮度控制", "CL-N01，手动亮度 60%",
                       f"MANUAL，功率 {expected_power:.1f} W",
                       f"{node.mode}，功率 {node.power:.1f} W", passed,
                       "功率 = 额定功率 × 亮度比例")

    def t04() -> dict:
        device = {**DEVICES["CL-N01"], "device_id": "CL-N01"}
        link = calculate_link(device, "GW-01", GATEWAYS["GW-01"],
                              timestamp=timestamp, extra_loss_db=200, shadowing=False)
        passed = link["packet_success"] is False and link["packet_loss_probability"] == 1.0
        return _result("T04", "LoRa 网络", "严重衰减下丢包", "GW-01 链路附加损耗 200 dB",
                       "丢包概率 100%，本次收包失败",
                       f"丢包概率 {link['packet_loss_probability']:.0%}，"
                       f"本次收包{'成功' if link['packet_success'] else '失败'}",
                       passed, "RSSI 低于当前 SF 接收灵敏度")

    def t05() -> dict:
        threshold = float(FAULTS["very_low_rssi"]["threshold_dbm"])
        rssi = threshold - 1
        alarms = check_fault(
            {"device_id": "CL-N01", "online": True, "status": "ONLINE"},
            {"timestamp": timestamp, "packet_success": True, "lux": 300.0,
             "rssi": rssi, "pdr": 1.0},
        )
        kinds = {alarm["alarm_type"] for alarm in alarms}
        passed = "very_low_rssi" in kinds
        return _result("T05", "故障告警", "RSSI 严重异常告警", f"RSSI = {rssi:.0f} dBm",
                       "产生 very_low_rssi 告警", ", ".join(sorted(kinds)) or "未产生告警",
                       passed, f"严重告警阈值 ≤ {threshold:.0f} dBm")

    def t06() -> dict:
        alarms = check_fault(
            {"device_id": "CL-N01", "online": False, "status": "OFFLINE"}, None
        )
        kinds = {alarm["alarm_type"] for alarm in alarms}
        passed = "node_offline" in kinds
        return _result("T06", "故障告警", "节点离线告警", "CL-N01 状态 OFFLINE",
                       "产生 node_offline 告警", ", ".join(sorted(kinds)) or "未产生告警",
                       passed, "离线节点必须形成严重告警")

    def t07() -> dict:
        energy = calculate_energy(60.0, 5)
        passed = abs(energy - 0.005) < 1e-12
        return _result("T07", "能耗计算", "单周期电量换算", "60 W 持续 5 分钟",
                       "0.005 kWh", f"{energy:.6f} kWh", passed,
                       "E = P × Δt / 1000")

    cases = [
        (t01, "T01", "智能照明", "教室自动开灯"),
        (t02, "T02", "智能照明", "教室自动关灯"),
        (t03, "T03", "远程控制", "MANUAL 亮度控制"),
        (t04, "T04", "LoRa 网络", "严重衰减下丢包"),
        (t05, "T05", "故障告警", "RSSI 严重异常告警"),
        (t06, "T06", "故障告警", "节点离线告警"),
        (t07, "T07", "能耗计算", "单周期电量换算"),
    ]
    return [_run_case(builder, case_id, category, name)
            for builder, case_id, category, name in cases]


def results_to_csv_bytes(results: list[dict], executed_at: datetime | None = None) -> bytes:
    """生成 Excel 可直接打开的 UTF-8 BOM CSV。"""
    executed = (executed_at or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
    fields = ["检测时间", "用例", "类别", "检测内容", "测试输入", "期望结果",
              "实际结果", "是否通过", "判定依据"]
    from io import StringIO
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for result in results:
        writer.writerow({"检测时间": executed, **result})
    return buffer.getvalue().encode("utf-8-sig")


def save_results_csv(results: list[dict], path: Path = TEST_RESULTS_CSV) -> Path:
    """保存本次质量检查结果，覆盖上一版可复现的检查单。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(results_to_csv_bytes(results))
    return target


__all__ = ["run_quality_checks", "results_to_csv_bytes", "save_results_csv"]
