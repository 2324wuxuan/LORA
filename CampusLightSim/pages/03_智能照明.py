"""Streamlit page: smart lighting control and 24-hour visualization.

负责人：梁（页面集成）。数据来自现有公共模块，页面本身不重新实现算法：

    simulator/environment.py  → lux / occupancy
    control/lighting.py       → AUTO 模式下的目标 brightness（含教室迟滞）
    simulator/device.py       → VirtualLightingNode，负责 power 与状态快照

页面职责仅限于：选择设备、选择时间、展示当前状态卡片、绘制 24 小时
Lux / Brightness / Power 三条曲线，并可视化“自然光增强 → 人工照明降低”
的联动关系。不访问数据库、不重新计算 LoRa，不绕开设备模型直接改功率。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from html import escape

import streamlit as st

from analysis.energy import calculate_total_energy
from config import DEVICES, LIGHTING_RULES, SIMULATION_STEP_MINUTES, ZONES
from control.lighting import auto_control, reset_state
from simulator.device import VirtualLightingNode
from simulator.environment import get_lux, get_occupancy


# ---------------------------------------------------------------------------
# 数据装配：把 environment + lighting + device 三个模块串成一天的时间序列。
# 页面只负责编排调用顺序和展示，具体规则完全在对应模块内部。
# ---------------------------------------------------------------------------
def _build_day_series(device_id: str, day: date, mode: str, manual_brightness: float) -> dict:
    """计算某设备在给定日期 00:00~24:00（288 点）的 lux/occupancy/brightness/power。

    AUTO 模式下 brightness 由 control.lighting.auto_control 按时间顺序依次
    计算，保证 Z01 教室的迟滞状态与真实运行时一致；MANUAL 模式下 brightness
    在全天保持为用户指定的手动值，只有 lux/occupancy 仍按环境模拟给出，用于
    对照“如果这一刻是自动模式，本应输出的亮度”。
    """
    device_cfg = DEVICES[device_id]
    zone_id = device_cfg["zone_id"]
    node = VirtualLightingNode.from_config(device_id)
    node.set_mode(mode)

    step = SIMULATION_STEP_MINUTES
    points_per_day = 24 * 60 // step
    day_start = datetime.combine(day, time.min)

    # 迟滞状态属于 zone_id 维度的全局记忆；重新铺一整天曲线前先清空，
    # 避免沿用上一次页面交互（不同日期/不同设备）残留的历史状态。
    reset_state(zone_id)

    timestamps: list[datetime] = []
    lux_series: list[float] = []
    occupancy_series: list[bool] = []
    brightness_series: list[float] = []
    power_series: list[float] = []
    reference_brightness_series: list[float] = []  # AUTO 参考亮度，MANUAL 模式下用于对照

    for index in range(points_per_day):
        timestamp = day_start + timedelta(minutes=index * step)
        lux = get_lux(zone_id, timestamp)
        occupancy = get_occupancy(zone_id, timestamp)
        auto_brightness = auto_control(zone_id, lux, occupancy, timestamp)

        if mode == "MANUAL":
            brightness = float(manual_brightness)
        else:
            brightness = auto_brightness

        node.update_environment(lux, occupancy)
        # 不使用三元表达式调用无返回值的方法。Streamlit 会自动渲染裸表达式，
        # turn_on()/turn_off() 的返回值 None 会因此在页面上重复显示。
        if brightness > 0:
            node.turn_on()
        else:
            node.turn_off()
        node.set_brightness(brightness)

        timestamps.append(timestamp)
        lux_series.append(lux)
        occupancy_series.append(occupancy)
        brightness_series.append(node.brightness)
        power_series.append(node.power)
        reference_brightness_series.append(auto_brightness)

    return {
        "zone_id": zone_id,
        "timestamps": timestamps,
        "lux": lux_series,
        "occupancy": occupancy_series,
        "brightness": brightness_series,
        "power": power_series,
        "reference_brightness": reference_brightness_series,
        "rated_power": node.rated_power,
    }


def _current_index(timestamps: list[datetime], moment: datetime) -> int:
    """返回距 moment 最近且不晚于它的采样点下标，供“当前状态”卡片取值。"""
    index = 0
    for position, ts in enumerate(timestamps):
        if ts <= moment:
            index = position
        else:
            break
    return index


# ---------------------------------------------------------------------------
# SVG 曲线：与 02_区域与设备.py 一致，不引入 pandas/plotly 等额外依赖。
# ---------------------------------------------------------------------------
def _dual_axis_lux_brightness_svg(
    timestamps: list[datetime],
    lux: list[float],
    brightness: list[float],
    current_index: int,
) -> str:
    """Lux（左轴）与 Brightness（右轴）叠加，直观展示两者的反向联动。"""
    width, height = 960, 340
    left, right, top, bottom = 64, 64, 28, 54
    plot_width = width - left - right
    plot_height = height - top - bottom
    count = len(timestamps)

    lux_max = max(100.0, ((max(lux) + 99) // 100) * 100)
    brightness_max = 100.0
    lux_color = "#f59e0b"
    brightness_color = "#2563eb"

    def x_at(index: int) -> float:
        return left + index / (count - 1) * plot_width

    def y_lux(value: float) -> float:
        return top + (1 - value / lux_max) * plot_height

    def y_brightness(value: float) -> float:
        return top + (1 - value / brightness_max) * plot_height

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Lux与Brightness24小时联动曲线" '
        'style="width:100%;height:auto;background:var(--secondary-background-color);border-radius:8px">'
    ]
    for tick in range(5):
        y = top + plot_height - tick / 4 * plot_height
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" '
            'stroke="currentColor" opacity="0.10" />'
        )
        parts.append(
            f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" font-size="12" '
            f'fill="{lux_color}">{lux_max*tick/4:.0f}</text>'
        )
        parts.append(
            f'<text x="{width-right+8}" y="{y+4:.1f}" text-anchor="start" font-size="12" '
            f'fill="{brightness_color}">{brightness_max*tick/4:.0f}</text>'
        )
    for hour in (0, 6, 12, 18, 24):
        idx = min(count - 1, round(hour / 24 * (count - 1)))
        x = x_at(idx)
        parts.append(
            f'<text x="{x:.1f}" y="{height-24}" text-anchor="middle" font-size="12" '
            f'fill="currentColor" opacity="0.72">{hour:02d}:00</text>'
        )

    lux_points = " ".join(f"{x_at(i):.1f},{y_lux(v):.1f}" for i, v in enumerate(lux))
    brightness_points = " ".join(
        f"{x_at(i):.1f},{y_brightness(v):.1f}" for i, v in enumerate(brightness)
    )
    parts.append(
        f'<polyline points="{lux_points}" fill="none" stroke="{lux_color}" '
        'stroke-width="3" stroke-linejoin="round" stroke-linecap="round" />'
    )
    parts.append(
        f'<polyline points="{brightness_points}" fill="none" stroke="{brightness_color}" '
        'stroke-width="3" stroke-dasharray="2 5" stroke-linejoin="round" stroke-linecap="round" />'
    )

    # 当前时刻的竖线与两个数据点标记。
    cx = x_at(current_index)
    parts.append(
        f'<line x1="{cx:.1f}" y1="{top}" x2="{cx:.1f}" y2="{top+plot_height}" '
        'stroke="currentColor" opacity="0.35" stroke-dasharray="3 3" />'
    )
    parts.append(f'<circle cx="{cx:.1f}" cy="{y_lux(lux[current_index]):.1f}" r="5" fill="{lux_color}" />')
    parts.append(
        f'<circle cx="{cx:.1f}" cy="{y_brightness(brightness[current_index]):.1f}" '
        f'r="5" fill="{brightness_color}" />'
    )

    legend_x = left
    for label, color, dash in (("Lux（左轴，自然光）", lux_color, ""), ("Brightness（右轴，人工照明 %）", brightness_color, "2 5")):
        parts.append(
            f'<line x1="{legend_x}" y1="14" x2="{legend_x+26}" y2="14" stroke="{color}" '
            f'stroke-width="3" stroke-dasharray="{dash}" />'
        )
        parts.append(
            f'<text x="{legend_x+34}" y="18" font-size="12" fill="currentColor">{escape(label)}</text>'
        )
        legend_x += 250

    parts.append("</svg>")
    return "".join(parts)


def _single_series_svg(
    timestamps: list[datetime],
    values: list[float],
    color: str,
    unit_label: str,
    aria_label: str,
    current_index: int,
    y_max_override: float | None = None,
) -> str:
    """通用单曲线 SVG（用于 Power 曲线，也可复用于其他单指标图）。"""
    width, height = 960, 260
    left, right, top, bottom = 64, 24, 24, 44
    plot_width = width - left - right
    plot_height = height - top - bottom
    count = len(values)

    raw_max = max(values) if values else 0.0
    if y_max_override is not None:
        y_max = y_max_override
    else:
        y_max = max(1.0, ((raw_max + 9) // 10) * 10)

    def x_at(index: int) -> float:
        return left + index / (count - 1) * plot_width

    def y_at(value: float) -> float:
        return top + (1 - value / y_max) * plot_height

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(aria_label)}" '
        'style="width:100%;height:auto;background:var(--secondary-background-color);border-radius:8px">'
    ]
    for tick in range(4):
        y = top + plot_height - tick / 3 * plot_height
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" '
            'stroke="currentColor" opacity="0.10" />'
        )
        parts.append(
            f'<text x="{left-8}" y="{y+4:.1f}" text-anchor="end" font-size="12" '
            f'fill="currentColor" opacity="0.72">{y_max*tick/3:.0f}</text>'
        )
    for hour in (0, 6, 12, 18, 24):
        idx = min(count - 1, round(hour / 24 * (count - 1)))
        x = x_at(idx)
        parts.append(
            f'<text x="{x:.1f}" y="{height-16}" text-anchor="middle" font-size="12" '
            f'fill="currentColor" opacity="0.72">{hour:02d}:00</text>'
        )

    area_points = (
        f"{x_at(0):.1f},{top+plot_height:.1f} "
        + " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(values))
        + f" {x_at(count-1):.1f},{top+plot_height:.1f}"
    )
    parts.append(f'<polygon points="{area_points}" fill="{color}" opacity="0.12" />')
    line_points = " ".join(f"{x_at(i):.1f},{y_at(v):.1f}" for i, v in enumerate(values))
    parts.append(
        f'<polyline points="{line_points}" fill="none" stroke="{color}" '
        'stroke-width="3" stroke-linejoin="round" stroke-linecap="round" />'
    )

    cx = x_at(current_index)
    parts.append(
        f'<line x1="{cx:.1f}" y1="{top}" x2="{cx:.1f}" y2="{top+plot_height}" '
        'stroke="currentColor" opacity="0.35" stroke-dasharray="3 3" />'
    )
    parts.append(f'<circle cx="{cx:.1f}" cy="{y_at(values[current_index]):.1f}" r="5" fill="{color}" />')

    parts.append(
        f'<text x="16" y="{top + plot_height/2:.1f}" text-anchor="middle" font-size="12" '
        f'fill="currentColor" transform="rotate(-90 16 {top + plot_height/2:.1f})">{escape(unit_label)}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# 页面主体
# ---------------------------------------------------------------------------
st.title("💡 智能照明")
st.caption("按设备查看 24 小时自动调光运行情况：光照、亮度、功率的联动关系")
st.info(
    "曲线由 environment.py（光照/人员）→ lighting.py（自动调光算法）→ "
    f"device.py（灯具状态与功率）依次计算得到。全部 {len(DEVICES)} 个独立节点均可选择；"
    "所有结果均属于仿真估算。"
)


# 设备选择 —— 必须先选设备，后续状态与曲线均围绕该设备展开。
device_ids = list(DEVICES)
select_col, date_col, time_col, mode_col = st.columns([1.4, 1, 1, 1])
with select_col:
    selected_device_id = st.selectbox(
        "选择设备",
        options=device_ids,
        format_func=lambda item: f"[{item}] {DEVICES[item]['device_name']}",
    )
device_cfg = DEVICES[selected_device_id]
zone_cfg = ZONES[device_cfg["zone_id"]]

with date_col:
    selected_date = st.date_input("日期", value=datetime.now().date(), key="lighting_date")
with time_col:
    selected_time = st.time_input(
        "查看时刻",
        value=time(10, 0),
        step=timedelta(minutes=SIMULATION_STEP_MINUTES),
        key="lighting_time",
    )
with mode_col:
    selected_mode = st.radio(
        "控制模式",
        options=["AUTO", "MANUAL"],
        horizontal=True,
        key=f"lighting_mode_{selected_device_id}",
    )

manual_brightness = float(device_cfg.get("initial_brightness", 0))
if selected_mode == "MANUAL":
    manual_brightness = st.slider(
        "手动亮度 (%)",
        min_value=0,
        max_value=100,
        value=int(manual_brightness),
        step=5,
        help="MANUAL 模式下全天亮度固定为该值；下方曲线仍会同步给出 AUTO 参考亮度用于对照。",
    )

selected_timestamp = datetime.combine(selected_date, selected_time)

series = _build_day_series(selected_device_id, selected_date, selected_mode, manual_brightness)
current_index = _current_index(series["timestamps"], selected_timestamp)


st.divider()
st.subheader(f"当前状态 · [{selected_device_id}] {device_cfg['device_name']}")
st.caption(f"所属区域：{device_cfg['zone_id']} {zone_cfg['name']} · {selected_timestamp.strftime('%Y-%m-%d %H:%M')}")
st.caption(f"参数来源：{device_cfg['parameter_source']}")

current_lux = series["lux"][current_index]
current_occupancy = series["occupancy"][current_index]
current_brightness = series["brightness"][current_index]
current_power = series["power"][current_index]
lamp_on = current_brightness > 0

metric_cols = st.columns(7)
metric_cols[0].metric("当前 Lux", f"{current_lux:.1f} lux")
metric_cols[1].metric("人员状态", "🧍 有人" if current_occupancy else "— 无人")
metric_cols[2].metric("灯状态", "🟡 ON" if lamp_on else "⚫ OFF")
metric_cols[3].metric("亮度", f"{current_brightness:.0f}%")
metric_cols[4].metric("功率", f"{current_power:.1f} W", help=f"额定功率 {series['rated_power']:g} W")
metric_cols[5].metric("模式", selected_mode)
daily_energy = calculate_total_energy(
    ({"power": power} for power in series["power"]),
    SIMULATION_STEP_MINUTES,
)
metric_cols[6].metric("全天能耗", f"{daily_energy:.3f} kWh")

if selected_mode == "MANUAL":
    reference = series["reference_brightness"][current_index]
    st.caption(f"参考：若为 AUTO 模式，此刻算法计算的目标亮度应为 {reference:.0f}%。")


st.divider()
st.subheader("24 小时 Lux ↔ Brightness 联动")
st.markdown(_dual_axis_lux_brightness_svg(
    series["timestamps"], series["lux"], series["brightness"], current_index,
), unsafe_allow_html=True)
st.caption("自然光增强（Lux 曲线上升）→ 人工照明相应降低（Brightness 曲线下降），两条曲线呈反向联动；虚线为当前查看时刻。")

st.subheader("24 小时 Power 曲线")
st.markdown(_single_series_svg(
    series["timestamps"], series["power"], "#dc2626", "功率 (W)",
    f"{selected_device_id} 24小时功率曲线", current_index,
    y_max_override=float(series["rated_power"]),
), unsafe_allow_html=True)
st.caption("功率 = 额定功率 × 亮度 / 100（device.py），随 Brightness 曲线同步升降。")

with st.expander("单独查看 Lux / Brightness 曲线"):
    lux_tab, brightness_tab = st.tabs(["Lux 曲线", "Brightness 曲线"])
    with lux_tab:
        st.markdown(_single_series_svg(
            series["timestamps"], series["lux"], "#f59e0b", "照度 (lux)",
            f"{selected_device_id} 24小时Lux曲线", current_index,
        ), unsafe_allow_html=True)
    with brightness_tab:
        st.markdown(_single_series_svg(
            series["timestamps"], series["brightness"], "#2563eb", "亮度 (%)",
            f"{selected_device_id} 24小时Brightness曲线", current_index,
            y_max_override=100.0,
        ), unsafe_allow_html=True)

with st.expander("控制逻辑说明"):
    rule = LIGHTING_RULES[device_cfg["zone_id"]]
    if zone_cfg["control_mode"] == "LIGHT_OCCUPANCY":
        st.markdown(
            f"- **光照 + 人员**：Lux < {rule['lux_on_threshold']:g} 且有人 → "
            f"{rule['occupied_brightness']:g}%；Lux > {rule['lux_off_threshold']:g} → "
            f"{rule['unoccupied_brightness']:g}%；中间迟滞区间保持上一状态。"
        )
    elif zone_cfg["control_mode"] == "OCCUPANCY":
        st.markdown(
            f"- **仅人员**：有人 → {rule['occupied_brightness']:g}%；"
            f"无人 → {rule['unoccupied_brightness']:g}% 基础照明。"
        )
    else:
        st.markdown(
            f"- **时间 + 光照 + 人员**：白天（Lux ≥ {rule['day_lux_threshold']:g}）→ "
            f"{rule['day_brightness']:g}%；夜间有人 → {rule['night_occupied_brightness']:g}%；"
            f"夜间无人 → {rule['night_unoccupied_brightness']:g}% 基础照明。"
        )
    st.caption("以上规则来自 control/lighting.py，阈值以 config.LIGHTING_RULES 为准，本页仅展示结果。")
