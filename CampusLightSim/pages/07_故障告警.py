"""故障操作页面；检测及恢复验证委托给现有 engine / FaultManager。"""
from datetime import timedelta

import streamlit as st

from app import initialize_session
from config import DEVICES, SIMULATION_STEP_MINUTES
from control.lighting import reset_state
from database import db
from simulator.device import VirtualLightingNode
from simulator.engine import simulate_step


initialize_session()
db.init_db()
manager = st.session_state.fault_manager
if "maintenance_results" not in st.session_state:
    st.session_state.maintenance_results = {}
if "maintenance_nodes" not in st.session_state:
    st.session_state.maintenance_nodes = {}


def persist_events():
    for alarm in manager.get_alarms():
        db.save_alarm(alarm)
    for log in manager.get_operation_logs():
        db.save_operation_log(log)


def detect(device_id, cycles=1):
    current = st.session_state.devices[device_id]
    if device_id not in st.session_state.maintenance_nodes:
        node = VirtualLightingNode.from_config(device_id)
        node.set_online(current.get("online", current.get("status") == "ONLINE"))
        st.session_state.maintenance_nodes[device_id] = node
    node = st.session_state.maintenance_nodes[device_id]
    node.set_mode(current.get("mode", "AUTO"))
    node.set_brightness(current.get("brightness", 0))
    reset_state(DEVICES[device_id]["zone_id"])
    for _ in range(cycles):
        timestamp = manager.next_sample_time(device_id, st.session_state.simulation_time
                                              + timedelta(minutes=SIMULATION_STEP_MINUTES))
        result = simulate_step(node, DEVICES[device_id]["zone_id"], timestamp,
                               fault_manager=manager, gateways=st.session_state.gateways)
        st.session_state.simulation_time = timestamp
        st.session_state.maintenance_results[device_id] = result
        telemetry = result["telemetry"]
        online = result["device"]["status"] == "ONLINE"
        current.update(online=online, status=result["device"]["status"],
                       gateway_id=telemetry.get("gateway_id"),
                       brightness=node.brightness, power=node.power)
        active = [a for a in result["alarms"] if a["device_id"] == device_id and a["status"] != "CLOSED"]
        snapshot = {"device_id": device_id, "online": online,
                    "gateway_id": telemetry.get("gateway_id"),
                    "fault": bool(active), "fault_type": ",".join(a["alarm_type"] for a in active),
                    "updated_at": timestamp}
        if result["accept_telemetry"]:
            snapshot.update(node.to_dict(), online=online, lux=telemetry["lux"],
                            rssi=telemetry["rssi"], snr=telemetry["snr"],
                            packet_loss=1-telemetry["pdr"])
        db.save_device(snapshot)
    persist_events()
    return result


st.title("🚨 故障告警")
st.caption("全部十个节点均可注入故障。按钮推进实际采样周期；刷新页面不会重复采样。")
st.subheader("当前告警")
alarm_panel = st.container()

st.subheader("故障注入与恢复")
device_id = st.selectbox("选择节点", list(DEVICES),
                         format_func=lambda key: f"{key} · {DEVICES[key]['device_name']}")
options = {"节点离线": "node_offline", "LoRa信号衰减": "signal_attenuation",
           "高丢包": "high_packet_loss", "传感器异常": "sensor_abnormal"}
label = st.selectbox("故障类型", list(options))
st.caption("信号衰减增加 25 dB 路径损耗；高丢包增加 40% 丢包概率；传感器异常使用 -1 Lux。")
inject, recover, check = st.columns(3)
try:
    if inject.button("注入故障", type="primary"):
        manager.inject_fault(device_id, options[label], timestamp=st.session_state.simulation_time)
        persist_events()
        detect(device_id)
        st.success("已注入并完成一次检测，下方显示最新数据。")
    if recover.button("恢复设备"):
        manager.recover_device(device_id, timestamp=st.session_state.simulation_time)
        st.session_state.devices[device_id].update(online=True, status="ONLINE")
        if device_id in st.session_state.maintenance_nodes:
            st.session_state.maintenance_nodes[device_id].set_online(True)
        persist_events()
        result = detect(device_id)
        if result["recovered"]:
            st.success("恢复验证通过，相关告警已关闭。")
        else:
            st.warning("已撤销故障，恢复验证尚未通过。请继续检测；手动模式下需先切回 AUTO 才能验证自动控制。")
    if check.button("继续检测（20个周期）"):
        result = detect(device_id, 20)
        st.info("已完成 20 个实际采样周期，PDR 按收包结果统计，未强制修改为正常值。")
except Exception as exc:
    st.error(f"操作或保存未完成：{exc}")
    st.stop()

result = st.session_state.maintenance_results.get(device_id)
if result:
    data = result["telemetry"]
    st.subheader(f"{device_id} 最新检测结果")
    a, b, c, d = st.columns(4)
    a.metric("节点状态", result["device"]["status"])
    b.metric("Lux", str(data["lux"]))
    c.metric("RSSI", f"{data['rssi']:.1f} dBm" if data.get("rssi") is not None else "无可达链路")
    d.metric("最近窗口 PDR", f"{data['pdr']:.0%}")
    st.caption(f"采样时间：{data['timestamp']} · 自动控制验证：{'通过' if result['recovered'] else '未确认恢复'}")
    if result.get("gateway_links"):
        st.dataframe(list(result["gateway_links"].values()), hide_index=True)
else:
    st.info("尚无该节点的故障检测结果。注入故障或继续检测后显示实际数据。")

with alarm_panel:
    alarms = [a for a in db.get_alarms() if a["status"] != "CLOSED"]
    if not alarms:
        st.success("当前没有未关闭告警。")
    local_ids = {a["alarm_id"] for a in manager.get_alarms()}
    for alarm in alarms:
        icon = "🔴" if alarm["severity"] == "CRITICAL" else "🟠"
        st.write(f"{icon} **{alarm['severity']} · {alarm['device_id']}** — {alarm['message']}")
        st.caption(f"{alarm['timestamp']} · {alarm['status']}")
        if alarm["status"] == "OPEN" and st.button("确认告警", key=f"ack_{alarm['alarm_id']}"):
            if alarm["alarm_id"] in local_ids:
                manager.acknowledge_alarm(alarm["alarm_id"], timestamp=st.session_state.simulation_time)
                persist_events()
            else:
                db.update_alarm_status(alarm["alarm_id"], "ACKNOWLEDGED")
                db.save_operation_log(dict(device_id=alarm["device_id"], operation="acknowledge_alarm",
                                           fault_type=alarm["alarm_type"], severity=alarm["severity"],
                                           result="SUCCESS", description="确认数据库历史告警"))
            st.rerun()
    st.caption("数据库保留历史告警；其他会话的告警不会因本会话点击恢复而自动关闭。")
