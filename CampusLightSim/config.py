"""CampusLightSim unified configuration.

Research area: Beijing University of Posts and Telecommunications (BUPT),
Main Building and nearby campus lighting facilities.

The values below are simulation/design parameters unless explicitly replaced
by field measurements. Keep these IDs consistent with the project document:
Z01/Z02/Z03, CL-N01/02/03, GW-01.
"""
from pathlib import Path

PROJECT_NAME = "CampusLightSim"
PROJECT_TITLE = "北邮本部主楼智能照明 LoRa 云运维仿真平台"
SCHOOL_NAME = "北京邮电大学"
CAMPUS_NAME = "本部校区"
RESEARCH_AREA = "本部主楼及主楼附近照明设施"

SIMULATION_STEP_MINUTES = 5
SIMULATION_POINTS_PER_DAY = 24 * 60 // SIMULATION_STEP_MINUTES
RANDOM_SEED = 20260908

ZONES = {
    "Z01": {
        "name": "主楼典型教室",
        "short_name": "Classroom",
        "location": "北邮本部主楼典型教室区域",
        "scene": "indoor_classroom",
        "control_mode": "LIGHT_OCCUPANCY",
        "description": "人员集中、自然光变化明显，采用光照+人员联合控制。",
    },
    "Z02": {
        "name": "主楼一层公共走廊",
        "short_name": "Corridor",
        "location": "北邮本部主楼一层公共走廊",
        "scene": "indoor_corridor",
        "control_mode": "OCCUPANCY",
        "description": "人员流动明显，无人时维持低亮度基础照明。",
    },
    "Z03": {
        "name": "主楼附近道路",
        "short_name": "Road",
        "location": "北邮本部主楼附近校园道路",
        "scene": "outdoor_road",
        "control_mode": "TIME_LIGHT_OCCUPANCY",
        "description": "夜间路灯采用时间+光照+人员控制。",
    },
}

DEVICES = {
    "CL-N01": {
        "device_name": "主楼教室照明控制节点",
        "zone_id": "Z01", "lamp_id": "LAMP-01",
        "light_sensor_id": "LS-01", "presence_sensor_id": "PS-01",
        "rated_power_w": 80.0,
        "distance_to_gateway_m": 60.0,
        "environment": "indoor", "obstacle": "light_indoor",
        "lora_sf": 7, "lora_tx_power_dbm": 14,
        "primary_network": "LoRaWAN", "backup_network": None,
        "initial_status": "ONLINE", "initial_mode": "AUTO", "initial_brightness": 0,
    },
    "CL-N02": {
        "device_name": "主楼走廊照明控制节点",
        "zone_id": "Z02", "lamp_id": "LAMP-02",
        "light_sensor_id": "LS-02", "presence_sensor_id": "PS-02",
        "rated_power_w": 50.0,
        "distance_to_gateway_m": 120.0,
        "environment": "indoor", "obstacle": "indoor_wall",
        "lora_sf": 9, "lora_tx_power_dbm": 14,
        "primary_network": "LoRaWAN", "backup_network": None,
        "initial_status": "ONLINE", "initial_mode": "AUTO", "initial_brightness": 20,
    },
    "CL-N03": {
        "device_name": "主楼附近道路路灯控制节点",
        "zone_id": "Z03", "lamp_id": "LAMP-03",
        "light_sensor_id": "LS-03", "presence_sensor_id": "PS-03",
        "rated_power_w": 120.0,
        "distance_to_gateway_m": 350.0,
        "environment": "outdoor", "obstacle": "outdoor_open",
        "lora_sf": 12, "lora_tx_power_dbm": 14,
        "primary_network": "LoRaWAN", "backup_network": "NB-IoT",
        "initial_status": "ONLINE", "initial_mode": "AUTO", "initial_brightness": 40,
    },
}

GATEWAYS = {
    "GW-01": {
        "name": "主楼 LoRaWAN 虚拟网关",
        "location": "北邮本部主楼附近中心位置（仿真部署点）",
        "status": "ONLINE",
        "frequency_band": "CN470",
        "tx_power_dbm": 14,
        "antenna_gain_dbi": 2.15,
        "reference_distance_m": 1.0,
        "path_loss_exponent_indoor": 3.0,
        "path_loss_exponent_outdoor": 2.7,
        "reference_path_loss_db": 40.0,
        "default_shadowing_std_db": 4.0,
        "max_devices": 200,
    }
}
DEFAULT_GATEWAY_ID = "GW-01"

LIGHTING_RULES = {
    "Z01": {
        "zone_name": "主楼典型教室",
        "lux_on_threshold": 450.0,
        "lux_off_threshold": 550.0,
        "occupied_brightness": 100,
        "unoccupied_brightness": 0,
        "control_features": ["ambient_light", "occupancy"],
    },
    "Z02": {
        "zone_name": "主楼一层公共走廊",
        "occupied_brightness": 100,
        "unoccupied_brightness": 20,
        "control_features": ["occupancy"],
    },
    "Z03": {
        "zone_name": "主楼附近道路",
        "day_brightness": 0,
        "night_unoccupied_brightness": 40,
        "night_occupied_brightness": 100,
        "day_lux_threshold": 50.0,
        "control_features": ["time", "ambient_light", "occupancy"],
    },
}

ENVIRONMENT = {
    "lux_profile": {0: 5, 6: 50, 8: 200, 10: 450, 12: 650, 14: 580, 17: 250, 19: 30, 23: 5},
    "lux_random_variation_ratio": 0.05,
    # The profile above represents unobstructed outdoor daylight.  These
    # factors model the amount of daylight that reaches each scene.
    "zone_lux_factors": {
        "Z01": 0.72,  # classroom windows and indoor attenuation
        "Z02": 0.86,  # corridor receives indirect daylight
        "Z03": 1.00,  # outdoor road
    },
    # Occupancy is sampled once per interval so a sensor does not flicker on
    # every call.  Each tuple is (start_hour, end_hour, probability).
    "occupancy_sample_interval_minutes": 15,
    "occupancy_probability_schedules": {
        "Z01": [
            (0, 7, 0.01), (7, 8, 0.20), (8, 12, 0.90),
            (12, 14, 0.25), (14, 18, 0.90), (18, 22, 0.20),
            (22, 24, 0.01),
        ],
        "Z02": [
            (0, 6, 0.01), (6, 8, 0.25), (8, 9, 0.85),
            (9, 10, 0.12), (10, 11, 0.80), (11, 12, 0.15),
            (12, 14, 0.55), (14, 15, 0.80), (15, 16, 0.15),
            (16, 17, 0.80), (17, 18, 0.35), (18, 22, 0.15),
            (22, 24, 0.02),
        ],
        "Z03": [
            (0, 6, 0.02), (6, 8, 0.65), (8, 12, 0.25),
            (12, 14, 0.60), (14, 17, 0.25), (17, 18, 0.55),
            (18, 22, 0.85), (22, 24, 0.20),
        ],
    },
    "occupancy": {
        "Z01": {"morning_start": 8, "morning_end": 12, "afternoon_start": 14, "afternoon_end": 18, "night_start": 22},
        "Z02": {"peak_hours": [(8, 9), (10, 11), (14, 15), (16, 17)]},
        "Z03": {"high_traffic_start": 18, "high_traffic_end": 22, "low_traffic_start": 0, "low_traffic_end": 6},
    },
}

LORA = {
    "enabled": True,
    "network_type": "LoRaWAN",
    "frequency_mhz": 470.0,
    "bandwidth_khz": 125,
    "coding_rate": "4/5",
    "sensitivity_dbm_by_sf": {7: -123, 8: -126, 9: -129, 10: -132, 11: -134, 12: -137},
    "obstacle_loss_db": {"light_indoor": 8.0, "indoor_wall": 15.0, "outdoor_open": 2.0},
    "base_packet_loss_probability": 0.01,
    "additional_loss_threshold_db": 8.0,
    "base_delay_ms": 100,
    "delay_per_sf_ms": 30,
    "rssi_min_dbm": -130,
    "rssi_max_dbm": -40,
    "snr_mean_db": 5.0,
    "snr_std_db": 2.5,
}

NBIOT = {
    "enabled": True,
    "role": "supplementary",
    "description": "NB-IoT仅作为少量独立/边缘路灯的补充通信方式，不改变LoRaWAN主网络定位。",
    "default_rsrp_dbm": -95,
    "default_sinr_db": 10.0,
    "default_delay_ms": 800,
    "devices": ["CL-N03"],
}

TELEMETRY = {
    "upload_interval_minutes": SIMULATION_STEP_MINUTES,
    "offline_after_failed_uploads": 5,
    "fields": ["timestamp", "device_id", "lux", "occupancy", "brightness", "power", "rssi", "snr", "packet_success"],
}

FAULTS = {
    "node_offline": {"enabled": True, "severity": "CRITICAL"},
    "low_rssi": {"enabled": True, "threshold_dbm": -110, "severity": "WARNING"},
    "very_low_rssi": {"enabled": True, "threshold_dbm": -120, "severity": "CRITICAL"},
    "low_pdr": {"enabled": True, "threshold": 0.80, "severity": "WARNING"},
    "sensor_abnormal": {"enabled": True, "lux_min": 0, "lux_max": 10000, "severity": "WARNING"},
    "gateway_offline": {"enabled": True, "severity": "CRITICAL"},
}

BASE_DIR = Path(__file__).resolve().parent
DATABASE_DIR = BASE_DIR / "database"
DATABASE_PATH = DATABASE_DIR / "campus.db"
DATA_DIR = BASE_DIR / "data"
SIMULATION_CSV = DATA_DIR / "simulation.csv"
TEST_RESULTS_CSV = DATA_DIR / "test_results.csv"

SYSTEM = {
    "default_mode": "AUTO",
    "available_modes": ["AUTO", "MANUAL"],
    "brightness_min": 0,
    "brightness_max": 100,
    "supported_alarm_levels": ["INFO", "WARNING", "CRITICAL"],
    "date_format": "%Y-%m-%d",
    "datetime_format": "%Y-%m-%d %H:%M:%S",
}

ENERGY = {
    "traditional_brightness": 100,
    "traditional_start_hour": 7,
    "traditional_end_hour": 22,
    "unit": "kWh",
    "formula": "E = P_rated × brightness × Δt / 1000",
    "compare_modes": ["TRADITIONAL", "SMART"],
}


def get_zone(zone_id: str) -> dict:
    if zone_id not in ZONES:
        raise KeyError(f"未知区域编号: {zone_id}")
    return ZONES[zone_id]


def get_device(device_id: str) -> dict:
    if device_id not in DEVICES:
        raise KeyError(f"未知设备编号: {device_id}")
    return DEVICES[device_id]


def get_gateway(gateway_id: str = DEFAULT_GATEWAY_ID) -> dict:
    if gateway_id not in GATEWAYS:
        raise KeyError(f"未知网关编号: {gateway_id}")
    return GATEWAYS[gateway_id]


def get_lighting_rule(zone_id: str) -> dict:
    if zone_id not in LIGHTING_RULES:
        raise KeyError(f"区域没有配置照明策略: {zone_id}")
    return LIGHTING_RULES[zone_id]


def get_all_device_ids() -> list[str]:
    return list(DEVICES.keys())


def get_lora_device_ids() -> list[str]:
    return [k for k, v in DEVICES.items() if v["primary_network"] == "LoRaWAN"]


def get_nbiot_device_ids() -> list[str]:
    return [k for k, v in DEVICES.items() if v.get("backup_network") == "NB-IoT"]


def validate_config() -> tuple[bool, list[str]]:
    errors = []
    for device_id, device in DEVICES.items():
        if device.get("zone_id") not in ZONES:
            errors.append(f"{device_id}: zone_id不存在")
        if device.get("rated_power_w", 0) <= 0:
            errors.append(f"{device_id}: rated_power_w必须大于0")
        if device.get("lora_sf") not in range(7, 13):
            errors.append(f"{device_id}: LoRa SF必须为7~12")
        if device.get("distance_to_gateway_m", 0) <= 0:
            errors.append(f"{device_id}: distance_to_gateway_m必须大于0")
    if DEFAULT_GATEWAY_ID not in GATEWAYS:
        errors.append(f"默认网关{DEFAULT_GATEWAY_ID}不存在")

    lux_profile = ENVIRONMENT.get("lux_profile", {})
    if not lux_profile or 0 not in lux_profile:
        errors.append("环境光照曲线必须包含0时锚点")
    if any(float(lux) < 0 for lux in lux_profile.values()):
        errors.append("环境光照值不能小于0")

    lux_factors = ENVIRONMENT.get("zone_lux_factors", {})
    occupancy_schedules = ENVIRONMENT.get("occupancy_probability_schedules", {})
    for zone_id in ZONES:
        if float(lux_factors.get(zone_id, 0)) <= 0:
            errors.append(f"{zone_id}: zone_lux_factor必须大于0")
        schedule = occupancy_schedules.get(zone_id, [])
        cursor = 0.0
        for start_hour, end_hour, probability in schedule:
            if float(start_hour) != cursor or float(end_hour) <= float(start_hour):
                errors.append(f"{zone_id}: 人员活动时段必须连续覆盖全天")
                break
            if not 0 <= float(probability) <= 1:
                errors.append(f"{zone_id}: 人员概率必须在0~1之间")
                break
            cursor = float(end_hour)
        if cursor != 24.0:
            errors.append(f"{zone_id}: 人员活动时段必须覆盖到24时")

    if int(ENVIRONMENT.get("occupancy_sample_interval_minutes", 0)) <= 0:
        errors.append("人员传感器采样间隔必须大于0")
    return len(errors) == 0, errors


if __name__ == "__main__":
    ok, errors = validate_config()
    print(PROJECT_TITLE)
    print("配置检查：", "PASS" if ok else "FAIL")
    for error in errors:
        print("-", error)
    print("区域数量：", len(ZONES))
    print("照明节点：", len(DEVICES))
    print("LoRaWAN节点：", len(get_lora_device_ids()))
    print("NB-IoT补充节点：", len(get_nbiot_device_ids()))
    print("每日仿真点数：", SIMULATION_POINTS_PER_DAY)
