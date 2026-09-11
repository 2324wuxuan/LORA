"""Full deployment, independent classrooms, migration, and engine coverage."""
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
from config import DEVICES, ZONES, CAMPUS_PLANNING_AREAS
from control.lighting import auto_control, reset_state
from simulator.environment import get_environment
from simulator.engine import run_simulation
from simulator.fault import FaultManager
from database import db


class DeploymentTests(unittest.TestCase):
    def test_every_classroom_is_a_real_independent_node(self):
        rooms = [d for d in DEVICES.values() if d["plan_item_id"] == "MAIN-ROOM"]
        self.assertEqual(len(rooms), 100)
        self.assertEqual({d["floor"] for d in rooms}, set(range(1, 11)))
        for floor in range(1, 11):
            self.assertEqual(sum(d["floor"] == floor for d in rooms), 10)
        self.assertEqual(len({d["zone_id"] for d in rooms}), 100)
        self.assertTrue(all(d["fixture_count"] == 12 and d["rated_power_w"] == 432 for d in rooms))
        first, second = [d["zone_id"] for d in rooms[:2]]
        reset_state(first); reset_state(second)
        auto_control(first, 300, True)
        auto_control(second, 700, False)
        self.assertEqual(auto_control(first, 500, False), 100)
        self.assertEqual(auto_control(second, 500, True), 0)
        now = datetime(2026, 9, 9, 10)
        self.assertNotEqual(get_environment(first, now)["lux"], get_environment(second, now)["lux"])

    def test_inventory_and_sensor_identity(self):
        self.assertEqual(len(DEVICES), 1690)
        self.assertEqual(sum(d["fixture_count"] for d in DEVICES.values()), 8363)
        for key in ("zone_id", "lamp_id", "light_sensor_id", "presence_sensor_id"):
            self.assertEqual(len({d[key] for d in DEVICES.values()}), 1690)
        for area_id, area in CAMPUS_PLANNING_AREAS.items():
            self.assertEqual(sum(d["planning_area_id"] == area_id for d in DEVICES.values()), area["recommended_nodes"])

    def test_full_engine_step_and_fault_target_isolation(self):
        now = datetime(2026, 9, 9, 10)
        manager = FaultManager()
        target = "CL-MAIN-ROOM-0100"
        manager.inject_fault(target, "node_offline", timestamp=now)
        rows = run_simulation(now, hours=5/60, fault_manager=manager, persist=False)
        self.assertEqual(len(rows), 1690)
        self.assertEqual({row["device_id"] for row in rows}, set(DEVICES))
        self.assertFalse(next(row for row in rows if row["device_id"] == target)["packet_success"])
        self.assertTrue(any(a["device_id"] == target for a in manager.get_alarms()))
        self.assertFalse(any(a["device_id"] == "CL-N01" and a["alarm_type"] == "node_offline" for a in manager.get_alarms()))

    def test_migration_preserves_state_and_log_history(self):
        with TemporaryDirectory() as directory, patch.object(db, "DATABASE_PATH", Path(directory)/"test.db"):
            db.init_db()
            db.save_device(dict(device_id="CL-N01", mode="MANUAL", brightness=50, lamp_state=True))
            alarm = db.add_alarm("CL-N01", "low_rssi", "WARNING", "previous record")
            with db.get_connection() as conn:
                conn.execute("UPDATE devices SET deployment_version=NULL, rated_power=80 WHERE device_id='CL-N01'")
            conn.close()
            db.init_db()
            row = db.get_device("CL-N01")
            self.assertEqual((row["mode"], row["brightness"], row["rated_power"], row["power"]), ("MANUAL", 50, 432, 216))
            self.assertEqual(len(db.get_all_devices()), 1690)
            self.assertEqual(db.get_alarms()[0]["alarm_id"], alarm)

    def test_step_transaction_rolls_back_as_a_unit(self):
        with TemporaryDirectory() as directory, patch.object(db, "DATABASE_PATH", Path(directory)/"test.db"):
            db.init_db()
            original = db.get_device("CL-N01")["brightness"]
            with self.assertRaises(RuntimeError):
                with db.transaction():
                    db.save_device(dict(device_id="CL-N01", brightness=99))
                    raise RuntimeError("cancel step")
            self.assertEqual(db.get_device("CL-N01")["brightness"], original)

    def test_full_step_persists_all_circuits(self):
        with TemporaryDirectory() as directory, patch.object(db, "DATABASE_PATH", Path(directory)/"test.db"):
            rows = run_simulation(datetime(2026, 9, 9, 10), hours=5/60, persist=True)
            saved = db.get_all_devices()
            self.assertEqual(len(rows), 1690)
            self.assertEqual(len(saved), 1690)
            self.assertEqual(db.get_device("CL-MAIN-ROOM-0100")["rated_power"], 432)
            self.assertTrue(all(row["zone"] in {z["name"] for z in ZONES.values()} for row in saved))


if __name__ == "__main__":
    unittest.main()
