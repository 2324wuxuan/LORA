"""Energy calculations shared by the simulation and analysis page.

The traditional scenario parameters are defined by the presales plan in
``config.py``: all lamps operate at the configured brightness from 07:00 to
22:00.  Smart energy is integrated from the actual telemetry power values.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from config import DEVICES, ENERGY, SIMULATION_STEP_MINUTES


def calculate_energy(power_w: float, step_minutes: int = SIMULATION_STEP_MINUTES) -> float:
    """Convert one constant-power sampling interval to kWh."""
    if power_w < 0:
        raise ValueError("power_w 不能小于 0")
    if step_minutes <= 0:
        raise ValueError("step_minutes 必须大于 0")
    return float(power_w) * (step_minutes / 60) / 1000


def calculate_total_energy(
    telemetry_list: Iterable[Mapping],
    step_minutes: int = SIMULATION_STEP_MINUTES,
) -> float:
    """Integrate smart-lighting telemetry power and return kWh."""
    total = 0.0
    for telemetry in telemetry_list:
        if "power" not in telemetry:
            raise KeyError("Telemetry 缺少 power 字段")
        total += calculate_energy(float(telemetry["power"]), step_minutes)
    return round(total, 6)


def calculate_traditional_daily_energy(
    devices: Mapping[str, Mapping] = DEVICES,
) -> float:
    """Return one day's energy for the configured traditional strategy."""
    start_hour = float(ENERGY["traditional_start_hour"])
    end_hour = float(ENERGY["traditional_end_hour"])
    duration_hours = end_hour - start_hour
    if duration_hours < 0:
        duration_hours += 24
    brightness_ratio = float(ENERGY["traditional_brightness"]) / 100
    rated_power_w = sum(float(device["rated_power_w"]) for device in devices.values())
    return round(rated_power_w * brightness_ratio * duration_hours / 1000, 6)


def calculate_saving_rate(traditional_energy: float, smart_energy: float) -> float:
    """Return energy-saving percentage relative to the traditional scheme."""
    if traditional_energy <= 0:
        raise ValueError("traditional_energy 必须大于 0")
    if smart_energy < 0:
        raise ValueError("smart_energy 不能小于 0")
    return round((traditional_energy - smart_energy) / traditional_energy * 100, 2)


def compare_daily_energy(telemetry_list: Iterable[Mapping]) -> dict:
    """Build the traditional-vs-smart result used by reports and pages."""
    traditional = calculate_traditional_daily_energy()
    smart = calculate_total_energy(telemetry_list)
    return {
        "traditional_energy_kwh": traditional,
        "smart_energy_kwh": smart,
        "saved_energy_kwh": round(traditional - smart, 6),
        "saving_rate_percent": calculate_saving_rate(traditional, smart),
    }


__all__ = [
    "calculate_energy",
    "calculate_saving_rate",
    "calculate_total_energy",
    "calculate_traditional_daily_energy",
    "compare_daily_energy",
]
