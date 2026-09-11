"""Streamlit page for campus-zone planning and virtual environment sensors."""

from datetime import datetime, time, timedelta
import csv
from io import StringIO
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
    DEVICES,
    GATEWAYS,
    LIGHTING_RULES,
    LIGHTING_PLAN_ESTIMATE,
    RESEARCH_AREA,
    SCHOOL_NAME,
    SIMULATION_STEP_MINUTES,
    ZONES,
)
from simulator.environment import get_environment, get_lux, get_occupancy_probability
from planning import PLAN_BOUNDARY
from analysis.energy_cache import daily_energy_for_ui


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
    f"八个片区的 {len(DEVICES)} 个独立控制节点全部接入仿真。每间教室一个节点，走廊分段、路灯逐杆控制。所有参数统一标为“仿真估算”，"
    "用于运行 Lux、Occupancy、智能照明和能耗仿真，不代表现场实测或最终施工配置。"
)


st.subheader("校园总体规划地图")
planned_nodes = sum(area["recommended_nodes"] for area in CAMPUS_PLANNING_AREAS.values())
simulation_nodes = sum(area["simulation_nodes"] for area in CAMPUS_PLANNING_AREAS.values())
plan_col, zone_col, simulation_col, node_total_col, fixture_col = st.columns(5)
plan_col.metric("校园规划片区", len(CAMPUS_PLANNING_AREAS))
zone_col.metric("独立控制区", len(ZONES))
simulation_col.metric("已接入控制节点", simulation_nodes)
node_total_col.metric("规划控制节点（估算）", planned_nodes)
fixture_col.metric("规划灯具（估算）", LIGHTING_PLAN_ESTIMATE["fixtures"])
st.caption("主楼按10层×每层10间教室；每间教室12灯、1控制节点。其余区域逐项估算，灯具数与控制节点数分别统计。")

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
            "状态": area["status"],
            "参数性质": "仿真估算" if "仿真估算" in area["parameter_source"] else "仿真估算",
            "已接入节点": area["simulation_nodes"],
            "规划控制节点": area["recommended_nodes"],
            "规划灯具": area["recommended_fixtures"],
        }
    )
st.markdown(_markdown_table(planning_rows))

with st.expander("照明数量估算明细与计算依据", expanded=False):
    st.write(PLAN_BOUNDARY)
    st.caption("建筑项节点=建筑单元数×层数×每层控制区；灯具=节点×每节点灯数。道路按向上取整配置灯杆，开放路段另计端点，环路不重复计端点。修改 planning.py 的清单因子后重启应用可重新计算。")
    quantity_rows = [
        {"片区": row["area_id"], "清单编号": row["item_id"], "照明对象": row["name"],
         "节点计算式": row["node_formula"], "控制节点": row["control_nodes"],
         "灯具计算式": row["fixture_formula"], "灯具": row["fixtures"], "假设依据": row["basis"]}
        for row in LIGHTING_PLAN_ESTIMATE["rows"]
    ]
    st.markdown(_markdown_table(quantity_rows))
    csv_stream = StringIO()
    writer = csv.DictWriter(csv_stream, fieldnames=list(quantity_rows[0]))
    writer.writeheader()
    writer.writerows(quantity_rows)
    st.download_button("下载照明数量清单 CSV", csv_stream.getvalue().encode("utf-8-sig"),
                       file_name="lighting_quantity_plan.csv", mime="text/csv")

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
st.subheader("全校独立照明控制区")

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
            "估算坐标 (m)": f"({device['x']:g}, {device['y']:g})",
            "LoRa SF": device.get("lora_sf", "—"),
            "控制方式": zone["control_mode"],
            "参数性质": "仿真估算" if "仿真估算" in zone["parameter_source"] else "仿真估算",
        }
    )

st.dataframe(zone_rows, width="stretch", hide_index=True)

gateway_col, node_col, step_col = st.columns(3)
gateway_col.metric("虚拟网关", len(GATEWAYS))
node_col.metric("照明控制节点", len(DEVICES))
step_col.metric("环境采样步长", f"{SIMULATION_STEP_MINUTES} 分钟")
st.caption("500 × 750 m 校园 · 西北角为原点，x 向东、y 向南 · 三网关动态选路")
st.markdown(_markdown_table([
    {"网关": key, "名称": gateway["name"], "位置": gateway["location"],
     "坐标 (m)": f"({gateway['x']:g}, {gateway['y']:g})", "高度 (m)": gateway["height"]}
    for key, gateway in GATEWAYS.items()
]))


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
    for zone_id in list(dict.fromkeys([selected_zone_id] + CAMPUS_PLANNING_AREAS[zone["planning_area_id"]]["linked_zone_ids"]))[:3]
}
st.markdown(_lux_chart_svg(chart_data), unsafe_allow_html=True)
st.caption("曲线展示所选控制区及同片区最多另外两个控制区，避免千条曲线重叠；全部节点仍参与能耗计算。")


st.divider()
st.subheader("全部控制节点 24 小时能耗仿真")
energy_result = daily_energy_for_ui(selected_date)
traditional_total = calculate_traditional_daily_energy()
smart_total = energy_result["total_energy_kwh"]
energy_cols = st.columns(4)
energy_cols[0].metric("传统策略", f"{traditional_total:.3f} kWh")
energy_cols[1].metric("智能策略", f"{smart_total:.3f} kWh")
energy_cols[2].metric("估算节能率", f"{calculate_saving_rate(traditional_total, smart_total):.1f}%")
energy_cols[3].metric("参与区域", f"{len(energy_result['zone_energy_kwh'])}/{len(ZONES)}")
st.caption(
    f"已逐一计算 {len(DEVICES)} 个独立回路，覆盖 {LIGHTING_PLAN_ESTIMATE['fixtures']} 盏灯；每个回路功率由灯数×单灯功率计算。结果为全量软件仿真，非现场实测。"
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
            "独立回路": len(area_devices),
            "传统 (kWh)": f"{traditional:.3f}",
            "智能 (kWh)": f"{smart:.3f}",
            "节能率": f"{calculate_saving_rate(traditional, smart):.1f}%",
            "口径": "仿真估算" if "仿真估算" in area["parameter_source"] else "仿真估算",
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
            "网关": "每周期动态选择最优链路",
            "估算坐标 (m)": f"({device['x']:g}, {device['y']:g})",
            "额定功率 (W)": device["rated_power_w"],
            "回路灯具数": device["fixture_count"],
            "楼层": device["floor"],
            "SF": device["lora_sf"],
            "主网络": device["primary_network"],
            "补充网络": device.get("backup_network") or "—",
            "参数性质": "仿真估算" if "仿真估算" in device["parameter_source"] else "仿真估算",
        }
    )
st.dataframe(deployment_rows, width="stretch", hide_index=True)

with st.expander("参数口径说明"):
    st.markdown(
        "- 三网关形成三角布局；主备网关表是规划说明，不限制运行时选路。\n"
        "- 节点坐标是新增仿真估算，片区归属保持不变；链路距离由节点与网关坐标计算。\n"
        "- 所有节点的距离、功率、SF、光照系数及人员时段均不是现场实测值。\n"
        "- 所有节点配置明确标注为“仿真估算”，依据校园地图相对位置和教室、阅览区、体育场、宿舍走廊、科研公共区、道路等场景类型给出。\n"
        f"- {planned_nodes} 个控制节点已全部实例化；{LIGHTING_PLAN_ESTIMATE['fixtures']} 盏灯按教室/分区/灯杆归入回路，具有独立状态和故障管理。\n"
        "- 校园地图作为规划底图保存在项目 `assets` 目录，网页不依赖外部图片链接。\n"
        "- 光照曲线、室内衰减系数、人员概率和采样间隔统一维护在 `config.py`。\n"
        "- `environment.py` 只产生 Lux 与 Occupancy，不包含照明控制、LoRa 或数据库逻辑。\n"
        "- 完成现场勘测后，只需替换配置参数，页面与环境模型无需改写。"
    )
