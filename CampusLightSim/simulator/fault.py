"""校园照明故障注入、检测与运维状态管理（软件仿真初版）。

check_fault 是兼容 V1 的无状态检测入口；连续周期、PDR 和告警生命周期
由每次仿真独立创建的 FaultManager 管理。模块不操作页面、数据库或灯具。
所有返回数据均为副本，数据库调用方负责保存告警快照及运维日志。
"""

from __future__ import annotations

from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime, timedelta
from math import isfinite
from numbers import Real
from random import Random
from uuid import uuid4

from config import (
    DEFAULT_GATEWAY_ID, DEVICES, GATEWAYS, FAULTS, FAULT_SIMULATION, RANDOM_SEED, TELEMETRY,
)


FAULT_CODES = {
    "node_offline": "F01", "low_rssi": "F02", "very_low_rssi": "F03",
    "low_pdr": "F04", "very_low_pdr": "F05", "sensor_abnormal": "F06",
    "high_packet_loss": "F07", "gateway_offline": "F08",
}
INJECTABLE = {"node_offline", "signal_attenuation", "high_packet_loss",
              "sensor_abnormal", "gateway_offline"}


def _number(value) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and isfinite(value)


def is_valid_lux(value) -> bool:
    """非法、缺失、非有限 Lux 均不得送入自动照明控制。"""
    rule = FAULTS["sensor_abnormal"]
    return _number(value) and rule["lux_min"] <= value <= rule["lux_max"]


def _online(device: dict) -> bool:
    return (device.get("online", True) is True
            and device.get("status", device.get("initial_status", "ONLINE")) == "ONLINE")


def check_fault(device: dict, telemetry: dict | None,
                gateway_status: str = "ONLINE", *, gateway_id=DEFAULT_GATEWAY_ID) -> list[dict]:
    """检测当前快照，返回 OPEN Alarm；不维护历史、不修改输入。

    PDR 使用 0~1 比例；未提供时不猜测。连续无数据周期由调用方通过
    device['missed_cycles'] 提供，或使用 FaultManager.sample 自动统计。
    同一指标只报告最高级别。无上传时不使用缓存遥测判断传感器/信号。
    """
    data = telemetry or {}
    device_id = device["device_id"]
    timestamp = data.get("timestamp") or datetime.now()
    alarms = []

    def add(kind, message, target=device_id):
        if any(a["alarm_type"] == kind and a["device_id"] == target for a in alarms):
            return
        if FAULTS[kind]["enabled"]:
            alarms.append({
                "alarm_id": str(uuid4()), "timestamp": timestamp,
                "device_id": target, "alarm_type": kind,
                "fault_code": FAULT_CODES[kind], "severity": FAULTS[kind]["severity"],
                "message": message, "status": "OPEN",
            })

    online = _online(device)
    injected = device.get("faults", {})
    if "sensor_abnormal" in injected:
        add("sensor_abnormal", "已注入光照传感器异常，禁止参与自动照明决策")
    if "signal_attenuation" in injected:
        alarms.append(dict(alarm_id=str(uuid4()), timestamp=timestamp, device_id=device_id,
                           alarm_type="signal_attenuation", fault_code="INJECT_SIGNAL",
                           severity="WARNING", message=f"已注入 {injected['signal_attenuation']:g} dB 信号衰减",
                           status="OPEN"))
    if not online or device.get("missed_cycles", 0) >= TELEMETRY["offline_after_failed_uploads"]:
        add("node_offline", "节点离线或连续三个采样周期无有效数据")
    if gateway_status != "ONLINE":
        add("gateway_offline", "网关离线，需检查备用链路", gateway_id)
    if online and gateway_status == "ONLINE" and data.get("packet_success") is True:
        if not is_valid_lux(data.get("lux")):
            add("sensor_abnormal", "光照数据非法，禁止参与自动照明决策")
        rssi = data.get("rssi")
        if _number(rssi):
            if rssi <= FAULTS["very_low_rssi"]["threshold_dbm"]:
                add("very_low_rssi", f"LoRa 信号严重异常：{rssi} dBm")
            elif rssi <= FAULTS["low_rssi"]["threshold_dbm"]:
                add("low_rssi", f"LoRa 信号较弱：{rssi} dBm")
    pdr = data.get("pdr")
    if pdr is not None:
        if not _number(pdr) or not 0 <= pdr <= 1:
            raise ValueError("PDR 必须是 0~1 的有限数值，例如 90% 写作 0.9")
        if pdr < FAULTS["very_low_pdr"]["threshold"]:
            add("very_low_pdr", f"数据包接收率严重异常：{pdr:.1%}")
        elif pdr < FAULTS["low_pdr"]["threshold"]:
            add("low_pdr", f"数据包接收率较低：{pdr:.1%}")
    if "high_packet_loss" in device.get("faults", {}):
        add("high_packet_loss", "已注入高丢包故障")
    return alarms


class FaultManager:
    """每个仿真/Streamlit 会话持有一个实例，避免用户之间共享故障状态。

    调度顺序：apply_sensor → 合法时调用 lighting → 正常 LoRa 计算 → sample。
    sample 每个节点每个采样周期调用一次，即使没有数据也传 None；timestamp
    必须严格递增，避免页面重复刷新误计周期。恢复不会清空真实 PDR 历史。
    """

    def __init__(self, seed: int = RANDOM_SEED):
        self._seed = seed
        self._rng = Random(seed)
        self._faults = defaultdict(dict)
        self._packets = defaultdict(lambda: deque(maxlen=FAULT_SIMULATION["pdr_window_size"]))
        self._missed = defaultdict(int)
        self._last_time = {}
        self._latest = {}
        self._alarms = {}
        self._alarm_history = []
        self._logs = []
        self._pending = {}

    def _target(self, device_id):
        if device_id not in DEVICES and device_id not in GATEWAYS:
            raise KeyError(f"未知设备：{device_id}")

    def _log(self, device_id, operation, fault_type, severity, result, description, timestamp):
        log = dict(log_id=str(uuid4()), timestamp=timestamp, device_id=device_id, operation=operation,
                   fault_type=fault_type, severity=severity, result=result,
                   description=description)
        self._logs.append(log)
        return deepcopy(log)

    def inject_fault(self, device_id: str, fault_type: str, *,
                     value: float | None = None, timestamp: datetime | None = None) -> dict:
        """叠加故障；信号衰减单位 dB，高丢包值为额外丢包概率（默认 40%）。"""
        self._target(device_id)
        if fault_type not in INJECTABLE:
            raise ValueError(f"不支持的注入类型：{fault_type}")
        if (device_id in GATEWAYS) != (fault_type == "gateway_offline"):
            raise ValueError("网关只支持 gateway_offline，节点不支持该类型")
        defaults = {"signal_attenuation": FAULT_SIMULATION["extra_loss_db"],
                    "high_packet_loss": FAULT_SIMULATION["packet_loss_probability"],
                    "sensor_abnormal": FAULT_SIMULATION["invalid_lux"]}
        value = defaults.get(fault_type, True) if value is None else value
        if fault_type in defaults:
            if not _number(value):
                raise ValueError("注入参数必须是有限数值")
            if fault_type == "signal_attenuation" and value <= 0:
                raise ValueError("额外损耗必须大于 0 dB")
            if fault_type == "high_packet_loss" and not 0 < value <= 1:
                raise ValueError("额外丢包概率必须在 (0, 1] 范围内")
            if fault_type == "sensor_abnormal" and is_valid_lux(value) and value != 99999:
                raise ValueError("传感器注入值必须非法，例如 -1 或 100001 Lux")
        self._faults[device_id][fault_type] = value
        severity = "WARNING" if fault_type in {"signal_attenuation", "high_packet_loss"} else "CRITICAL"
        return self._log(device_id, "inject_fault", fault_type, severity, "SUCCESS",
                         f"已注入故障，参数={value}", timestamp or datetime.now())

    def recover_device(self, device_id: str, fault_type: str | None = None, *,
                       timestamp: datetime | None = None) -> dict:
        """撤销指定/全部人为故障，等待后续检测；不修改外部真实设备状态。"""
        self._target(device_id)
        if fault_type is not None and fault_type not in INJECTABLE:
            raise ValueError(f"未知故障类型：{fault_type}")
        if fault_type is None:
            self._faults[device_id].clear()
        else:
            self._faults[device_id].pop(fault_type, None)
        now = timestamp or datetime.now()
        self._pending[device_id] = now
        return self._log(device_id, "recover_device", fault_type or "all", "INFO",
                         "PENDING", "已撤销注入，等待新的遥测及自动控制验证", now)

    def apply_sensor(self, device_id: str, environment: dict) -> dict:
        """在 lighting.auto_control 前调用；sensor_valid=False 时跳过自动决策。"""
        self._target(device_id)
        result = deepcopy(environment)
        if "sensor_abnormal" in self._faults[device_id]:
            result["lux"] = self._faults[device_id]["sensor_abnormal"]
        result["sensor_valid"] = (is_valid_lux(result.get("lux"))
                                  and "sensor_abnormal" not in self._faults[device_id])
        return result

    def next_sample_time(self, device_id: str, timestamp: datetime) -> datetime:
        """供按步检测页面使用，避免页面重跑或其他引擎调用造成重复周期。"""
        previous = self._last_time.get(device_id)
        return max(timestamp, previous + timedelta(minutes=TELEMETRY["upload_interval_minutes"])) if previous else timestamp

    def set_device_offline(self, device: dict, *, timestamp=None) -> dict:
        return self.inject_fault(device["device_id"], "node_offline", timestamp=timestamp)

    def inject_signal_attenuation(self, device: dict, *, timestamp=None) -> dict:
        return self.inject_fault(device["device_id"], "signal_attenuation", timestamp=timestamp)

    def sample(self, device: dict, telemetry: dict | None,
               gateway_status: str = "ONLINE", *, timestamp: datetime,
               auto_control_ok: bool = False, gateway_id=DEFAULT_GATEWAY_ID,
               link_adjusted: bool = False, all_alarms: bool = True) -> dict:
        """叠加异常、统计上传、更新告警，返回供引擎和数据库使用的快照。

        telemetry 为本周期原始正常 LoRa 结果（不得重复传入本方法的输出）。
        latest_telemetry 只在在线且成功上传有效数据时更新；遥测 pdr 输入被
        本实例最近 20 次上传的实测 PDR 替换。auto_control_ok 必须由控制模块
        明确报告，不能仅凭恢复按钮或 Lux 合法推定。
        """
        device_id = device["device_id"]
        self._target(device_id)
        if device_id in GATEWAYS:
            raise ValueError("sample 接收照明节点，网关状态通过 gateway_status 提供")
        if not isinstance(timestamp, datetime):
            raise TypeError("timestamp 必须是 datetime")
        if device_id in self._last_time and timestamp <= self._last_time[device_id]:
            raise ValueError("每个节点的采样时间必须严格递增")
        if telemetry and telemetry.get("device_id", device_id) != device_id:
            raise ValueError("遥测设备编号与检测节点不一致")
        if telemetry and telemetry.get("timestamp", timestamp) != timestamp:
            raise ValueError("必须传入本采样周期的新遥测，不能使用缓存数据")
        self._last_time[device_id] = timestamp
        faults = self._faults[device_id]
        node = deepcopy(device)
        node["online"] = _online(device) and "node_offline" not in faults
        node["status"] = "ONLINE" if node["online"] else "OFFLINE"
        node["faults"] = deepcopy(faults)
        gateway_online = gateway_status == "ONLINE" and not self._faults.get(gateway_id)
        node["gateway_id"] = gateway_id
        data = self.apply_sensor(device_id, telemetry or {})
        data.update(timestamp=timestamp, device_id=device_id)
        data["gateway_id"] = gateway_id
        if not link_adjusted and "signal_attenuation" in faults and _number(data.get("rssi")):
            data["rssi"] -= faults["signal_attenuation"]
        success = (bool(telemetry) and node["online"] and gateway_online
                   and data.get("packet_success") is True)
        if success and "high_packet_loss" in faults:
            success = self._rng.random() >= faults["high_packet_loss"]
        data["packet_success"] = success
        self._packets[device_id].append(success)
        data["pdr"] = sum(self._packets[device_id]) / len(self._packets[device_id])
        valid = success and data["sensor_valid"] and _number(data.get("rssi"))
        self._missed[device_id] = 0 if valid else self._missed[device_id] + 1
        node["missed_cycles"] = self._missed[device_id]
        if node["missed_cycles"] >= TELEMETRY["offline_after_failed_uploads"]:
            node["status"] = "OFFLINE"
        if valid:
            self._latest[device_id] = deepcopy(data)
        # 保留真实在线标志供检测区分“无有效数据”与主动离线。
        detected = check_fault({**node, "status": "ONLINE" if node["online"] else "OFFLINE"},
                               data, "ONLINE" if gateway_online else "OFFLINE", gateway_id=gateway_id)
        for alarm in detected:
            key = (alarm["device_id"], alarm["alarm_type"])
            if key not in self._alarms or self._alarms[key]["status"] == "CLOSED":
                if key in self._alarms:
                    self._alarm_history.append(deepcopy(self._alarms[key]))
                alarm["timestamp"] = timestamp
                self._alarms[key] = alarm
        healthy = (valid and not faults and gateway_online and auto_control_ok is True
                   and data["rssi"] > FAULTS["low_rssi"]["threshold_dbm"]
                   and data["pdr"] >= FAULTS["low_pdr"]["threshold"])
        if healthy:
            self._confirm_recovery(device_id, timestamp)
            # 网关恢复至少需要一次实际成功的节点上传作为验证。
            if gateway_id is not None:
                self._confirm_recovery(gateway_id, timestamp)
        return deepcopy(dict(device=node, telemetry=data, accept_telemetry=valid,
                             latest_telemetry=self._latest.get(device_id),
                             recovered=healthy, alarms=(self.get_alarms() if all_alarms else
                                 self.current_alarms_for([device_id, *GATEWAYS]))))

    def sample_network(self, device: dict, telemetry: dict | None, *, timestamp: datetime,
                       gateways: dict | None = None, auto_control_ok=False, all_alarms=True) -> dict:
        """三网关入口：环境/灯具遥测 → 叠加故障 → 动态选路 → 状态检测。

        正常链路由 gateway/lora 计算；本方法仅提供注入损耗及网关离线状态。
        网关恢复必须经该网关重新上传验证，备用网关成功不会关闭故障网关告警。
        """
        from simulator.gateway import select_gateway

        device_id = device["device_id"]
        self._target(device_id)
        if device_id in self._last_time and timestamp <= self._last_time[device_id]:
            raise ValueError("每个节点的采样时间必须严格递增")
        effective = deepcopy(GATEWAYS if gateways is None else gateways)
        for key, gateway in effective.items():
            self._target(key)
            if "gateway_offline" in self._faults[key]:
                gateway["status"] = "OFFLINE"
        link = select_gateway({**DEVICES[device_id], **device}, effective, timestamp=timestamp,
                              seed=self._seed,
                              extra_loss_db=self._faults[device_id].get("signal_attenuation", 0))
        result = self.sample(device, {**telemetry, **link} if telemetry is not None else None,
                             timestamp=timestamp, auto_control_ok=auto_control_ok,
                             gateway_id=link["gateway_id"], link_adjusted=True, all_alarms=all_alarms)
        for key, gateway in effective.items():
            if gateway["status"] == "ONLINE":
                continue
            alarm_key = (key, "gateway_offline")
            existing = self._alarms.get(alarm_key)
            if existing is None or existing["status"] == "CLOSED":
                if existing is not None:
                    self._alarm_history.append(deepcopy(existing))
                for alarm in check_fault({"device_id": device_id}, {"timestamp": timestamp},
                                         "OFFLINE", gateway_id=key):
                    if alarm["alarm_type"] == "gateway_offline":
                        self._alarms[alarm_key] = alarm
        result["alarms"] = (self.get_alarms() if all_alarms else
                            self.current_alarms_for([device_id, *effective]))
        result["gateway_links"] = link["gateway_links"]
        return result

    def _confirm_recovery(self, device_id, timestamp):
        if device_id in self._pending and timestamp <= self._pending[device_id]:
            return
        closed = False
        for kind in (*FAULT_CODES, "signal_attenuation"):
            alarm = self._alarms.get((device_id, kind))
            if alarm is not None and alarm["status"] != "CLOSED":
                alarm.update(status="CLOSED", recovered_at=timestamp)
                closed = True
        if closed or device_id in self._pending:
            self._pending.pop(device_id, None)
            self._log(device_id, "recovery_confirmed", "all", "INFO", "SUCCESS",
                      "新遥测、通信、传感器及自动控制验证通过，故障已恢复", timestamp)

    def acknowledge_alarm(self, alarm_id: str, description: str = "已确认故障对象，待分析处理",
                          *, timestamp: datetime | None = None) -> dict:
        for alarm in self._alarms.values():
            if alarm["alarm_id"] == alarm_id:
                if alarm["status"] == "CLOSED":
                    raise ValueError("已关闭告警不能再次确认")
                alarm["status"] = "ACKNOWLEDGED"
                self._log(alarm["device_id"], "acknowledge_alarm", alarm["alarm_type"],
                          alarm["severity"], "SUCCESS", description, timestamp or datetime.now())
                return deepcopy(alarm)
        raise KeyError(f"未知告警：{alarm_id}")

    def record_manual_control(self, device_id: str, result: str, description: str,
                              *, timestamp: datetime | None = None) -> dict:
        """设备模块执行控制后报告实际结果；本方法只记录，不改变亮度。"""
        self._target(device_id)
        if result not in {"SUCCESS", "FAILED"}:
            raise ValueError("控制结果必须为 SUCCESS 或 FAILED")
        return self._log(device_id, "manual_control", "none", "INFO", result,
                         description, timestamp or datetime.now())

    def current_alarms_for(self, targets):
        """Bounded current snapshot; complete historical snapshots remain available."""
        return deepcopy([self._alarms[(target, kind)] for target in targets
                         for kind in (*FAULT_CODES, "signal_attenuation")
                         if (target, kind) in self._alarms])

    def get_alarms(self, status: str | None = None) -> list[dict]:
        return deepcopy([a for a in [*self._alarm_history, *self._alarms.values()]
                         if status is None or a["status"] == status])

    def get_operation_logs(self) -> list[dict]:
        return deepcopy(self._logs)


__all__ = ["FaultManager", "check_fault", "is_valid_lux", "FAULT_CODES"]
