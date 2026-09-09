"""Energy calculations shared by the simulation and analysis page.

The traditional scenario parameters are defined by the presales plan in
``config.py``: all lamps operate at the configured brightness from 07:00 to
22:00.  Smart energy is integrated from the actual telemetry power values.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta

from config import DEVICES, ENERGY, SIMULATION_STEP_MINUTES
from control.lighting import auto_control, reset_state
from simulator.environment import get_lux, get_occupancy


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


def simulate_smart_daily_energy(
    simulation_day: date | datetime,
    device_ids: Iterable[str] | None = None,
) -> dict:
    """Run one deterministic 24-hour smart-lighting estimate.

    Each configured representative device is connected to the same Lux →
    Occupancy → automatic brightness chain used by the Streamlit lighting page.
    Results describe representative circuits, not a measured campus total.
    """
    if isinstance(simulation_day, datetime):
        day = simulation_day.date()
    elif isinstance(simulation_day, date):
        day = simulation_day
    else:
        raise TypeError("simulation_day 必须是 date 或 datetime")

    selected_ids = list(DEVICES) if device_ids is None else list(device_ids)
    if not selected_ids:
        raise ValueError("至少需要一个设备参与能耗仿真")
    unknown_ids = [device_id for device_id in selected_ids if device_id not in DEVICES]
    if unknown_ids:
        raise KeyError(f"未知设备编号: {', '.join(unknown_ids)}")

    points_per_day = 24 * 60 // SIMULATION_STEP_MINUTES
    day_start = datetime.combine(day, time.min)
    device_energy: dict[str, float] = {}
    zone_energy: defaultdict[str, float] = defaultdict(float)
    planning_area_energy: defaultdict[str, float] = defaultdict(float)

    for device_id in selected_ids:
        device = DEVICES[device_id]
        zone_id = device["zone_id"]
        reset_state(zone_id)
        energy_kwh = 0.0
        for index in range(points_per_day):
            timestamp = day_start + timedelta(minutes=index * SIMULATION_STEP_MINUTES)
            lux = get_lux(zone_id, timestamp)
            occupancy = get_occupancy(zone_id, timestamp)
            brightness = auto_control(zone_id, lux, occupancy, timestamp)
            power_w = float(device["rated_power_w"]) * brightness / 100
            energy_kwh += calculate_energy(power_w)

        rounded_energy = round(energy_kwh, 6)
        device_energy[device_id] = rounded_energy
        zone_energy[zone_id] += rounded_energy
        planning_area_energy[device["planning_area_id"]] += rounded_energy

    return {
        "simulation_date": day.isoformat(),
        "sample_count": points_per_day * len(selected_ids),
        "device_energy_kwh": device_energy,
        "zone_energy_kwh": {key: round(value, 6) for key, value in zone_energy.items()},
        "planning_area_energy_kwh": {
            key: round(value, 6) for key, value in planning_area_energy.items()
        },
        "total_energy_kwh": round(sum(device_energy.values()), 6),
    }


def compare_simulated_daily_energy(
    simulation_day: date | datetime,
    device_ids: Iterable[str] | None = None,
) -> dict:
    """Compare representative smart simulation with the configured baseline."""
    selected_ids = list(DEVICES) if device_ids is None else list(device_ids)
    smart_result = simulate_smart_daily_energy(simulation_day, selected_ids)
    selected_devices = {device_id: DEVICES[device_id] for device_id in selected_ids}
    traditional = calculate_traditional_daily_energy(selected_devices)
    smart = smart_result["total_energy_kwh"]
    return {
        **smart_result,
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
    "compare_simulated_daily_energy",
    "simulate_smart_daily_energy",
]
