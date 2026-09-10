"""故障标准边界、注入影响及恢复生命周期验证。"""
import unittest
from datetime import datetime, timedelta

from simulator.fault import FaultManager, check_fault, is_valid_lux


class FaultTests(unittest.TestCase):
    def setUp(self):
        self.manager = FaultManager(seed=42)
        self.now = datetime(2026, 9, 9, 10)
        self.device = {"device_id": "CL-N01", "status": "ONLINE"}
        self.data = {"lux": 300.0, "rssi": -95.0, "snr": 5.0,
                     "packet_success": True, "brightness": 100, "power": 80}

    def sample(self, **kwargs):
        self.now += timedelta(minutes=5)
        return self.manager.sample(self.device, self.data, timestamp=self.now, **kwargs)

    def types(self, **changes):
        return {a["alarm_type"] for a in check_fault(self.device, {**self.data, **changes})}

    def test_thresholds(self):
        for rssi, expected in [(-114.9, set()), (-115, {"low_rssi"}),
                               (-120, {"very_low_rssi"}), (-121, {"very_low_rssi"})]:
            self.assertEqual(self.types(rssi=rssi), expected)
        for pdr, expected in [(0.9, set()), (0.899, {"low_pdr"}),
                              (0.8, {"low_pdr"}), (0.799, {"very_low_pdr"})]:
            self.assertEqual(self.types(pdr=pdr), expected)
        with self.assertRaises(ValueError):
            self.types(pdr=90)

    def test_sensor_boundaries(self):
        for lux in [0, 99999, 100000]:
            self.assertTrue(is_valid_lux(lux))
        for lux in [-1, 100001, float("nan"), float("inf"), None, "bad"]:
            self.assertIn("sensor_abnormal", self.types(lux=lux))

    def test_offline_and_verified_recovery(self):
        baseline = self.sample()["latest_telemetry"]
        self.manager.inject_fault("CL-N01", "node_offline", timestamp=self.now)
        result = self.sample()
        self.assertEqual(result["device"]["status"], "OFFLINE")
        self.assertFalse(result["accept_telemetry"])
        self.assertEqual(result["latest_telemetry"], baseline)
        alarm = next(a for a in result["alarms"] if a["alarm_type"] == "node_offline")
        self.assertEqual(alarm["severity"], "CRITICAL")
        self.manager.acknowledge_alarm(alarm["alarm_id"], timestamp=self.now)
        self.manager.recover_device("CL-N01", timestamp=self.now)
        self.sample()
        self.assertTrue(self.manager.get_alarms("ACKNOWLEDGED"))
        for _ in range(20):
            result = self.sample(auto_control_ok=True)
        self.assertTrue(result["recovered"])
        self.assertTrue(all(a["status"] == "CLOSED" for a in result["alarms"]))
        self.assertIn("recovery_confirmed", {x["operation"] for x in self.manager.get_operation_logs()})

    def test_three_missing_cycles_and_duplicate_time(self):
        for index in range(3):
            self.now += timedelta(minutes=5)
            result = self.manager.sample(self.device, None, timestamp=self.now)
            offline = [a for a in result["alarms"] if a["alarm_type"] == "node_offline"]
            self.assertEqual(bool(offline), index == 2)
        with self.assertRaises(ValueError):
            self.manager.sample(self.device, None, timestamp=self.now)

    def test_signal_overlay_does_not_mutate_input(self):
        self.manager.inject_fault("CL-N01", "signal_attenuation")
        result = self.sample()
        self.assertEqual(result["telemetry"]["rssi"], -120)
        self.assertEqual(self.data["rssi"], -95)
        self.assertIn("very_low_rssi", {a["alarm_type"] for a in result["alarms"]})
        self.assertEqual(len(self.sample()["alarms"]), 2)  # 注入提示与实际信号阈值告警

    def test_packet_loss_is_observed_and_recovers(self):
        self.manager.inject_fault("CL-N01", "high_packet_loss")
        received = sum(self.sample()["telemetry"]["packet_success"] for _ in range(1000))
        self.assertGreater(received, 550)
        self.assertLess(received, 650)
        self.assertTrue(any(a["alarm_type"] == "very_low_pdr" for a in self.manager.get_alarms()))
        self.manager.recover_device("CL-N01", timestamp=self.now)
        for _ in range(20):
            result = self.sample(auto_control_ok=True)
        self.assertEqual(result["telemetry"]["pdr"], 1)
        self.assertTrue(result["recovered"])

    def test_sensor_guard_and_partial_recovery(self):
        self.manager.inject_fault("CL-N01", "sensor_abnormal")
        self.manager.inject_fault("CL-N01", "signal_attenuation")
        self.assertFalse(self.manager.apply_sensor("CL-N01", self.data)["sensor_valid"])
        self.assertFalse(self.sample()["accept_telemetry"])
        self.manager.recover_device("CL-N01", "sensor_abnormal", timestamp=self.now)
        self.assertFalse(self.sample(auto_control_ok=True)["recovered"])
        self.manager.inject_fault("CL-N01", "sensor_abnormal", value=99999)
        self.assertFalse(self.manager.apply_sensor("CL-N01", self.data)["sensor_valid"])

    def test_gateway_shared_alarm_and_recovery(self):
        self.manager.inject_fault("GW-01", "gateway_offline", timestamp=self.now)
        for device_id in ["CL-N01", "CL-N02", "CL-N03"]:
            result = self.manager.sample({"device_id": device_id}, self.data, timestamp=self.now)
            self.assertFalse(result["telemetry"]["packet_success"])
        alarms = [a for a in self.manager.get_alarms() if a["alarm_type"] == "gateway_offline"]
        self.assertEqual(len(alarms), 1)
        self.manager.recover_device("GW-01", timestamp=self.now)
        self.sample(gateway_status="OFFLINE", auto_control_ok=True)
        self.assertEqual(self.manager.get_alarms()[0]["status"], "OPEN")
        for _ in range(20):
            self.sample(auto_control_ok=True)
        gateway_alarm = next(a for a in self.manager.get_alarms() if a["device_id"] == "GW-01")
        self.assertEqual(gateway_alarm["status"], "CLOSED")

    def test_logs_copies_and_session_isolation(self):
        self.manager.record_manual_control("CL-N01", "FAILED", "控制模块报告超时")
        logs = self.manager.get_operation_logs()
        logs[0]["result"] = "SUCCESS"
        self.assertEqual(self.manager.get_operation_logs()[0]["result"], "FAILED")
        self.assertEqual(FaultManager().get_operation_logs(), [])


if __name__ == "__main__":
    unittest.main()
