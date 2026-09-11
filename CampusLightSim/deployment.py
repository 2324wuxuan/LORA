"""Expand the lighting inventory into independent control circuits and zones."""
from copy import deepcopy
from math import ceil, cos, sin, pi
from planning import estimate_lighting_plan

# Room/floor positions are design coordinates, not surveyed building geometry.
AREA_ANCHORS = {"PA01": (270, 410), "PA02": (150, 500), "PA03": (245, 220),
                "PA04": (380, 160), "PA05": (100, 570), "PA06": (350, 260),
                "PA07": (250, 35), "PA08": (95, 645)}
LEGACY_FIRST = {"MAIN-ROOM": "CL-N01", "MAIN-CORRIDOR": "CL-N02", "MAIN-ROAD": "CL-N03",
                "TEACH-ROOM": "CL-N04", "LIB-READ": "CL-N05", "SPORT-FIELD": "CL-N06",
                "DORM-CORRIDOR": "CL-N07", "RESEARCH-ROOM": "CL-N08",
                "ROAD-NS": "CL-N09", "PUBLIC-ROAD": "CL-N10"}


def template_for(row):
    key = row["item_id"]
    if row["kind"] == "road" or key in {"GATE", "PARKING"}:
        return {"PA01": "CL-N03", "PA08": "CL-N10"}.get(row["area_id"], "CL-N09")
    if any(part in key for part in ("CORRIDOR", "STAIR", "ENTRY", "COMMON")) or key == "HOSPITAL":
        return "CL-N07" if row["area_id"] == "PA05" else "CL-N02"
    return {"PA01": "CL-N01", "PA02": "CL-N04", "PA03": "CL-N05", "PA04": "CL-N06",
            "PA05": "CL-N08", "PA06": "CL-N08", "PA08": "CL-N05"}[row["area_id"]]


def fixture_power(row):
    if row["kind"] == "road" or row["item_id"] in {"GATE", "PARKING"}:
        return 120.0
    if row["area_id"] == "PA04":
        return 200.0 if row["item_id"] == "SPORT-FIELD" else 100.0
    if any(k in row["item_id"] for k in ("CORRIDOR", "STAIR", "ENTRY", "COMMON")) or row["item_id"] == "HOSPITAL":
        return 18.0
    return 36.0


def position(row, index):
    ax, ay = AREA_ANCHORS[row["area_id"]]
    if row["kind"] == "road":
        per_route = ceil(row["length_m"] / row["spacing_m"]) + (not row["closed"])
        route, pole = divmod(index, per_route)
        fraction = pole / max(1, per_route - (0 if row["closed"] else 1))
        if row["item_id"] == "ROAD-NS":
            return 200.0 + route * 120, 40.0 + fraction * 650, 6.0
        if row["item_id"] == "ROAD-EW":
            return 40.0 + fraction * 400, 160.0 + route * 220, 6.0
        # Dedicated paths occupy their own area; lengths are inventory estimates,
        # so this schematic does not claim a metrically surveyed route.
        return ax + 32 * cos(2*pi*fraction), ay + 40 * sin(2*pi*fraction), 6.0
    per_building = row["floors"] * row["sections_per_floor"]
    building, within = divmod(index, per_building)
    floor, section = divmod(within, row["sections_per_floor"])
    x = ax + (building % 4) * 25 + (section % 5) * 4 - 12
    y = ay + (building // 4) * 25 + (section // 5) * 6 - 10
    return min(490., x), min(740., y), float(3 * (floor + 1))


def expand_deployment(templates, zone_templates, rule_templates, environment, areas):
    devices, zones, rules = {}, {}, {}
    lux_factors, schedules = {}, {}
    for area in areas.values():
        area["linked_zone_ids"] = []
        area["simulation_nodes"] = 0
    for row in estimate_lighting_plan()["rows"]:
        template_id = template_for(row)
        prototype = templates[template_id]
        template_zone = prototype["zone_id"]
        for index in range(row["control_nodes"]):
            device_id = LEGACY_FIRST.get(row["item_id"]) if index == 0 else None
            device_id = device_id or f"CL-{row['item_id']}-{index+1:04d}"
            zone_id = templates[device_id]["zone_id"] if device_id in templates else f"Z-{device_id[3:]}"
            if row["kind"] == "building":
                per_building = row["floors"] * row["sections_per_floor"]
                building, within = divmod(index, per_building)
                floor, section = divmod(within, row["sections_per_floor"])
                label = f"{row['name']} · {building+1}栋{floor+1}层{section+1:02d}号"
            else:
                building, floor, section = 0, 0, index
                label = f"{row['name']} · {index+1:03d}号灯杆"
            x, y, height = position(row, index)
            # Preserve the ten historical IDs as the first real circuits, not
            # ten extra representative devices. Existing operations remain addressable.
            if device_id in templates:
                x, y, height = (templates[device_id][key] for key in ("x", "y", "height"))
            device = {**deepcopy(prototype), "device_name": label, "zone_id": zone_id,
                      "planning_area_id": row["area_id"], "plan_item_id": row["item_id"],
                      "building_number": building+1, "floor": floor+1, "section": section+1,
                      "fixture_count": row["fixtures_per_node"], "fixture_power_w": fixture_power(row),
                      "rated_power_w": row["fixtures_per_node"] * fixture_power(row),
                      "x": float(x), "y": float(y), "height": float(height),
                      "lamp_id": f"CIRCUIT-{device_id}", "light_sensor_id": f"LS-{device_id}",
                      "presence_sensor_id": f"PS-{device_id}"}
            devices[device_id] = device
            zones[zone_id] = {**deepcopy(zone_templates[template_zone]), "name": label,
                              "location": label, "planning_area_id": row["area_id"],
                              "template_zone_id": template_zone, "device_id": device_id}
            rules[zone_id] = {**deepcopy(rule_templates[template_zone]), "zone_name": label}
            lux_factors[zone_id] = environment["zone_lux_factors"][template_zone]
            schedules[zone_id] = deepcopy(environment["occupancy_probability_schedules"][template_zone])
            areas[row["area_id"]]["linked_zone_ids"].append(zone_id)
            areas[row["area_id"]]["simulation_nodes"] += 1
    # Keep familiar examples first in searchable selectors while preserving all circuits.
    devices = dict(sorted(devices.items(), key=lambda pair: (pair[0] not in templates, pair[0])))
    zones = {device["zone_id"]: zones[device["zone_id"]] for device in devices.values()}
    environment["zone_lux_factors"] = lux_factors
    environment["occupancy_probability_schedules"] = schedules
    return devices, zones, rules
