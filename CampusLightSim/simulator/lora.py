"""可重复的 LoRa 链路仿真；参数为实验模型，不承诺真实校园覆盖。

三维距离 → 对数路径损耗 + 建筑遮挡 + 阴影波动 → RSSI/SNR/丢包。
不按固定覆盖半径判断可达性，不将 RSSI 裁剪到绘图范围。
"""
from hashlib import sha256
from math import ceil, dist, isfinite, log10
from random import Random

from config import GATEWAY_RADIO, LORA, RANDOM_SEED


def link_distance(device: dict, gateway: dict) -> float:
    points = [tuple(float(item[key]) for key in ("x", "y", "height"))
              for item in (device, gateway)]
    if not all(isfinite(value) for point in points for value in point):
        raise ValueError("链路坐标必须是有限数值")
    return dist(*points)


def calculate_airtime_ms(sf: int, *, payload_bytes: int | None = None) -> float:
    """估算一个 LoRa 上行包的空中时间（显式头、可配 CRC/前导码）。

    使用 Semtech LoRa 调制的符号时间及 payload symbol 公式。这里只计算
    无线包的 time-on-air，不模拟 LoRaWAN 接收窗口、排队和 IP 回传。
    """
    if sf not in range(7, 13):
        raise ValueError("SF 必须为 7~12")
    payload = LORA["payload_bytes"] if payload_bytes is None else payload_bytes
    if not isinstance(payload, int) or isinstance(payload, bool) or payload < 0:
        raise ValueError("payload_bytes 必须是非负整数")
    bandwidth_hz = float(LORA["bandwidth_khz"]) * 1000
    if bandwidth_hz <= 0:
        raise ValueError("LoRa 带宽必须大于 0")
    try:
        numerator_cr, denominator = (
            int(value) for value in str(LORA["coding_rate"]).split("/")
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("coding_rate 必须类似 4/5、4/6、4/7 或 4/8") from exc
    coding_rate_index = denominator - 4
    if numerator_cr != 4 or coding_rate_index not in range(1, 5):
        raise ValueError("coding_rate 必须为 4/5、4/6、4/7 或 4/8")

    symbol_seconds = 2**sf / bandwidth_hz
    low_data_rate_optimization = int(symbol_seconds >= 0.016)
    implicit_header = int(not LORA["explicit_header"])
    crc = int(bool(LORA["crc_enabled"]))
    numerator = 8 * payload - 4 * sf + 28 + 16 * crc - 20 * implicit_header
    payload_symbols = 8 + max(
        ceil(numerator / (4 * (sf - 2 * low_data_rate_optimization)))
        * (coding_rate_index + 4),
        0,
    )
    preamble_symbols = float(LORA["preamble_symbols"]) + 4.25
    return (preamble_symbols + payload_symbols) * symbol_seconds * 1000


def simulate_lora(distance_m: float, sf: int, obstacle: str,
                  tx_power_dbm: float = 14.0, *, gateway: dict | None = None,
                  environment: str = "outdoor", seed=RANDOM_SEED,
                  extra_loss_db: float = 0.0, shadowing: bool = True) -> dict:
    """兼容 V1 距离接口；extra_loss_db 由故障模块提供，仅叠加异常损耗。"""
    if not isfinite(distance_m) or distance_m < 0 or sf not in range(7, 13):
        raise ValueError("距离必须非负且有限，SF 必须为 7~12")
    if not isfinite(tx_power_dbm) or not isfinite(extra_loss_db) or extra_loss_db < 0:
        raise ValueError("发射功率及附加损耗必须有限，附加损耗不能为负")
    if environment not in {"indoor", "outdoor"}:
        raise ValueError("environment 必须为 indoor/outdoor")
    radio = GATEWAY_RADIO if gateway is None else gateway
    rng = Random(seed)
    distance = max(distance_m, radio["reference_distance_m"])
    exponent = radio[f"path_loss_exponent_{environment}"]
    loss = (radio["reference_path_loss_db"]
            + 10 * exponent * log10(distance / radio["reference_distance_m"])
            + LORA["obstacle_loss_db"][obstacle] + extra_loss_db)
    if shadowing:
        loss += rng.gauss(0, radio["default_shadowing_std_db"])
    rssi = tx_power_dbm + radio["antenna_gain_dbi"] - loss
    sensitivity = float(LORA["sensitivity_dbm_by_sf"][sf])
    margin = rssi - sensitivity
    raw_snr = rssi - LORA["noise_floor_dbm"]
    reported_snr = min(
        LORA["reported_snr_max_db"],
        max(LORA["reported_snr_min_db"], raw_snr),
    )
    # 简化的接收曲线：灵敏度以下不接收，余量不足时逐步提高丢包概率。
    loss_probability = 1.0 if margin < 0 else min(
        1.0, LORA["base_packet_loss_probability"]
        + max(0.0, 1 - margin / LORA["additional_loss_threshold_db"]) * 0.8)
    airtime_ms = calculate_airtime_ms(sf)
    return {"distance_m": distance_m, "rssi": rssi,
            "snr": reported_snr, "raw_snr": raw_snr,
            "sensitivity_dbm": sensitivity, "link_margin_db": margin,
            "packet_loss_probability": loss_probability,
            "packet_success": rng.random() >= loss_probability,
            "radio_reachable": margin >= 0, "reachable": margin >= 0,
            "airtime_ms": airtime_ms,
            "delay_ms": LORA["base_delay_ms"] + airtime_ms}


def calculate_link(device: dict, gateway_id: str, gateway: dict, *,
                   timestamp=None, seed=RANDOM_SEED, extra_loss_db=0.0,
                   shadowing=True) -> dict:
    # 每设备/网关/周期独立随机流，停用一个网关不改变其他链路的随机结果。
    key = f"{seed}|{device.get('device_id', '')}|{gateway_id}|{timestamp}"
    stable_seed = int.from_bytes(sha256(key.encode()).digest()[:8], "big")
    result = simulate_lora(link_distance(device, gateway), device["lora_sf"],
                           device["obstacle"], device["lora_tx_power_dbm"],
                           gateway=gateway, environment=device["environment"],
                           seed=stable_seed, extra_loss_db=extra_loss_db, shadowing=shadowing)
    online = gateway.get("status", "ONLINE") == "ONLINE"
    result.update(gateway_id=gateway_id, online=online,
                  packet_success=online and result["packet_success"],
                  reachable=online and result["radio_reachable"])
    return result
