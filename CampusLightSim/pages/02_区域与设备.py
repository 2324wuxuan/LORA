"""Streamlit page for campus-zone planning and virtual environment sensors."""

from datetime import datetime, time, timedelta
from html import escape

import streamlit as st

from config import (
    CAMPUS_NAME,
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
        'aria-label="三个区域的24小时自然光照度曲线" '
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
    "本页把校园现场需求转换为统一的软件参数：三区、三节点和一个 LoRaWAN "
    "虚拟网关。距离、功率和环境规律均从 config.py 读取。"
)


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
        }
    )

st.subheader("规划总览")
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
    for zone_id in ZONES
}
st.markdown(_lux_chart_svg(chart_data), unsafe_allow_html=True)
st.caption("道路接收室外自然光最多，走廊次之，教室受建筑遮挡和窗体透射影响最低。")


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
        }
    )
st.markdown(_markdown_table(deployment_rows))

with st.expander("参数口径说明"):
    st.markdown(
        "- 60 m、120 m、350 m 是当前方案的仿真设计距离，不是现场实测值。\n"
        "- 光照曲线、室内衰减系数、人员概率和采样间隔统一维护在 `config.py`。\n"
        "- `environment.py` 只产生 Lux 与 Occupancy，不包含照明控制、LoRa 或数据库逻辑。\n"
        "- 完成现场勘测后，只需替换配置参数，页面与环境模型无需改写。"
    )
