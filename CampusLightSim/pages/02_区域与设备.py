"""Streamlit page for campus-zone planning and virtual environment sensors."""

from datetime import datetime, time, timedelta
from html import escape

import streamlit as st

from analysis.energy import (
    calculate_saving_rate,
    calculate_traditional_daily_energy,
    simulate_smart_daily_energy,
)
from config import (
    BASE_DIR,
    CAMPUS_NAME,
    CAMPUS_MAP,
    CAMPUS_PLANNING_AREAS,
    DEFAULT_GATEWAY_ID,
    DEVICES,
    GATEWAYS,
    LIGHTING_RULES,
    RESEARCH_AREA,
    SCHOOL_NAME,
    SIMULATION_STEP_MINUTES,
    ZONES,
)
from simulator.environment import get_environment, get_lux, get_occupancy_probability


def _markdown_table(rows: list[dict]) -> str:
    """Render small planning tables without adding a dataframe dependency."""
    if not rows:
        return "_暂无数据_"
    headers = list(rows[0])
    header = "| " + " | ".join(headers) + " |"
    divider = "| " + " | ".join("---" for _ in headers) + " |"
    body = [
        "| "
        + " | ".join(str(row.get(column, "")).replace("|", "\\|") for column in headers)
        + " |"
        for row in rows
    ]
    return "\n".join([header, divider, *body])


def _lux_chart_svg(series: dict[str, list[float]]) -> str:
    """Build an inline, dependency-free SVG for the 24-hour light curves."""
    width, height = 960, 330
    left, right, top, bottom = 62, 24, 28, 54
    plot_width = width - left - right
    plot_height = height - top - bottom
    maximum = max(max(values) for values in series.values())
    maximum = max(100.0, ((maximum + 99) // 100) * 100)
    colors = ["#2563eb", "#f59e0b", "#16a34a"]

    def point(index: int, value: float) -> str:
        x = left + index / 47 * plot_width
        y = top + (1 - value / maximum) * plot_height
        return f"{x:.1f},{y:.1f}"

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="所选片区24小时自然光照度曲线" '
        'style="width:100%;height:auto;background:var(--secondary-background-color);border-radius:8px">'
    ]
    for tick in range(5):
        value = maximum * tick / 4
        y = top + plot_height - tick / 4 * plot_height
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" '
            'stroke="currentColor" opacity="0.12" />'
        )
        parts.append(
            f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" font-size="12" '
            f'fill="currentColor" opacity="0.72">{value:.0f}</text>'
        )
    for hour in (0, 6, 12, 18, 24):
        x = left + hour / 24 * plot_width
        parts.append(
            f'<text x="{x:.1f}" y="{height-24}" text-anchor="middle" font-size="12" '
            f'fill="currentColor" opacity="0.72">{hour:02d}:00</text>'
        )
    for (label, values), color in zip(series.items(), colors):
        points = " ".join(point(index, value) for index, value in enumerate(values))
        parts.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" '
            'stroke-width="3" stroke-linejoin="round" stroke-linecap="round" />'
        )
    legend_x = left
    for (label, _), color in zip(series.items(), colors):
        parts.append(f'<circle cx="{legend_x}" cy="16" r="5" fill="{color}" />')
        parts.append(
            f'<text x="{legend_x+10}" y="20" font-size="12" fill="currentColor">'
            f'{escape(label)}</text>'
        )
        legend_x += 190
    parts.append(
        f'<text x="16" y="{top + plot_height/2:.1f}" text-anchor="middle" font-size="12" '
        'fill="currentColor" transform="rotate(-90 16 150)">照度 (lux)</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


st.title("🏫 区域与设备规划")
st.caption(f"研究范围：{SCHOOL_NAME}{CAMPUS_NAME} · {RESEARCH_AREA}")
st.info(
    "规划已由主楼试点扩展到本部校区教学、科研、生活、体育和道路区域。"
    "二、三期每个片区现已接入一个代表仿真节点；所有新增参数均明确标为“仿真估算”，"
    "用于先行运行 Lux、Occupancy、智能照明和能耗仿真，不代表现场实测或最终施工配置。"
)


st.subheader("校园总体规划地图")
planned_nodes = sum(area["recommended_nodes"] for area in CAMPUS_PLANNING_AREAS.values())
simulation_nodes = sum(area["simulation_nodes"] for area in CAMPUS_PLANNING_AREAS.values())
plan_col, zone_col, simulation_col, node_total_col = st.columns(4)
plan_col.metric("校园规划片区", len(CAMPUS_PLANNING_AREAS))
zone_col.metric("代表仿真区域", len(ZONES))
simulation_col.metric("代表仿真节点", simulation_nodes)
node_total_col.metric("建议部署节点", planned_nodes)

map_path = BASE_DIR / CAMPUS_MAP["asset_path"]
if map_path.exists():
    st.image(
        str(map_path),
        caption=CAMPUS_MAP["caption"],
    )
else:
    st.warning(f"未找到校园地图资源：{map_path}")

planning_rows = []
for area_id, area in CAMPUS_PLANNING_AREAS.items():
    planning_rows.append(
        {
            "片区": f"{area_id} {area['name']}",
            "地图地标": "、".join(area["landmarks"]),
            "阶段": area["phase"],
            "优先级": area["priority"],
            "状态": area["status"],
            "参数性质": "仿真估算" if "仿真估算" in area["parameter_source"] else "一期仿真设计",
            "代表节点": area["simulation_nodes"],
            "建议节点": area["recommended_nodes"],
        }
    )
st.markdown(_markdown_table(planning_rows))

selected_area_id = st.selectbox(
    "查看片区规划详情",
    options=list(CAMPUS_PLANNING_AREAS),
    format_func=lambda item: f"{item} · {CAMPUS_PLANNING_AREAS[item]['name']}",
)
selected_area = CAMPUS_PLANNING_AREAS[selected_area_id]
area_left, area_right = st.columns(2)
with area_left:
    st.markdown(f"**覆盖地标：** {'、'.join(selected_area['landmarks'])}")
    st.markdown(f"**照明范围：** {selected_area['lighting_scope']}")
    st.markdown(f"**控制策略：** {selected_area['control_strategy']}")
with area_right:
    st.markdown(f"**网关规划：** {selected_area['gateway_plan']}")
    st.markdown(f"**勘测重点：** {selected_area['survey_notes']}")
    linked_zones = selected_area["linked_zone_ids"]
    st.markdown(f"**已关联仿真区：** {', '.join(linked_zones)}")
    st.markdown(f"**参数来源：** {selected_area['parameter_source']}")


st.divider()
st.subheader("全校代表仿真区域")

zone_rows = []
for zone_id, zone in ZONES.items():
    device_id, device = next(
        (item for item in DEVICES.items() if item[1]["zone_id"] == zone_id),
        ("—", {}),
    )
    zone_rows.append(
        {
            "区域": f"{zone_id} {zone['name']}",
            "照明节点": device_id,
            "场景": zone["short_name"],
            "额定功率": f"{device.get('rated_power_w', 0):g} W",
            "网关距离": f"{device.get('distance_to_gateway_m', 0):g} m",
            "LoRa SF": device.get("lora_sf", "—"),
            "控制方式": zone["control_mode"],
            "参数性质": "仿真估算" if "仿真估算" in zone["parameter_source"] else "一期设计",
        }
    )

st.markdown(_markdown_table(zone_rows))

gateway = GATEWAYS[DEFAULT_GATEWAY_ID]
gateway_col, node_col, step_col = st.columns(3)
gateway_col.metric("虚拟网关", DEFAULT_GATEWAY_ID)
node_col.metric("照明控制节点", len(DEVICES))
step_col.metric("环境采样步长", f"{SIMULATION_STEP_MINUTES} 分钟")
st.caption(f"{gateway['name']} · 部署位置：{gateway['location']}")


st.divider()
st.subheader("虚拟环境传感器")

input_col, detail_col = st.columns([1, 2])
with input_col:
    selected_zone_id = st.selectbox(
        "选择区域",
        options=list(ZONES),
        format_func=lambda item: f"{item} · {ZONES[item]['name']}",
    )
    selected_date = st.date_input("模拟日期", value=datetime.now().date())
    selected_time = st.time_input(
        "模拟时间",
        value=time(10, 0),
        step=timedelta(minutes=SIMULATION_STEP_MINUTES),
    )
    selected_timestamp = datetime.combine(selected_date, selected_time)
    sample = get_environment(selected_zone_id, selected_timestamp)
    occupancy_probability = get_occupancy_probability(selected_zone_id, selected_timestamp)

with detail_col:
    zone = ZONES[selected_zone_id]
    rule = LIGHTING_RULES[selected_zone_id]
    lux_col, occupancy_col, probability_col = st.columns(3)
    lux_col.metric("环境照度", f"{sample['lux']:.1f} lux")
    occupancy_col.metric("人员传感器", "有人" if sample["occupancy"] else "无人")
    probability_col.metric("时段人员概率", f"{occupancy_probability:.0%}")
    st.markdown(f"**环境特点：** {zone['description']}")
    st.markdown(f"**控制依据：** {' + '.join(rule['control_features'])}")
    st.markdown(f"**参数来源：** {zone['parameter_source']}")
    st.caption(
        "人员状态由配置中的校园活动规律进行确定性采样；同一区域、日期和采样时段可重复得到相同结果。"
    )


st.subheader("24 小时自然光变化")
day_start = datetime.combine(selected_date, time.min)
chart_data = {
    ZONES[zone_id]["name"]: [
        get_lux(zone_id, day_start + timedelta(minutes=30 * index))
        for index in range(48)
    ]
    for zone_id in CAMPUS_PLANNING_AREAS[zone["planning_area_id"]]["linked_zone_ids"]
}
st.markdown(_lux_chart_svg(chart_data), unsafe_allow_html=True)
st.caption("曲线展示当前区域所属片区的代表节点；室内外差异由 config.py 中的场景光照系数表达。")


st.divider()
st.subheader("代表节点 24 小时能耗仿真")
energy_result = simulate_smart_daily_energy(selected_date)
traditional_total = calculate_traditional_daily_energy()
smart_total = energy_result["total_energy_kwh"]
energy_cols = st.columns(4)
energy_cols[0].metric("传统策略", f"{traditional_total:.3f} kWh")
energy_cols[1].metric("智能策略", f"{smart_total:.3f} kWh")
energy_cols[2].metric("估算节能率", f"{calculate_saving_rate(traditional_total, smart_total):.1f}%")
energy_cols[3].metric("参与区域", f"{len(energy_result['zone_energy_kwh'])}/{len(ZONES)}")
st.caption(
    "结果是 10 个代表回路在所选日期的仿真估算，不是 69 个建议部署节点的全校实测总电量。"
)

energy_rows = []
for area_id, area in CAMPUS_PLANNING_AREAS.items():
    area_devices = {
        device_id: device
        for device_id, device in DEVICES.items()
        if device["planning_area_id"] == area_id
    }
    traditional = calculate_traditional_daily_energy(area_devices)
    smart = energy_result["planning_area_energy_kwh"].get(area_id, 0.0)
    energy_rows.append(
        {
            "片区": f"{area_id} {area['name']}",
            "代表回路": len(area_devices),
            "传统 (kWh)": f"{traditional:.3f}",
            "智能 (kWh)": f"{smart:.3f}",
            "节能率": f"{calculate_saving_rate(traditional, smart):.1f}%",
            "口径": "仿真估算" if "仿真估算" in area["parameter_source"] else "一期设计",
        }
    )
st.markdown(_markdown_table(energy_rows))


st.divider()
st.subheader("节点部署明细")
deployment_rows = []
for device_id, device in DEVICES.items():
    zone = ZONES[device["zone_id"]]
    deployment_rows.append(
        {
            "设备编号": device_id,
            "设备名称": device["device_name"],
            "区域": f"{device['zone_id']} {zone['name']}",
            "位置": zone["location"],
            "网关": DEFAULT_GATEWAY_ID,
            "距离 (m)": device["distance_to_gateway_m"],
            "额定功率 (W)": device["rated_power_w"],
            "SF": device["lora_sf"],
            "主网络": device["primary_network"],
            "补充网络": device.get("backup_network") or "—",
            "参数性质": "仿真估算" if "仿真估算" in device["parameter_source"] else "一期设计",
        }
    )
st.markdown(_markdown_table(deployment_rows))

with st.expander("参数口径说明"):
    st.markdown(
        "- 一期和二、三期的距离、功率、SF、光照系数及人员时段均不是现场实测值。\n"
        "- 二、三期配置明确标注为“仿真估算”，依据校园地图相对位置和教室、阅览区、体育场、宿舍走廊、科研公共区、道路等场景类型给出。\n"
        "- 69 个建议节点表示后续部署量；当前只有 10 个代表节点参加逐点仿真，不能直接外推为全校真实能耗。\n"
        "- 校园地图作为规划底图保存在项目 `assets` 目录，网页不依赖外部图片链接。\n"
        "- 光照曲线、室内衰减系数、人员概率和采样间隔统一维护在 `config.py`。\n"
        "- `environment.py` 只产生 Lux 与 Occupancy，不包含照明控制、LoRa 或数据库逻辑。\n"
        "- 完成现场勘测后，只需替换配置参数，页面与环境模型无需改写。"
    )
