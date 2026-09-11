"""Streamlit page: 传统照明与智能照明能耗对比分析。

负责人：梁（页面集成）。能耗与节能率完全由 analysis/energy.py 现有接口
计算，页面本身不重新实现任何公式：

    analysis/energy.py
        calculate_traditional_daily_energy  → 传统策略固定亮度、固定时段的能耗
        compare_simulated_daily_energy      → 智能策略逐点仿真能耗 + 对比结果
        calculate_saving_rate               → 节能率

页面职责仅限于：选择日期、展示全校代表节点当日能耗汇总（传统能耗、
智能能耗、节省电量、节能率）、绘制传统 vs 智能柱状对比图，以及按区域
展示能耗与节能率明细。不访问数据库，不重新计算 LoRa 或照明逻辑。
"""

from __future__ import annotations

from datetime import datetime
from html import escape

import streamlit as st

from analysis.energy import (
    calculate_saving_rate,
    calculate_traditional_daily_energy,
    compare_simulated_daily_energy,
)
from config import DEVICES, ENERGY, ZONES
from analysis.energy_cache import daily_energy_for_ui


# ---------------------------------------------------------------------------
# 轻量表格渲染：与 02_区域与设备.py 一致，不引入 pandas 依赖。
# ---------------------------------------------------------------------------
def _markdown_table(rows: list[dict]) -> str:
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


# ---------------------------------------------------------------------------
# SVG 柱状图：风格与 02/03 页面的自绘曲线一致，同样不引入 pandas/plotly。
# ---------------------------------------------------------------------------
def _traditional_vs_smart_bar_svg(
    traditional_kwh: float,
    smart_kwh: float,
    unit: str = "kWh",
) -> str:
    """传统照明与智能照明两柱对比图。"""
    width, height = 480, 340
    left, right, top, bottom = 48, 40, 28, 54
    plot_width = width - left - right
    plot_height = height - top - bottom

    values = [traditional_kwh, smart_kwh]
    labels = ["传统照明", "智能照明"]
    colors = ["#f59e0b", "#2563eb"]
    raw_max = max(values) if values else 0.0
    max_value = max(1.0, ((raw_max + 9) // 10) * 10)

    gap = plot_width / len(values)
    bar_width = gap * 0.5

    def bar_x(index: int) -> float:
        return left + gap * index + (gap - bar_width) / 2

    def bar_y(value: float) -> float:
        return top + (1 - value / max_value) * plot_height

    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" '
        'aria-label="传统照明与智能照明能耗对比柱状图" '
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
            f'fill="currentColor" opacity="0.72">{max_value*tick/4:.0f}</text>'
        )

    for index, (value, label, color) in enumerate(zip(values, labels, colors)):
        x = bar_x(index)
        y = bar_y(value)
        bar_height = top + plot_height - y
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" '
            f'fill="{color}" rx="6" />'
        )
        parts.append(
            f'<text x="{x+bar_width/2:.1f}" y="{max(y-10, top+12):.1f}" text-anchor="middle" '
            f'font-size="13" font-weight="600" fill="currentColor">{value:.2f} {escape(unit)}</text>'
        )
        parts.append(
            f'<text x="{x+bar_width/2:.1f}" y="{height-24:.1f}" text-anchor="middle" font-size="13" '
            f'fill="currentColor">{escape(label)}</text>'
        )

    parts.append(
        f'<line x1="{left}" y1="{top+plot_height:.1f}" x2="{width-right}" y2="{top+plot_height:.1f}" '
        'stroke="currentColor" opacity="0.35" />'
    )
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# 页面主体
# ---------------------------------------------------------------------------
st.title("🔋 能耗分析")
st.caption("比较全部独立控制节点在传统照明策略与智能照明策略下的当日能耗与节能效果")
st.info(
    "传统能耗按 `config.ENERGY` 固定策略计算（全部灯具 "
    f"{ENERGY['traditional_brightness']}% 亮度、{ENERGY['traditional_start_hour']:02d}:00–"
    f"{ENERGY['traditional_end_hour']:02d}:00 常亮）；智能能耗由 environment → lighting → "
    f"device 逐点仿真后对实际功率积分得到。结果覆盖全部 {len(DEVICES)} 个独立照明控制节点，"
    "不是全校实测总电量。"
)

selected_date = st.date_input("选择日期", value=datetime.now().date(), key="energy_date")

result = daily_energy_for_ui(selected_date)
traditional_total = result["traditional_energy_kwh"]
smart_total = result["smart_energy_kwh"]
saved_total = result["saved_energy_kwh"]
saving_rate = result["saving_rate_percent"]


st.divider()
st.subheader(f"当日能耗汇总 · {selected_date.strftime('%Y-%m-%d')}")
metric_cols = st.columns(4)
metric_cols[0].metric("传统照明能耗", f"{traditional_total:.3f} kWh")
metric_cols[1].metric("智能照明能耗", f"{smart_total:.3f} kWh")
metric_cols[2].metric("节省电量", f"{saved_total:.3f} kWh")
metric_cols[3].metric("节能率", f"{saving_rate:.1f}%")
st.caption(
    f"参与节点 {len(DEVICES)} 个 · 全天采样点 {result['sample_count']} 个 · "
    "节能率 = (传统能耗 − 智能能耗) / 传统能耗 × 100%"
)


st.divider()
st.subheader("传统 vs 智能：能耗对比")
chart_col, _ = st.columns([1, 1])
with chart_col:
    st.markdown(
        _traditional_vs_smart_bar_svg(traditional_total, smart_total),
        unsafe_allow_html=True,
    )
st.caption("柱高表示当日累计能耗；智能照明按需调光，累计耗电量明显低于传统常亮策略。")


st.divider()
st.subheader("按区域对比")
zone_rows = []
for zone_id, zone in ZONES.items():
    zone_devices = {
        device_id: device
        for device_id, device in DEVICES.items()
        if device["zone_id"] == zone_id
    }
    zone_traditional = calculate_traditional_daily_energy(zone_devices) if zone_devices else 0.0
    zone_smart = result["zone_energy_kwh"].get(zone_id, 0.0)
    zone_rate = f"{calculate_saving_rate(zone_traditional, zone_smart):.1f}%" if zone_traditional > 0 else "—"
    zone_rows.append(
        {
            "区域": f"{zone_id} {zone['name']}",
            "传统能耗 (kWh)": f"{zone_traditional:.3f}",
            "智能能耗 (kWh)": f"{zone_smart:.3f}",
            "节能率": zone_rate,
        }
    )
st.dataframe(zone_rows, width="stretch", hide_index=True)
st.caption("每个控制区对应一个独立节点；节能率按该控制区自身的传统/智能能耗独立计算。")


with st.expander("参数口径说明"):
    st.markdown(
        "- 传统策略：`config.ENERGY` 固定亮度与固定时段，公式为 "
        f"`{ENERGY['formula']}`（见 `analysis/energy.py`）。\n"
        "- 智能策略：`compare_simulated_daily_energy` 将每个独立节点接入 "
        "`environment → lighting → device` 全链路，对每个采样周期的实际功率积分。\n"
        "- 节能率 = (传统能耗 − 智能能耗) / 传统能耗 × 100%，与 `interfaces.md` 公式一致。\n"
        f"- 当前全部 {len(DEVICES)} 个控制节点逐一参与仿真，功率按每个回路的灯数与单灯功率计算，"
        "结果不能直接外推为全校真实能耗。\n"
        "- 本页只调用 `analysis/energy.py` 现成接口进行展示，不重新实现能耗或节能率计算。"
    )
