"""三网关链路预览；全部通信计算由 simulator 模块提供。"""
from copy import deepcopy
from datetime import datetime
from html import escape

import streamlit as st

from config import AREA_GATEWAY_PLAN, CAMPUS_PLANNING_AREAS, DEVICES, GATEWAYS
from simulator.gateway import select_gateway


st.title("📡 LoRa 三网关网络")
st.caption("西北角 (0, 0)，x 向东 0～500 m，y 向南 0～750 m；坐标和链路均为仿真参数。")
st.caption(f"全部 {len(DEVICES)} 个节点同时参与链路预览；选择节点仅用于查看三条链路详情。")
st.info(
    "本页只做确定性链路预览，不运行完整照明仿真，也不写数据库。LoRaWAN 节点上行时不会"
    "像手机一样先绑定某个网关：多个网关可能同时收到同一帧。页面将可达链路中 RSSI 最大的"
    "网关标为“最佳接收网关”，用于简化展示和后续状态保存。"
)
node_metric, gateway_metric, model_metric = st.columns(3)
node_metric.metric("参与预览节点", len(DEVICES))
gateway_metric.metric("候选接收网关", len(GATEWAYS))
model_metric.metric("链路模型", "三维对数路径损耗")
device_id = st.selectbox("查看节点链路详情", list(DEVICES),
                         format_func=lambda key: f"{key} · {DEVICES[key]['device_name']}")
device = {**DEVICES[device_id], "device_id": device_id}
st.write(f"所属片区：{CAMPUS_PLANNING_AREAS[device['planning_area_id']]['name']}")
plan = AREA_GATEWAY_PLAN[device["planning_area_id"]]
st.caption("规划主要网关：" + (" / ".join(plan["primary"]) or "动态选择")
           + "；规划备用：" + (" / ".join(plan["backup"]) or "不固定指定"))
if st.checkbox("预览其他节点位置（不修改原区域规划）"):
    device["x"] = st.number_input("x 向东 (m)", 0.0, 500.0, float(device["x"]))
    device["y"] = st.number_input("y 向南 (m)", 0.0, 750.0, float(device["y"]))
offline = st.multiselect("对照场景离线网关（仅预览）", list(GATEWAYS))
st.caption("此预览不注入会话故障、不写入运维记录。正式故障流程由 FaultManager.sample_network 处理。")
epoch = st.session_state.get("simulation_time", datetime(2026, 9, 10, 10))
normal_gateways = deepcopy(GATEWAYS)
scenario_gateways = deepcopy(normal_gateways)
for key in offline:
    scenario_gateways[key]["status"] = "OFFLINE"
all_devices = {key: {**value, "device_id": key} for key, value in DEVICES.items()}
all_devices[device_id] = device
normal_results = {key: select_gateway(value, normal_gateways, timestamp=epoch)
                  for key, value in all_devices.items()}
scenario_results = {key: select_gateway(value, scenario_gateways, timestamp=epoch)
                    for key, value in all_devices.items()}
normal = normal_results[device_id]
scenario = scenario_results[device_id]
left, right = st.columns(2)
left.metric("全部在线时最佳接收网关", normal["gateway_id"] or "无可达网关")
right.metric("对照场景最佳接收网关", scenario["gateway_id"] or "无可达网关")
st.dataframe([
    {"网关": key, "名称": GATEWAYS[key]["name"],
     "在线": link["online"], "距离 (m)": round(link["distance_m"], 1),
     "RSSI (dBm)": round(link["rssi"], 2), "SNR (dB)": round(link["snr"], 2),
     "接收灵敏度 (dBm)": round(link["sensitivity_dbm"], 1),
     "链路余量 (dB)": round(link["link_margin_db"], 2),
     "模型丢包概率": round(link["packet_loss_probability"], 3),
     "空中时间 (ms)": round(link["airtime_ms"], 1),
     "简化总时延 (ms)": round(link["delay_ms"], 1),
     "可达": link["reachable"], "本次收包": link["packet_success"],
     "最佳接收": scenario["gateway_id"] == key}
    for key, link in scenario["gateway_links"].items()
])
st.caption("摘要链路先比较可达在线网关的 RSSI，再使用该链路的收包结果；模型丢包概率不等于多轮实测 PDR。")

with st.expander("链路指标怎么算，以及模型没有模拟什么"):
    st.markdown(
        "1. **三维距离**：由节点和网关的 `(x, y, height)` 计算。\n"
        "2. **路径损耗**：`PL = PL(d₀) + 10n·log₁₀(d/d₀) + 建筑遮挡 + 阴影波动`。\n"
        "3. **RSSI**：`发射功率 + 网关天线增益 - 路径损耗`。\n"
        "4. **链路余量**：`RSSI - 当前 SF 的接收灵敏度`；余量小于 0 时无线链路不可达。\n"
        "5. **SNR**：由 RSSI 与 -117 dBm 模拟噪声底计算，并限制在 SX127x 包 SNR 寄存器可报告范围。\n"
        "6. **空中时间**：按 SF、125 kHz 带宽、4/5 编码率和 20-byte 遥测负载估算。\n"
        "7. **收包结果**：按链路余量得到简化丢包概率，再进行可重复的确定性采样。"
    )
    st.warning(
        "这是课程项目的简化链路预算模型，没有模拟 LoRaWAN 入网、信道选择、ADR、同频碰撞、"
        "占空比、下行接收窗口、网络服务器去重，也没有真实建筑材料和现场测量数据。"
    )

st.subheader("全校节点与三网关拓扑")
st.caption("所有节点使用相同样式；外圈表示当前查看的节点。连线只表示用于摘要的最佳接收网关，不表示节点与该网关独占绑定，也不代表本次收包成功。灰色节点无可达网关。")
# 原点及纵横比例与仿真坐标保持一致；不是对原校园底图进行地理配准。
parts = ['<svg viewBox="-40 -40 640 840" style="max-width:560px;width:100%" '
         'role="img" aria-label="三网关与全校全部代表节点的北向上坐标示意图">',
         '<rect width="500" height="750" fill="none" stroke="gray"/>',
         '<text x="0" y="-15" fill="currentColor">北 · 西北角 (0, 0)</text>',
         ]
for key, node in all_devices.items():
    selected_gateway = scenario_results[key]["gateway_id"]
    if selected_gateway is not None:
        gateway = GATEWAYS[selected_gateway]
        parts.append(f'<line x1="{node["x"]}" y1="{node["y"]}" '
                     f'x2="{gateway["x"]}" y2="{gateway["y"]}" '
                     'stroke="#94a3b8" stroke-width="1.5" opacity="0.65"/>')
for key, gateway in GATEWAYS.items():
    color = "#ef4444" if key in offline else "#2563eb"
    parts.append(f'<circle cx="{gateway["x"]}" cy="{gateway["y"]}" r="9" fill="{color}"/>')
    parts.append(f'<text x="{gateway["x"] + 12}" y="{gateway["y"]}" fill="currentColor">{key}</text>')
for key, node in all_devices.items():
    color = "#16a34a" if scenario_results[key]["gateway_id"] else "#64748b"
    label = escape(f"{key} · {node['device_name']} · {node['planning_area_id']}")
    parts.append(f'<g data-device-id="{key}"><title>{label}</title>'
                 f'<circle cx="{node["x"]}" cy="{node["y"]}" r="7" fill="{color}"/>')
    if key == device_id:
        parts.append(f'<circle cx="{node["x"]}" cy="{node["y"]}" r="12" '
                     'fill="none" stroke="#f59e0b" stroke-width="2"/>')
    # 密集的主楼节点左右错开放置文字，其余节点统一标注。
    dx, dy, anchor = {"CL-N01": (-14, -7, "end"), "CL-N02": (-14, 12, "end"),
                      "CL-N03": (14, 17, "start"), "CL-N05": (-14, -12, "end")}.get(
                          key, (14, -10, "start"))
    if key == device_id:
        parts.append(f'<text x="{node["x"] + dx}" y="{node["y"] + dy}" '
                     f'text-anchor="{anchor}" font-size="12" fill="currentColor">{key}</text>')
    parts.append('</g>')
parts.append('</svg>')
st.markdown("".join(parts), unsafe_allow_html=True)
st.caption("所有节点均计算并绘制；只标注所选节点文字以避免重叠。3个网关当前只验证链路模型，不代表已验证1690节点的LoRaWAN并发容量。")

st.subheader("全部节点链路汇总")
st.dataframe([
    {"节点": key, "名称": node["device_name"],
     "片区": f"{node['planning_area_id']} · {CAMPUS_PLANNING_AREAS[node['planning_area_id']]['name']}",
     "正常最佳接收": normal_results[key]["gateway_id"] or "无可达网关",
     "场景最佳接收": scenario_results[key]["gateway_id"] or "无可达网关",
     "最佳接收变化": normal_results[key]["gateway_id"] != scenario_results[key]["gateway_id"],
     "RSSI (dBm)": round(scenario_results[key]["rssi"], 2) if scenario_results[key]["rssi"] is not None else None,
     "本次收包": scenario_results[key]["packet_success"]}
    for key, node in all_devices.items()
])
