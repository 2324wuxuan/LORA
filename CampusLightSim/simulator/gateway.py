"""多网关链路选择与接收；不固定绑定片区，不访问数据库或页面。"""
from copy import deepcopy

from config import DEVICES, GATEWAYS, RANDOM_SEED
from simulator.lora import calculate_link


def select_gateway(device: dict, gateways: dict | None = None, *, timestamp=None,
                   seed=RANDOM_SEED, extra_loss_db=0.0, shadowing=True) -> dict:
    """先计算全部链路，再选可达在线网关中 RSSI 最大者。

    选择不参考本次随机收包结果，避免挑选成功包而人为抬高 PDR。
    无可达网关时 gateway_id=None；仍保留所有候选链路供诊断。
    """
    gateways = GATEWAYS if gateways is None else gateways
    device = {**DEVICES.get(device.get("device_id"), {}), **device}
    if "sf" in device:
        device["lora_sf"] = device["sf"]
    links = {key: calculate_link(device, key, value, timestamp=timestamp, seed=seed,
                                 extra_loss_db=extra_loss_db, shadowing=shadowing)
             for key, value in sorted(gateways.items())}
    candidates = [link for link in links.values() if link["reachable"]]
    selected = max(candidates, key=lambda link: link["rssi"]) if candidates else None
    return {**(selected or {"gateway_id": None, "rssi": None, "snr": None,
                            "distance_m": None, "delay_ms": None,
                            "packet_success": False, "packet_loss_probability": 1.0}),
            "gateway_links": links}


class LoRaGateway:
    def __init__(self, gateway_id: str):
        self.gateway_id = gateway_id
        self.config = deepcopy(GATEWAYS[gateway_id])

    def receive(self, telemetry: dict) -> dict:
        accepted = (self.config["status"] == "ONLINE"
                    and telemetry.get("gateway_id") == self.gateway_id
                    and telemetry.get("packet_success") is True)
        return {"gateway_id": self.gateway_id, "accepted": accepted,
                "telemetry": deepcopy(telemetry) if accepted else None}
