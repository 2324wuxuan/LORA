"""可重复的 LoRa 链路仿真；参数为实验模型，不承诺真实校园覆盖。

三维距离 → 对数路径损耗 + 建筑遮挡 + 阴影波动 → RSSI/SNR/丢包。
不按固定覆盖半径判断可达性，不将 RSSI 裁剪到绘图范围。
"""
from hashlib import sha256
from math import dist, isfinite, log10
from random import Random

from config import GATEWAY_RADIO, LORA, RANDOM_SEED


def link_distance(device: dict, gateway: dict) -> float:
    points = [tuple(float(item[key]) for key in ("x", "y", "height"))
              for item in (device, gateway)]
    if not all(isfinite(value) for point in points for value in point):
        raise ValueError("链路坐标必须是有限数值")
    return dist(*points)


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
    margin = rssi - LORA["sensitivity_dbm_by_sf"][sf]
    # 简化的接收曲线：灵敏度以下不接收，余量不足时逐步提高丢包概率。
    loss_probability = 1.0 if margin < 0 else min(
        1.0, LORA["base_packet_loss_probability"]
        + max(0.0, 1 - margin / LORA["additional_loss_threshold_db"]) * 0.8)
    return {"distance_m": distance_m, "rssi": rssi,
            "snr": rssi - LORA["noise_floor_dbm"],
            "packet_loss_probability": loss_probability,
            "packet_success": rng.random() >= loss_probability,
            "reachable": margin >= 0,
            "delay_ms": LORA["base_delay_ms"] + (sf - 7) * LORA["delay_per_sf_ms"]}


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
                  reachable=online and result["reachable"])
    return result
