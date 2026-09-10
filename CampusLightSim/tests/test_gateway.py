"""三网关规划、链路选择及故障切换回归测试。"""
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from config import AREA_GATEWAY_PLAN, CAMPUS_PLANNING_AREAS, DEVICES, GATEWAYS, validate_config
from database import db
from simulator.device import VirtualLightingNode
from simulator.fault import FaultManager
from simulator.gateway import LoRaGateway, select_gateway
from simulator.lora import calculate_link


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.device = {**DEVICES["CL-N05"], "device_id": "CL-N05"}
        self.now = datetime(2026, 9, 10, 10)

    def test_configuration(self):
        self.assertEqual(len(GATEWAYS), 3)
        self.assertEqual(len(CAMPUS_PLANNING_AREAS), 8)
        self.assertEqual(len(DEVICES), 10)
        self.assertEqual(AREA_GATEWAY_PLAN["PA07"]["primary"], [])
        self.assertEqual([(g["x"], g["y"], g["height"]) for g in GATEWAYS.values()],
                         [(250, 220, 25), (145, 520, 22), (355, 520, 25)])
        valid, errors = validate_config()
        self.assertTrue(valid, errors)

    def test_best_rssi_repeatability_and_independent_streams(self):
        result = select_gateway(self.device, timestamp=self.now)
        self.assertEqual(result, select_gateway(self.device, timestamp=self.now))
        self.assertEqual(result["gateway_id"], "GW-01")
        self.assertEqual(result["rssi"], max(x["rssi"] for x in result["gateway_links"].values()))
        gateways = deepcopy(GATEWAYS)
        gateways["GW-01"]["status"] = "OFFLINE"
        fallback = select_gateway(self.device, gateways, timestamp=self.now)
        self.assertNotEqual(fallback["gateway_id"], "GW-01")
        self.assertEqual(fallback["gateway_links"]["GW-02"], result["gateway_links"]["GW-02"])
        for gateway in gateways.values():
            gateway["status"] = "OFFLINE"
        self.assertIsNone(select_gateway(self.device, gateways)["gateway_id"])

    def test_road_position_selects_different_gateways(self):
        for x, y, expected in [(250, 0, "GW-01"), (0, 520, "GW-02"), (500, 520, "GW-03")]:
            device = {**DEVICES["CL-N09"], "device_id": "CL-N09", "x": x, "y": y}
            self.assertEqual(select_gateway(device, shadowing=False)["gateway_id"], expected)

    def test_path_loss_and_no_radius_cutoff(self):
        first = calculate_link(self.device, "GW-01", GATEWAYS["GW-01"], shadowing=False)
        faded = calculate_link(self.device, "GW-01", GATEWAYS["GW-01"],
                               shadowing=False, extra_loss_db=25)
        self.assertAlmostEqual(first["rssi"] - faded["rssi"], 25)
        self.assertAlmostEqual(first["snr"] - faded["snr"], 25)
        self.assertIsNone(select_gateway(self.device, extra_loss_db=200)["gateway_id"])

    def test_fault_handover_does_not_close_failed_gateway_alarm(self):
        manager = FaultManager()
        telemetry = {"lux": 300.0}
        manager.inject_fault("GW-01", "gateway_offline", timestamp=self.now)
        result = manager.sample_network(self.device, telemetry, timestamp=self.now,
                                        auto_control_ok=True)
        self.assertNotEqual(result["device"]["gateway_id"], "GW-01")
        alarm = next(a for a in result["alarms"] if a["device_id"] == "GW-01")
        self.assertEqual(alarm["status"], "OPEN")
        manager.recover_device("GW-01", timestamp=self.now)
        for index in range(1, 25):
            result = manager.sample_network(self.device, telemetry,
                                            timestamp=self.now + timedelta(minutes=5*index),
                                            auto_control_ok=True)
        self.assertEqual(next(a for a in result["alarms"] if a["device_id"] == "GW-01")["status"], "CLOSED")
        for key in GATEWAYS:
            manager.inject_fault(key, "gateway_offline", timestamp=self.now)
        for index in range(25, 28):
            result = manager.sample_network(self.device, telemetry,
                                            timestamp=self.now + timedelta(minutes=5*index))
        self.assertEqual(result["device"]["status"], "OFFLINE")
        self.assertIsNone(result["device"]["gateway_id"])
        self.assertEqual(len([a for a in result["alarms"] if a["alarm_type"] == "gateway_offline"
                              and a["status"] == "OPEN"]), 3)

    def test_device_association_and_database_migration(self):
        with TemporaryDirectory() as directory, patch.object(db, "DATABASE_PATH", Path(directory) / "old.db"):
            db.init_db()
            db.save_device({"device_id": "CL-N05", "brightness": 73})
            alarm_id = db.add_alarm("GW-01", "gateway_offline", "CRITICAL", "旧告警")
            with db._connection() as conn:
                conn.execute("ALTER TABLE devices DROP COLUMN gateway_id")
                conn.execute("ALTER TABLE devices DROP COLUMN height")
                conn.execute("UPDATE devices SET distance=220, x=NULL, y=NULL")
            db.init_db()
            self.assertEqual(db.get_device("CL-N05")["brightness"], 73)
            self.assertIsNone(db.get_device("CL-N05")["distance"])
            self.assertEqual(db.get_alarms()[0]["alarm_id"], alarm_id)
            node = VirtualLightingNode.from_config("CL-N05")
            result = select_gateway(node.to_dict(), timestamp=self.now)
            node.update_link(result)
            db.save_device(node)
            self.assertEqual(db.get_device("CL-N05")["gateway_id"], result["gateway_id"])
            self.assertTrue(LoRaGateway("GW-01").receive({**result, "packet_success": True})["accepted"])
            node.update_link({"gateway_id": None})
            self.assertIsNone(node.distance)


if __name__ == "__main__":
    unittest.main()
