"""CampusLightSim 总入口：页面导航、会话初始化和系统首页。

运行方式：在项目目录执行 streamlit run app.py。
引擎负责推进仿真，页面负责展示；入口只装配公共状态和服务。
"""

from copy import deepcopy
from datetime import datetime
from functools import partial
from importlib import import_module
from importlib.util import find_spec

import streamlit as st

from config import (
    APP_ICON, APP_SUBTITLE, APP_TITLE, CAMPUS_PLANNING_AREAS, DEFAULT_EXPERIMENT_MODE,
    DEVICES, GATEWAYS, PROJECT_TITLE, RESEARCH_AREA,
    SIMULATION_POINTS_PER_DAY, SIMULATION_STEP_MINUTES, ZONES, validate_config,
)
from simulator.fault import FaultManager


def initialize_session() -> None:
    """仅补齐缺失状态；页面切换和控件重跑不重置时间、设备或故障。"""
    defaults = {
        "simulation_running": False,
        "simulation_time": datetime.now().replace(second=0, microsecond=0),
        "experiment_mode": DEFAULT_EXPERIMENT_MODE,
        "devices_initialized": False,
        "database_initialized": False,
        "engine_ready": False,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if "devices" not in st.session_state:
        # 这是设备初始状态快照；实际 VirtualLamp 对象由后续引擎创建。
        st.session_state.devices = {
            device_id: {
                **deepcopy(config), "device_id": device_id,
                "status": config["initial_status"],
                "mode": config["initial_mode"],
                "brightness": config["initial_brightness"],
            }
            for device_id, config in DEVICES.items()
        }
    st.session_state.devices_initialized = True
    if "gateways" not in st.session_state:
        st.session_state.gateways = deepcopy(GATEWAYS)
    else:
        for gateway_id, config in GATEWAYS.items():
            current = st.session_state.gateways.get(gateway_id, {})
            st.session_state.gateways[gateway_id] = {
                **deepcopy(config), "status": current.get("status", config["status"])}
    for device_id, device in st.session_state.devices.items():
        for key in ("x", "y", "height", "position_source"):
            device.setdefault(key, DEVICES[device_id][key])
    if "fault_manager" not in st.session_state:
        st.session_state.fault_manager = FaultManager()


def initialize_services() -> None:
    """接入现有公共接口；不执行仿真，不把尚未实现的服务标记为就绪。

    db.init_db 应为可重复调用的建表接口，每个会话成功后不再调用。
    引擎后续提供 run_simulation 后，页面可使用 session_state.engine_runner。
    """
    if not st.session_state.database_initialized:
        init_db = getattr(import_module("database.db"), "init_db", None)
        if callable(init_db):
            init_db()
            st.session_state.database_initialized = True
    if not st.session_state.engine_ready and find_spec("simulator.engine") is not None:
        runner = getattr(import_module("simulator.engine"), "run_simulation", None)
        if callable(runner):
            st.session_state.engine_runner = runner
            st.session_state.engine_ready = True


def render_home() -> None:
    st.title(f"{APP_ICON} {APP_TITLE}")
    st.markdown(f"### {APP_SUBTITLE}")
    st.caption(f"{PROJECT_TITLE} · {RESEARCH_AREA}")
    st.caption("500 × 750 m 校园 · 八个规划片区 · 三个 LoRa 网关形成三角布局，终端动态选路")

    status, mode, clock = st.columns(3)
    status.metric("系统当前状态", "仿真运行中" if st.session_state.simulation_running else "待机")
    mode.metric("当前实验模式", st.session_state.experiment_mode)
    clock.metric("当前仿真时间", st.session_state.simulation_time.strftime("%Y-%m-%d %H:%M"))
    st.caption("首次进入以当前时间初始化；后续仿真时间由仿真引擎推进。")

    areas, zones, devices, gateways, interval = st.columns(5)
    areas.metric("校园规划片区", len(CAMPUS_PLANNING_AREAS))
    zones.metric("代表仿真区域", len(ZONES))
    devices.metric("照明节点", len(st.session_state.devices))
    gateways.metric("虚拟网关", len(st.session_state.gateways))
    interval.metric("采样间隔", f"{SIMULATION_STEP_MINUTES} 分钟")

    st.subheader("系统准备情况")
    st.success("公共配置检查通过，设备初始状态与本会话故障管理器已准备。")
    st.write("数据库：" + ("已初始化" if st.session_state.database_initialized else "待接入"))
    st.write("仿真引擎：" + ("已接入" if st.session_state.engine_ready else "待接入"))
    st.info(
        "当前可查看校园地图、全校统一规划，以及全部代表节点的 Lux、Occupancy、"
        "智能照明和能耗仿真。所有节点参数均为仿真估算，仍需现场校准。"
    )

    st.subheader("项目功能")
    st.markdown(
        "- **区域与设备**：查看校园地图、八个规划片区和十个代表节点，并比较逐日仿真能耗。\n"
        "- **智能照明、LoRa 网络、远程控制**：自动调光、通信质量监测和手动控制。\n"
        "- **能耗分析**：比较传统照明与智能照明的能耗。\n"
        "- **故障告警、运维记录**：故障注入、告警确认、恢复验证与操作追踪。\n"
        "- **实验测试**：验证完整仿真流程与异常场景。"
    )
    st.subheader("使用说明")
    st.markdown(
        "1. 从左侧进入「区域与设备」，查看校园总体规划、代表节点和参数口径。\n"
        "2. 完整仿真功能开放后，通过功能页面运行实验并查看结果。\n"
        "3. 在故障页面注入和恢复故障，在运维记录中追踪处理过程。"
    )
    st.caption(
        f"仿真约定：24 小时每节点 {SIMULATION_POINTS_PER_DAY} 个采样点。"
        "设备与链路均为软件仿真；当前会话状态在浏览器会话结束后不保证保留。"
    )


def render_pending(title: str, description: str) -> None:
    """尚未实现的页面共用占位视图，不提供无效运行按钮。"""
    st.title(title)
    st.write(description)
    st.info("此功能页面正在建设中，请先从左侧查看「系统总览」或「区域与设备」。")


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon=APP_ICON, layout="wide")
    valid, errors = validate_config()
    if not valid:
        st.error("公共配置校验失败，请修正后重新加载。")
        for error in errors:
            st.write(f"- {error}")
        st.stop()
    initialize_session()
    try:
        initialize_services()
    except Exception as exc:
        st.error("公共服务初始化失败，请检查数据库或仿真引擎后重新加载。")
        st.exception(exc)
        st.stop()

    pages = [
        st.Page(render_home, title="系统总览", icon="🏠", default=True),
        st.Page("pages/02_区域与设备.py", title="区域与设备", icon="🏫", url_path="devices"),
        st.Page("pages/03_智能照明.py", title="智能照明", icon="💡", url_path="lighting"),
        st.Page("pages/04_LoRa网络.py", title="LoRa网络", icon="📡", url_path="lora"),
        st.Page("pages/06_能耗分析.py", title="能耗分析", icon="🔋", url_path="energy"),
        st.Page("pages/07_故障告警.py", title="故障告警", icon="🚨", url_path="faults"),
        st.Page("pages/08_运维记录.py", title="运维记录", icon="📝", url_path="operations"),
    ]
    # 远程控制使用独立页面；其他尚未实现模块继续保持原有占位逻辑。
    pages.append(
        st.Page("pages/05_远程控制.py", title="远程控制", icon="🎛️", url_path="control")
    )
    for title, path, description in [
        ("实验测试", "experiments", "运行仿真场景，检查系统功能。"),
    ]:
        pages.append(st.Page(partial(render_pending, title, description),
                             title=title, url_path=path))
    page = st.navigation(pages)
    with st.sidebar:
        st.caption(APP_SUBTITLE)
        st.caption(f"模式：{st.session_state.experiment_mode}")
        st.caption("状态：" + ("运行中" if st.session_state.simulation_running else "待机"))
    page.run()


if __name__ == "__main__":
    main()
