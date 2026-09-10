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
left.metric("全部网关在线时选择", normal["gateway_id"] or "无可达网关")
right.metric("对照场景选择", scenario["gateway_id"] or "无可达网关")
st.dataframe([
    {"网关": key, "名称": GATEWAYS[key]["name"],
     "在线": link["online"], "距离 (m)": round(link["distance_m"], 1),
     "RSSI (dBm)": round(link["rssi"], 2), "SNR (dB)": round(link["snr"], 2),
     "模型丢包概率": round(link["packet_loss_probability"], 3),
     "可达": link["reachable"], "本次收包": link["packet_success"],
     "选中": scenario["gateway_id"] == key}
    for key, link in scenario["gateway_links"].items()
])
st.caption("选路先比较可达在线网关的 RSSI，再使用所选链路的收包结果；模型丢包概率不等于实测 PDR。")

st.subheader("全校节点与三网关拓扑")
st.caption("所有节点使用相同样式；外圈表示当前查看的节点。连线表示该场景的最优网关关联，不代表本次收包成功。灰色节点无可达网关。")
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
    parts.append(f'<text x="{node["x"] + dx}" y="{node["y"] + dy}" '
                 f'text-anchor="{anchor}" font-size="12" fill="currentColor">{key}</text></g>')
parts.append('</svg>')
st.markdown("".join(parts), unsafe_allow_html=True)

st.subheader("全部节点链路汇总")
st.dataframe([
    {"节点": key, "名称": node["device_name"],
     "片区": f"{node['planning_area_id']} · {CAMPUS_PLANNING_AREAS[node['planning_area_id']]['name']}",
     "正常网关": normal_results[key]["gateway_id"] or "无可达网关",
     "场景网关": scenario_results[key]["gateway_id"] or "无可达网关",
     "发生切换": normal_results[key]["gateway_id"] != scenario_results[key]["gateway_id"],
     "RSSI (dBm)": round(scenario_results[key]["rssi"], 2) if scenario_results[key]["rssi"] is not None else None,
     "本次收包": scenario_results[key]["packet_success"]}
    for key, node in all_devices.items()
])
