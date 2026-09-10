"""实验与测试页面：执行并导出系统验收用例。"""

from datetime import datetime
from time import perf_counter

import streamlit as st

from analysis.quality import run_quality_checks, save_results_csv
from config import TEST_RESULTS_CSV


st.title("🧪 实验与测试")
st.caption("质量检查单：用固定输入验证照明、控制、LoRa、告警和能耗模块")
st.info(
    "本页执行的是可重复的功能验收，不是展示预先写好的“通过”结果。每条记录都调用当前"
    "代码的公开接口，再把实际结果与预期值比较。检测使用独立对象，不修改当前设备、故障"
    "或业务数据库。"
)

test_date = st.date_input("测试日期", value=datetime.now().date(), key="quality_test_date")
run_clicked = st.button("运行全部质量检测", type="primary")

if run_clicked:
    executed_at = datetime.now()
    started_at = perf_counter()
    with st.spinner("正在调用照明、LoRa、告警和能耗模块进行检测……"):
        results = run_quality_checks(test_date)
        output_path = save_results_csv(results)
    elapsed_ms = (perf_counter() - started_at) * 1000
    st.session_state.quality_results = results
    st.session_state.quality_executed_at = executed_at
    st.session_state.quality_elapsed_ms = elapsed_ms
    st.session_state.quality_run_count = st.session_state.get("quality_run_count", 0) + 1
    st.session_state.quality_output_path = str(output_path)
    st.toast(f"第 {st.session_state.quality_run_count} 次质量检测执行完成")

results = st.session_state.get("quality_results")
if not results:
    st.warning("尚未执行检测。点击“运行全部质量检测”生成本次质量检查单。")
else:
    passed_count = sum(row["是否通过"] == "通过" for row in results)
    failed_count = len(results) - passed_count
    executed_at = st.session_state.quality_executed_at

    total_col, passed_col, failed_col, rate_col, elapsed_col = st.columns(5)
    total_col.metric("测试用例", len(results))
    passed_col.metric("通过", passed_count)
    failed_col.metric("失败", failed_count)
    rate_col.metric("通过率", f"{passed_count / len(results):.1%}")
    elapsed_col.metric("本次耗时", f"{st.session_state.quality_elapsed_ms:.2f} ms")

    if failed_count:
        st.error(f"本次检测有 {failed_count} 项失败，请根据表中的实际结果和判定依据排查。")
    else:
        st.success("本次 7 项功能验收全部通过。")

    st.caption(
        f"本会话第 {st.session_state.quality_run_count} 次执行 · "
        f"检测时间：{executed_at:%Y-%m-%d %H:%M:%S.%f}"
    )
    st.dataframe(results, width="stretch", hide_index=True)

    csv_bytes = TEST_RESULTS_CSV.read_bytes() if TEST_RESULTS_CSV.is_file() else b""
    st.download_button(
        "下载质量检查单 CSV",
        data=csv_bytes,
        file_name="test_results.csv",
        mime="text/csv",
    )
    st.caption(f"本地结果文件：{st.session_state.quality_output_path}")

with st.expander("七项测试分别证明什么"):
    st.markdown(
        "- **T01/T02**：教室自动照明在暗且有人时开灯，在自然光充足时关灯。\n"
        "- **T03**：MANUAL 模式能设置亮度，功率随亮度比例变化。\n"
        "- **T04**：LoRa 链路在严重衰减并低于灵敏度后会记录丢包。\n"
        "- **T05/T06**：弱信号和节点离线能被故障模块识别并产生对应告警。\n"
        "- **T07**：能耗模块正确完成 W、分钟到 kWh 的换算。"
    )
    st.caption("这些结果验证软件逻辑是否符合项目需求，不代表真实硬件已经通过现场测试。")
