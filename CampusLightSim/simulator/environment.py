"""CampusLightSim campus environment and virtual sensor simulation.

This module is deliberately limited to ambient illuminance and occupancy.  It
does not make lighting-control decisions or access the database.  All design
parameters live in :mod:`config`, making later replacement with field
measurements possible without changing the simulation code.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta
from numbers import Real
from typing import Iterator

from config import ENVIRONMENT, RANDOM_SEED, SIMULATION_STEP_MINUTES, ZONES


TimestampLike = datetime | time | str | int | float


def _resolve_zone_id(zone: str) -> str:
    """Return the canonical zone ID for an ID, name, scene, or short name."""
    if not isinstance(zone, str) or not zone.strip():
        raise ValueError("区域必须是非空字符串")
    if zone in ZONES:
        return zone

    candidate = zone.strip().casefold()
    for zone_id, zone_config in ZONES.items():
        aliases = {
            zone_id.casefold(),
            str(zone_config.get("name", "")).casefold(),
            str(zone_config.get("short_name", "")).casefold(),
            str(zone_config.get("scene", "")).casefold(),
        }
        if candidate in aliases:
            return zone_id
    raise KeyError(f"未知区域: {zone}")


def _coerce_timestamp(value: TimestampLike) -> datetime:
    """Normalize supported time representations to a datetime.

    Numeric values are interpreted as decimal hours, while strings accept
    ``HH:MM``, ``HH:MM:SS`` or an ISO datetime.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, time):
        return datetime.combine(date(2000, 1, 1), value)
    if isinstance(value, Real) and not isinstance(value, bool):
        hour = float(value)
        if not 0 <= hour < 24:
            raise ValueError("小时必须在 [0, 24) 范围内")
        return datetime(2000, 1, 1) + timedelta(hours=hour)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("时间字符串不能为空")
        try:
            if "T" in text or " " in text:
                return datetime.fromisoformat(text)
            return datetime.combine(date(2000, 1, 1), time.fromisoformat(text))
        except ValueError as exc:
            raise ValueError(f"无法解析时间: {value}") from exc
    raise TypeError("时间必须是 datetime、time、HH:MM 字符串或 0~24 的数字")


def _decimal_hour(timestamp: datetime) -> float:
    return (
        timestamp.hour
        + timestamp.minute / 60
        + timestamp.second / 3600
        + timestamp.microsecond / 3_600_000_000
    )


def _interpolate_lux(hour: float) -> float:
    """Piecewise-linear interpolation of the configured 24-hour profile."""
    profile = sorted((float(h), float(lux)) for h, lux in ENVIRONMENT["lux_profile"].items())
    if not profile:
        raise ValueError("ENVIRONMENT.lux_profile 不能为空")

    points = profile + [(24.0, profile[0][1])]
    for (left_hour, left_lux), (right_hour, right_lux) in zip(points, points[1:]):
        if left_hour <= hour <= right_hour:
            width = right_hour - left_hour
            if width == 0:
                return left_lux
            ratio = (hour - left_hour) / width
            return left_lux + (right_lux - left_lux) * ratio

    # A profile is expected to begin at midnight.  This fallback supports a
    # later first anchor by interpolating cyclically from the previous day.
    last_hour, last_lux = profile[-1]
    first_hour, first_lux = profile[0]
    wrapped_hour = hour + 24 if hour < first_hour else hour
    ratio = (wrapped_hour - last_hour) / (first_hour + 24 - last_hour)
    return last_lux + (first_lux - last_lux) * ratio


def _stable_unit_value(
    zone_id: str,
    timestamp: datetime,
    channel: str,
    interval_minutes: int,
) -> float:
    """Create a repeatable pseudo-random value in [0, 1) for a sensor slot."""
    if interval_minutes <= 0:
        raise ValueError("采样间隔必须大于 0")
    minute_of_day = timestamp.hour * 60 + timestamp.minute
    slot = minute_of_day // interval_minutes
    key = f"{RANDOM_SEED}|{timestamp.date().isoformat()}|{zone_id}|{channel}|{slot}"
    digest = hashlib.blake2b(key.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") / 2**64


def get_lux(zone_id: str, timestamp: TimestampLike) -> float:
    """Simulate ambient illuminance in lux for a campus zone.

    The configured daylight curve is linearly interpolated, attenuated for the
    scene, and varied by a small deterministic sensor/weather disturbance.
    Repeating the same query therefore returns the same value.
    """
    canonical_zone_id = _resolve_zone_id(zone_id)
    normalized_time = _coerce_timestamp(timestamp)
    factors = ENVIRONMENT["zone_lux_factors"]
    if canonical_zone_id not in factors:
        raise KeyError(f"区域缺少光照系数: {canonical_zone_id}")

    base_lux = _interpolate_lux(_decimal_hour(normalized_time))
    variation_ratio = float(ENVIRONMENT["lux_random_variation_ratio"])
    unit_value = _stable_unit_value(
        canonical_zone_id,
        normalized_time,
        "lux",
        SIMULATION_STEP_MINUTES,
    )
    variation = (unit_value * 2 - 1) * variation_ratio
    lux = base_lux * float(factors[canonical_zone_id]) * (1 + variation)
    return round(max(0.0, lux), 1)


def get_occupancy_probability(zone_id: str, timestamp: TimestampLike) -> float:
    """Return the configured probability that a zone is occupied."""
    canonical_zone_id = _resolve_zone_id(zone_id)
    normalized_time = _coerce_timestamp(timestamp)
    hour = _decimal_hour(normalized_time)
    schedules = ENVIRONMENT["occupancy_probability_schedules"]
    if canonical_zone_id not in schedules:
        raise KeyError(f"区域缺少人员活动时段: {canonical_zone_id}")

    for start_hour, end_hour, probability in schedules[canonical_zone_id]:
        if float(start_hour) <= hour < float(end_hour):
            probability = float(probability)
            if not 0 <= probability <= 1:
                raise ValueError(f"{canonical_zone_id} 的人员概率必须在 [0, 1] 范围内")
            return probability
    raise ValueError(f"{canonical_zone_id} 的人员活动配置未覆盖 {hour:.2f} 时")


def get_occupancy(zone_id: str, timestamp: TimestampLike) -> bool:
    """Simulate the occupancy sensor according to campus activity patterns."""
    canonical_zone_id = _resolve_zone_id(zone_id)
    normalized_time = _coerce_timestamp(timestamp)
    probability = get_occupancy_probability(canonical_zone_id, normalized_time)
    sample_interval = int(ENVIRONMENT["occupancy_sample_interval_minutes"])
    return _stable_unit_value(
        canonical_zone_id,
        normalized_time,
        "occupancy",
        sample_interval,
    ) < probability


def get_environment(zone_id: str, timestamp: TimestampLike) -> dict:
    """Return one environment sample using the project's V1 data contract."""
    canonical_zone_id = _resolve_zone_id(zone_id)
    normalized_time = _coerce_timestamp(timestamp)
    return {
        "timestamp": normalized_time,
        "zone_id": canonical_zone_id,
        "lux": get_lux(canonical_zone_id, normalized_time),
        "occupancy": get_occupancy(canonical_zone_id, normalized_time),
    }


def generate_environment_series(
    zone_id: str,
    start_time: datetime,
    hours: float = 24,
    step_minutes: int = SIMULATION_STEP_MINUTES,
) -> Iterator[dict]:
    """Yield environment samples over a period for pages and the engine."""
    if not isinstance(start_time, datetime):
        raise TypeError("start_time 必须是 datetime")
    if hours < 0:
        raise ValueError("hours 不能小于 0")
    if step_minutes <= 0:
        raise ValueError("step_minutes 必须大于 0")

    canonical_zone_id = _resolve_zone_id(zone_id)
    steps = int(hours * 60 // step_minutes)
    for index in range(steps):
        yield get_environment(
            canonical_zone_id,
            start_time + timedelta(minutes=index * step_minutes),
        )


__all__ = [
    "generate_environment_series",
    "get_environment",
    "get_lux",
    "get_occupancy",
    "get_occupancy_probability",
]


if __name__ == "__main__":
    sample_time = datetime(2026, 9, 9, 10, 0)
    for sample_zone_id in ZONES:
        print(get_environment(sample_zone_id, sample_time))
