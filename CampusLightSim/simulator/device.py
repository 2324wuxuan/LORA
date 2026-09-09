"""CampusLightSim virtual lighting device model.

负责人：吴。

本模块只负责单个照明节点自身的状态：灯具开关、亮度、功率、控制模式、
在线状态，以及缓存最近一次上报的环境数据（lux / occupancy）。

不做的事情（按 interfaces.md 的模块边界）：
    - 不做照明决策算法（由 ``control/lighting.py`` 的 ``auto_control`` 完成，
      算好的 brightness 通过 ``set_brightness`` 传给设备）。
    - 不访问数据库（由 ``database/db.py`` 完成）。
    - 不模拟 LoRa/网关通信（由 ``lora.py`` / ``gateway.py`` 完成）。
"""

from __future__ import annotations

from typing import Any

from config import SYSTEM, get_device, get_zone

_VALID_MODES = tuple(SYSTEM.get("available_modes", ["AUTO", "MANUAL"]))
_DEFAULT_MODE = SYSTEM.get("default_mode", "AUTO")
_BRIGHTNESS_MIN = float(SYSTEM.get("brightness_min", 0))
_BRIGHTNESS_MAX = float(SYSTEM.get("brightness_max", 100))


class VirtualLightingNode:
    """单个虚拟照明节点（对应 config.DEVICES 中的一条记录，如 CL-N01）。"""

    def __init__(
        self,
        device_id: str,
        name: str,
        zone: str,
        distance: float,
        sf: int,
        rated_power: float,
        *,
        mode: str = _DEFAULT_MODE,
        lamp_state: bool = False,
        brightness: float = 0.0,
        online: bool = True,
        lux: float = 0.0,
        occupancy: bool = False,
    ) -> None:
        if not device_id:
            raise ValueError("device_id 不能为空")
        if not name:
            raise ValueError("name 不能为空")
        if not zone:
            raise ValueError("zone 不能为空")
        if distance <= 0:
            raise ValueError("distance 必须大于 0")
        if int(sf) not in range(7, 13):
            raise ValueError("sf 必须为 7~12")
        if rated_power <= 0:
            raise ValueError("rated_power 必须大于 0")

        # 静态属性：设备身份与硬件参数，创建后基本不变。
        self.device_id = device_id
        self.name = name
        self.zone = zone
        self.distance = float(distance)
        self.sf = int(sf)
        self.rated_power = float(rated_power)

        # 灯具/通信状态。
        self.lamp_state = bool(lamp_state)
        self.online = bool(online)
        self.set_mode(mode)

        # 环境缓存（由 update_environment 写入，供 lighting.py 决策使用）。
        self.lux = 0.0
        self.occupancy = False
        self.update_environment(lux, occupancy)

        # 亮度 / 功率，最后计算，确保依赖的属性都已就绪。
        self.brightness = 0.0
        self.power = 0.0
        self.set_brightness(brightness)

    @classmethod
    def from_config(cls, device_id: str) -> "VirtualLightingNode":
        """按 config.DEVICES / config.ZONES 中的记录快速构造一个节点。

        例如 ``VirtualLightingNode.from_config("CL-N01")``。
        """
        device_cfg = get_device(device_id)
        zone_cfg = get_zone(device_cfg["zone_id"])
        initial_brightness = float(device_cfg.get("initial_brightness", 0))
        return cls(
            device_id=device_id,
            name=device_cfg.get("device_name", device_id),
            zone=zone_cfg.get("name", device_cfg["zone_id"]),
            distance=device_cfg["distance_to_gateway_m"],
            sf=device_cfg["lora_sf"],
            rated_power=device_cfg["rated_power_w"],
            mode=device_cfg.get("initial_mode", _DEFAULT_MODE),
            lamp_state=initial_brightness > 0,
            brightness=initial_brightness,
            online=device_cfg.get("initial_status", "ONLINE") == "ONLINE",
        )

    def update_environment(self, lux: float, occupancy: bool) -> None:
        """写入最近一次上报的环境数据（不做任何照明决策）。"""
        if lux < 0:
            raise ValueError("lux 不能小于 0")
        self.lux = float(lux)
        self.occupancy = bool(occupancy)

    def set_brightness(self, value: float) -> None:
        """设置目标亮度（0~100），并同步刷新功率。

        例如 ``set_brightness(70)`` 表示 70%。
        """
        if not _BRIGHTNESS_MIN <= value <= _BRIGHTNESS_MAX:
            raise ValueError(f"brightness 必须在 {_BRIGHTNESS_MIN}~{_BRIGHTNESS_MAX} 之间")
        self.brightness = float(value)
        self.power = self.calculate_power()

    def turn_on(self) -> None:
        """开灯，并按当前亮度刷新功率。"""
        self.lamp_state = True
        self.power = self.calculate_power()

    def turn_off(self) -> None:
        """关灯；亮度设置予以保留，但功率归零。"""
        self.lamp_state = False
        self.power = self.calculate_power()

    def set_mode(self, mode: str) -> None:
        """切换控制模式，只能是 config.SYSTEM['available_modes'] 中的值。

        例如 ``set_mode("AUTO")`` 或 ``set_mode("MANUAL")``。
        """
        normalized = str(mode).upper()
        if normalized not in _VALID_MODES:
            raise ValueError(f"mode 必须是 {_VALID_MODES} 之一")
        self.mode = normalized

    def set_online(self, online: bool) -> None:
        """标记节点通信在线状态（供 gateway.py / fault.py 调用）。"""
        self.online = bool(online)

    def calculate_power(self) -> float:
        """power = rated_power × brightness / 100；灯关闭时功率为 0。"""
        if not self.lamp_state:
            return 0.0
        return round(self.rated_power * self.brightness / 100, 3)

    def to_dict(self) -> dict[str, Any]:
        """导出当前状态快照，便于 db.save_device() 或调试查看。"""
        return {
            "device_id": self.device_id,
            "name": self.name,
            "zone": self.zone,
            "distance": self.distance,
            "sf": self.sf,
            "rated_power": self.rated_power,
            "lamp_state": self.lamp_state,
            "brightness": self.brightness,
            "power": self.power,
            "mode": self.mode,
            "online": self.online,
            "lux": self.lux,
            "occupancy": self.occupancy,
        }

    def __repr__(self) -> str:  # pragma: no cover - 便于调试打印
        return (
            f"VirtualLightingNode(device_id={self.device_id!r}, name={self.name!r}, "
            f"mode={self.mode!r}, lamp_state={self.lamp_state}, "
            f"brightness={self.brightness}, power={self.power}, online={self.online})"
        )


__all__ = ["VirtualLightingNode"]