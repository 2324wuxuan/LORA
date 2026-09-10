"""校园全覆盖远程照明控制页面。

控制对象直接来自 config.py / app.py 的十个代表仿真节点：
CL-N01 ~ CL-N10，覆盖 PA01 ~ PA08 八个校园规划片区。
页面控制的是当前 Streamlit 会话中的 st.session_state.devices。
"""

from datetime import datetime

import streamlit as st

from config import CAMPUS_PLANNING_AREAS, DEVICES, SYSTEM, ZONES


st.title("🎛️ 远程照明控制")
st.caption("校园全覆盖 · 8 个规划片区 · 10 个代表照明节点")
st.divider()


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "devices" not in st.session_state:
    st.session_state.devices = {
        device_id: {
            **config,
            "device_id": device_id,
            "status": config.get("initial_status", "ONLINE"),
            "mode": config.get("initial_mode", SYSTEM["default_mode"]),
            "brightness": config.get("initial_brightness", 0),
        }
        for device_id, config in DEVICES.items()
    }

if "operation_logs" not in st.session_state:
    st.session_state.operation_logs = []


def device_power(device: dict) -> float:
    """按额定功率和当前亮度计算仿真功率。"""
    rated = float(device.get("rated_power_w", 0))
    brightness = float(device.get("brightness", 0))
    return rated * brightness / 100.0


def is_online(device: dict) -> bool:
    return str(device.get("status", "ONLINE")).upper() == "ONLINE"


def log_operation(device_id: str, operation: str, result: str = "SUCCESS") -> None:
    st.session_state.operation_logs.insert(
        0,
        {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "device_id": device_id,
            "operation": operation,
            "result": result,
        },
    )
    st.session_state.operation_logs = st.session_state.operation_logs[:100]


def set_mode(device_id: str, mode: str) -> None:
    device = st.session_state.devices[device_id]
    device["mode"] = mode
    log_operation(device_id, f"切换控制模式 → {mode}")


def set_brightness(device_id: str, brightness: int) -> None:
    device = st.session_state.devices[device_id]
    brightness = max(
        int(SYSTEM["brightness_min"]),
        min(int(SYSTEM["brightness_max"]), int(brightness)),
    )
    device["brightness"] = brightness
    device["mode"] = "MANUAL"
    log_operation(device_id, f"远程设置亮度 → {brightness}%")


def remote_on(device_id: str) -> None:
    device = st.session_state.devices[device_id]
    device["brightness"] = 100
    device["mode"] = "MANUAL"
    log_operation(device_id, "远程开灯 → 100%")


def remote_off(device_id: str) -> None:
    device = st.session_state.devices[device_id]
    device["brightness"] = 0
    device["mode"] = "MANUAL"
    log_operation(device_id, "远程关灯 → 0%")


# ---------------------------------------------------------------------------
# Campus-wide overview
# ---------------------------------------------------------------------------
st.subheader("🏫 校园全覆盖设备总览")

total_devices = len(st.session_state.devices)
online_devices = sum(is_online(d) for d in st.session_state.devices.values())
auto_devices = sum(d.get("mode") == "AUTO" for d in st.session_state.devices.values())
manual_devices = sum(d.get("mode") == "MANUAL" for d in st.session_state.devices.values())
total_power = sum(device_power(d) for d in st.session_state.devices.values())

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("规划片区", len(CAMPUS_PLANNING_AREAS))
c2.metric("代表区域", len(ZONES))
c3.metric("照明节点", total_devices)
c4.metric("在线节点", f"{online_devices}/{total_devices}")
c5.metric("当前总功率", f"{total_power:.1f} W")

st.caption(
    f"AUTO：{auto_devices} 个　|　MANUAL：{manual_devices} 个　|　"
    "控制对象为校园全覆盖规划下的代表仿真节点。"
)

st.divider()

# ---------------------------------------------------------------------------
# Filters: planning area -> zone -> node
# ---------------------------------------------------------------------------
st.subheader("🔎 选择校园控制对象")

area_options = ["全部规划片区"] + [
    f"{area_id} · {area['name']}"
    for area_id, area in CAMPUS_PLANNING_AREAS.items()
]

selected_area_label = st.selectbox("规划片区", area_options)

if selected_area_label == "全部规划片区":
    allowed_area_ids = set(CAMPUS_PLANNING_AREAS.keys())
else:
    selected_area_id = selected_area_label.split(" · ", 1)[0]
    allowed_area_ids = {selected_area_id}

allowed_device_ids = [
    device_id
    for device_id, device in st.session_state.devices.items()
    if device.get("planning_area_id") in allowed_area_ids
]

if not allowed_device_ids:
    st.warning("当前筛选条件下没有可控制节点。")
    st.stop()

device_options = [
    f"{device_id} · {st.session_state.devices[device_id].get('device_name', '')}"
    for device_id in allowed_device_ids
]

selected_device_label = st.selectbox("代表照明节点", device_options)
selected_device_id = selected_device_label.split(" · ", 1)[0]
device = st.session_state.devices[selected_device_id]

zone_id = device["zone_id"]
zone = ZONES[zone_id]
area_id = device["planning_area_id"]
area = CAMPUS_PLANNING_AREAS[area_id]

# ---------------------------------------------------------------------------
# Selected device details
# ---------------------------------------------------------------------------
st.divider()
st.subheader(f"🎯 当前控制：{selected_device_id}")

d1, d2, d3, d4, d5 = st.columns(5)
d1.metric("规划片区", area_id)
d2.metric("区域", zone_id)
d3.metric("控制模式", device.get("mode", "AUTO"))
d4.metric("当前亮度", f"{float(device.get('brightness', 0)):.0f}%")
d5.metric("当前功率", f"{device_power(device):.1f} W")

st.write(f"**片区：** {area['name']}")
st.write(f"**区域：** {zone['name']}　—　{zone['location']}")
st.write(f"**设备：** {device.get('device_name', selected_device_id)}")
st.write(f"**照明策略：** {zone.get('control_mode', '未配置')}")
st.write(f"**网关规划：** {area.get('gateway_plan', '未配置')}")
st.write(f"**参数口径：** {device.get('parameter_source', '未标注')}")

st.divider()

# ---------------------------------------------------------------------------
# Control buttons
# ---------------------------------------------------------------------------
st.markdown("### ⚙️ 控制模式")

m1, m2 = st.columns(2)

with m1:
    if st.button("🤖 AUTO 自动控制", use_container_width=True):
        set_mode(selected_device_id, "AUTO")
        st.success(f"{selected_device_id} 已切换为 AUTO")
        st.rerun()

with m2:
    if st.button("🖐️ MANUAL 手动控制", use_container_width=True):
        set_mode(selected_device_id, "MANUAL")
        st.success(f"{selected_device_id} 已切换为 MANUAL")
        st.rerun()

st.markdown("### 💡 快速开关")

b1, b2 = st.columns(2)

with b1:
    if st.button("🔆 远程开灯（100%）", use_container_width=True):
        remote_on(selected_device_id)
        st.success(f"{selected_device_id} 已开启")
        st.rerun()

with b2:
    if st.button("🌙 远程关灯（0%）", use_container_width=True):
        remote_off(selected_device_id)
        st.success(f"{selected_device_id} 已关闭")
        st.rerun()

st.markdown("### 🎚️ 手动亮度")

current_brightness = int(float(device.get("brightness", 0)))
brightness = st.slider(
    "目标亮度",
    min_value=int(SYSTEM["brightness_min"]),
    max_value=int(SYSTEM["brightness_max"]),
    value=current_brightness,
    step=5,
    format="%d%%",
)

preview_power = float(device.get("rated_power_w", 0)) * brightness / 100.0
p1, p2 = st.columns(2)
p1.metric("目标亮度", f"{brightness}%")
p2.metric("预计功率", f"{preview_power:.1f} W")

if st.button("📡 发送远程控制指令", type="primary", use_container_width=True):
    set_brightness(selected_device_id, brightness)
    st.success(
        f"控制指令已发送：{selected_device_id} → {brightness}% "
        f"（MANUAL）"
    )
    st.rerun()

st.divider()

# ---------------------------------------------------------------------------
# All-campus control table
# ---------------------------------------------------------------------------
st.subheader("🗺️ 全校园节点控制状态")

campus_rows = []
for device_id, item in st.session_state.devices.items():
    item_area_id = item.get("planning_area_id", "")
    item_zone_id = item.get("zone_id", "")
    item_area = CAMPUS_PLANNING_AREAS.get(item_area_id, {})
    item_zone = ZONES.get(item_zone_id, {})
    campus_rows.append(
        {
            "片区": item_area_id,
            "片区名称": item_area.get("name", ""),
            "区域": item_zone_id,
            "区域名称": item_zone.get("name", ""),
            "设备": device_id,
            "模式": item.get("mode", "AUTO"),
            "状态": item.get("status", "ONLINE"),
            "亮度": f"{float(item.get('brightness', 0)):.0f}%",
            "功率(W)": round(device_power(item), 1),
            "网络": item.get("primary_network", "LoRaWAN"),
        }
    )

st.dataframe(
    campus_rows,
    use_container_width=True,
    hide_index=True,
)

st.divider()

# ---------------------------------------------------------------------------
# Area summary
# ---------------------------------------------------------------------------
st.subheader("📊 八个规划片区控制概况")

area_rows = []
for area_id, area_info in CAMPUS_PLANNING_AREAS.items():
    ids = [
        device_id
        for device_id, item in st.session_state.devices.items()
        if item.get("planning_area_id") == area_id
    ]
    area_power = sum(device_power(st.session_state.devices[i]) for i in ids)
    area_online = sum(is_online(st.session_state.devices[i]) for i in ids)
    area_manual = sum(
        st.session_state.devices[i].get("mode") == "MANUAL" for i in ids
    )
    area_rows.append(
        {
            "片区": area_id,
            "片区名称": area_info["name"],
            "代表节点": len(ids),
            "在线": f"{area_online}/{len(ids)}",
            "手动控制": area_manual,
            "当前功率(W)": round(area_power, 1),
            "建议部署节点": area_info.get("recommended_nodes", ""),
            "网关规划": area_info.get("gateway_plan", ""),
        }
    )

st.dataframe(
    area_rows,
    use_container_width=True,
    hide_index=True,
)

st.divider()

# ---------------------------------------------------------------------------
# Operation log
# ---------------------------------------------------------------------------
st.subheader("📝 最近远程操作记录")

if st.session_state.operation_logs:
    st.dataframe(
        st.session_state.operation_logs[:30],
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("暂无远程控制操作记录。")

st.caption(
    "说明：当前页面控制的是校园全覆盖规划中的 10 个代表仿真节点，"
    "分别覆盖 Z01～Z10 / PA01～PA08。"
    "实际大规模部署数量由 config.py 中各规划片区的 recommended_nodes 表示；"
    "代表节点用于软件仿真和控制链路验证。"
)
