"""使用临时数据库验证持久化及现有模块兼容性。"""
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from config import DEVICES
from database import db
from simulator.device import VirtualLightingNode
from simulator.fault import check_fault


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "nested" / "campus.db"
        patcher = patch.object(db, "DATABASE_PATH", self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        db.init_database()

    def test_device_persistence_and_idempotent_initialization(self):
        node = VirtualLightingNode.from_config("CL-N01")
        db.save_device(node)
        db.init_db()
        self.assertTrue(self.path.is_file())
        saved = db.get_device(node.device_id)
        for key, value in node.to_dict().items():
            self.assertEqual(saved[key], value)
        self.assertEqual(saved["area"], node.zone)
        self.assertIsNone(saved["rssi"])
        node.set_brightness(50)
        node.turn_on()
        db.save_device(node.to_dict())
        db.save_device({"device_id": node.device_id, "rssi": -110})
        self.assertEqual(len(db.get_all_devices()), len(DEVICES))
        self.assertEqual(db.get_device(node.device_id)["power"], 40)
        self.assertEqual(db.get_device(node.device_id)["rssi"], -110)
        self.assertTrue(db.delete_device(node.device_id))
        self.assertFalse(db.delete_device(node.device_id))
        self.assertIsNone(db.get_device(node.device_id))

    def test_fault_snapshots_update_without_duplicates(self):
        alarm = check_fault({"device_id": "CL-N01", "online": False}, None)[0]
        db.save_alarm(alarm)
        alarm.update(status="CLOSED", recovered_at=datetime(2026, 9, 9, 12))
        db.save_alarm(alarm)
        saved, = db.get_alarms("CLOSED")
        self.assertEqual(saved["alarm_id"], alarm["alarm_id"])
        self.assertEqual(saved["severity"], alarm["severity"])
        self.assertEqual(saved["fault_type"], alarm["alarm_type"])
        self.assertEqual(saved["recovered_at"], "2026-09-09 12:00:00")
        self.assertEqual(db.get_alarms("OPEN"), [])

    def test_alarm_crud_and_parameter_binding(self):
        target = "GW-01'; DROP TABLE devices; --"
        alarm_id = db.add_alarm(target, "gateway_offline", "CRITICAL", "网关离线")
        self.assertEqual(db.get_alarms(device_id=target)[0]["device_id"], target)
        self.assertEqual(len(db.get_all_devices()), len(DEVICES))
        self.assertTrue(db.update_alarm_status(alarm_id, "ACKNOWLEDGED"))
        self.assertFalse(db.update_alarm_status("missing", "CLOSED"))
        with self.assertRaises(ValueError):
            db.update_alarm_status(alarm_id, "invalid")
        self.assertEqual(db.get_alarms()[0]["status"], "ACKNOWLEDGED")
        self.assertTrue(db.delete_alarm(alarm_id))
        self.assertEqual(db.get_alarms(), [])

    def test_maintenance_crud_and_history_retention(self):
        db.save_device({"device_id": "CL-N01", "area": "教学楼"})
        record_id = db.add_maintenance_record("CL-N01", "灯不亮", "排查线路", "张三", "PENDING")
        db.add_maintenance_record("CL-N02", "信号弱", "调整天线", "李四")
        self.assertTrue(db.update_maintenance_record(record_id, solution="更换驱动", status="COMPLETED"))
        db.delete_device("CL-N01")
        record, = db.get_maintenance_records("CL-N01")
        self.assertEqual(record["solution"], "更换驱动")
        self.assertEqual(len(db.get_maintenance_records()), 2)
        self.assertTrue(db.delete_maintenance_record(record_id))
        self.assertFalse(db.delete_maintenance_record(record_id))


if __name__ == "__main__":
    unittest.main()
