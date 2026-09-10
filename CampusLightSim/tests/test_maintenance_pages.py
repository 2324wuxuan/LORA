"""使用临时数据库验证故障页面闭环及运维记录持久化。"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from streamlit.testing.v1 import AppTest
from database import db

ROOT = Path(__file__).resolve().parents[1]


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch.object(db, "DATABASE_PATH", Path(directory.name) / "test.db")
        patcher.start()
        self.addCleanup(patcher.stop)

    def button(self, app, label):
        return next(button for button in app.button if button.label == label)

    def test_inject_acknowledge_restore_and_refresh(self):
        app = AppTest.from_file(str(ROOT / "pages/07_故障告警.py")).run(timeout=30)
        self.assertFalse(app.exception)
        self.button(app, "注入故障").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertFalse(app.session_state.devices["CL-N01"]["online"])
        self.assertTrue(any(a["alarm_type"] == "node_offline" for a in db.get_alarms()))
        count = len(db.get_operation_logs())
        app.run()
        self.assertEqual(count, len(db.get_operation_logs()))
        self.button(app, "确认告警").click().run(timeout=30)
        self.assertTrue(db.get_alarms("ACKNOWLEDGED"))
        self.button(app, "恢复设备").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(any(a["status"] != "CLOSED" for a in db.get_alarms()))
        self.button(app, "继续检测（20个周期）").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertTrue(app.session_state.devices["CL-N01"]["online"])
        self.assertTrue(all(a["status"] == "CLOSED" for a in db.get_alarms()))
        self.assertIn("recovery_confirmed", {log["operation"] for log in db.get_operation_logs()})

    def test_all_injection_types_and_log_filter(self):
        app = AppTest.from_file(str(ROOT / "pages/07_故障告警.py")).run(timeout=30)
        for label, kind in [("LoRa信号衰减", "signal_attenuation"),
                            ("高丢包", "high_packet_loss"), ("传感器异常", "sensor_abnormal")]:
            app.selectbox[1].select(label).run()
            self.button(app, "注入故障").click().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertTrue(any(a["alarm_type"] == kind for a in db.get_alarms()))
        records = AppTest.from_file(str(ROOT / "pages/08_运维记录.py")).run(timeout=30)
        self.assertFalse(records.exception)
        self.assertEqual(len(records.dataframe[0].value), len(db.get_operation_logs()))
        records.selectbox[0].select("CL-N10").run()
        self.assertFalse(records.exception)
        self.assertEqual(len(records.dataframe), 0)

    def test_idempotent_operation_log(self):
        db.init_db()
        log = dict(log_id="once", device_id="CL-N10", operation="manual_control", result="SUCCESS")
        db.save_operation_log(log)
        db.save_operation_log(log)
        self.assertEqual(len(db.get_operation_logs("CL-N10")), 1)


if __name__ == "__main__":
    unittest.main()
