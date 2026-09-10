"""入口页面与跨页面会话状态验证，使用 Streamlit 官方 AppTest。"""
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from config import DEVICES


APP = Path(__file__).resolve().parents[1] / "app.py"
DEVICE_PAGE = APP.parent / "pages" / "02_区域与设备.py"
LIGHTING_PAGE = APP.parent / "pages" / "03_智能照明.py"


class AppTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        patcher = patch("database.db.DATABASE_PATH", Path(directory.name) / "campus.db")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_home_and_state_survive_rerun(self):
        app = AppTest.from_file(str(APP)).run(timeout=20)
        self.assertFalse(app.exception)
        self.assertIn("CampusLightSim", app.title[0].value)
        self.assertTrue(app.session_state.devices_initialized)
        self.assertFalse(app.session_state.simulation_running)
        self.assertTrue(app.session_state.database_initialized)
        self.assertTrue(app.session_state.engine_ready)
        self.assertTrue(callable(app.session_state.engine_runner))
        manager = app.session_state.fault_manager
        timestamp = datetime(2026, 9, 9, 12)
        app.session_state.simulation_time = timestamp
        app.session_state.devices["CL-N01"]["status"] = "OFFLINE"
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state.simulation_time, timestamp)
        self.assertIs(app.session_state.fault_manager, manager)
        self.assertEqual(app.session_state.devices["CL-N01"]["status"], "OFFLINE")
        self.assertEqual(DEVICES["CL-N01"]["initial_status"], "ONLINE")

    def test_device_page_renders(self):
        # AppTest.switch_page cannot resolve st.navigation pages that define a
        # custom url_path, so execute the registered file page directly.
        app = AppTest.from_file(str(DEVICE_PAGE)).run(timeout=20)
        self.assertFalse(app.exception)
        self.assertIn("区域与设备", app.title[0].value)
        self.assertTrue(any("校园总体规划地图" in item.value for item in app.subheader))

    def test_three_gateway_network_page(self):
        app = AppTest.from_file(str(APP.parent / "pages" / "04_LoRa网络.py")).run(timeout=20)
        self.assertFalse(app.exception)
        topology = next(item.value for item in app.markdown if '<svg' in item.value)
        for device_id in DEVICES:
            self.assertIn(f'data-device-id="{device_id}"', topology)
        self.assertEqual(len(app.dataframe[1].value), len(DEVICES))
        app.selectbox[0].select("CL-N10").run(timeout=20)
        self.assertFalse(app.exception)
        topology = next(item.value for item in app.markdown if '<svg' in item.value)
        self.assertEqual(topology.count('data-device-id='), len(DEVICES))
        app.multiselect[0].set_value(["GW-01", "GW-02", "GW-03"]).run(timeout=20)
        self.assertFalse(app.exception)
        scenario_metric = next(
            metric for metric in app.metric
            if metric.label == "对照场景最佳接收网关"
        )
        self.assertEqual(scenario_metric.value, "无可达网关")
        self.assertTrue((app.dataframe[1].value["场景最佳接收"] == "无可达网关").all())

    def test_lighting_page_supports_all_representative_devices(self):
        app = AppTest.from_file(str(LIGHTING_PAGE)).run(timeout=20)
        self.assertFalse(app.exception)
        self.assertIn("智能照明", app.title[0].value)
        self.assertEqual(len(app.selectbox[0].options), len(DEVICES))
        app.selectbox[0].select("CL-N10").run(timeout=20)
        self.assertFalse(app.exception)
        self.assertTrue(any("仿真估算" in item.value for item in app.caption))

    def test_invalid_config_stops_initialization(self):
        with patch("config.validate_config", return_value=(False, ["测试配置错误"])):
            app = AppTest.from_file(str(APP)).run(timeout=20)
        self.assertFalse(app.exception)
        self.assertIn("校验失败", app.error[0].value)
        self.assertNotIn("devices", app.session_state)

    def test_database_initializes_once_per_session(self):
        with patch("database.db.init_db", create=True) as init_db:
            app = AppTest.from_file(str(APP)).run(timeout=20)
            app.run()
        self.assertFalse(app.exception)
        init_db.assert_called_once_with()
        self.assertTrue(app.session_state.database_initialized)


if __name__ == "__main__":
    unittest.main()
