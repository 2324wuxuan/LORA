"""文档 T01～T07 系统验收测试。"""

import csv
from datetime import date
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from analysis.quality import results_to_csv_bytes, run_quality_checks, save_results_csv


class SystemAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = run_quality_checks(date(2026, 9, 9))
        cls.by_id = {row["用例"]: row for row in cls.results}

    def test_documented_cases_are_complete(self):
        self.assertEqual(set(self.by_id), {f"T{index:02d}" for index in range(1, 8)})

    def test_t01_classroom_light_on(self):
        self.assertEqual(self.by_id["T01"]["实际结果"], "亮度 100%")
        self.assertEqual(self.by_id["T01"]["是否通过"], "通过")

    def test_t02_classroom_light_off(self):
        self.assertEqual(self.by_id["T02"]["实际结果"], "亮度 0%")
        self.assertEqual(self.by_id["T02"]["是否通过"], "通过")

    def test_t03_manual_control(self):
        self.assertIn("MANUAL", self.by_id["T03"]["实际结果"])
        self.assertEqual(self.by_id["T03"]["是否通过"], "通过")

    def test_t04_lora_packet_loss(self):
        self.assertIn("收包失败", self.by_id["T04"]["实际结果"])
        self.assertEqual(self.by_id["T04"]["是否通过"], "通过")

    def test_t05_low_rssi_alarm(self):
        self.assertIn("very_low_rssi", self.by_id["T05"]["实际结果"])
        self.assertEqual(self.by_id["T05"]["是否通过"], "通过")

    def test_t06_node_offline_alarm(self):
        self.assertIn("node_offline", self.by_id["T06"]["实际结果"])
        self.assertEqual(self.by_id["T06"]["是否通过"], "通过")

    def test_t07_energy_calculation(self):
        self.assertEqual(self.by_id["T07"]["实际结果"], "0.005000 kWh")
        self.assertEqual(self.by_id["T07"]["是否通过"], "通过")

    def test_csv_export_contains_all_results(self):
        decoded = results_to_csv_bytes(self.results).decode("utf-8-sig")
        rows = list(csv.DictReader(StringIO(decoded)))
        self.assertEqual(len(rows), 7)
        self.assertEqual({row["用例"] for row in rows}, set(self.by_id))
        with TemporaryDirectory() as directory:
            path = Path(directory) / "data" / "test_results.csv"
            self.assertEqual(save_results_csv(self.results, path), path)
            self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
