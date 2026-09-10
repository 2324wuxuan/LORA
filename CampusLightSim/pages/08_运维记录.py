"""读取数据库运维记录并导出当前筛选结果。"""
import csv
from io import StringIO

import streamlit as st

from config import DEVICES, GATEWAYS
from database import db


db.init_db()
st.title("📝 运维记录")
st.caption("记录来自数据库，包含故障注入、告警确认、恢复请求、恢复验证及远程控制操作。")
all_logs = db.get_operation_logs()
device_ids = sorted(set(DEVICES) | set(GATEWAYS) | {row["device_id"] for row in all_logs})
selected = st.selectbox("按设备筛选", ["全部设备", *device_ids])
logs = all_logs if selected == "全部设备" else db.get_operation_logs(selected)
labels = {"timestamp": "时间", "device_id": "设备", "operation": "操作",
          "fault_type": "故障类型", "severity": "级别", "result": "结果", "description": "处理说明"}
operations = {"inject_fault": "注入故障", "recover_device": "恢复请求",
              "recovery_confirmed": "恢复验证通过", "acknowledge_alarm": "确认告警",
              "manual_control": "手动控制"}
results = {"SUCCESS": "成功", "FAILED": "失败", "PENDING": "待验证"}
rows = []
for log in logs:
    row = {title: log.get(key, "") for key, title in labels.items()}
    row["操作"] = operations.get(log["operation"], log["operation"])
    row["结果"] = results.get(log["result"], log["result"])
    rows.append(row)
if rows:
    st.dataframe(rows, hide_index=True)
else:
    st.info("当前筛选条件下暂无运维记录。")
output = StringIO(newline="")
writer = csv.DictWriter(output, fieldnames=list(labels.values()))
writer.writeheader()
writer.writerows(rows)
st.download_button("导出 CSV", output.getvalue().encode("utf-8-sig"),
                   file_name="operation_logs.csv", mime="text/csv", disabled=not rows)
