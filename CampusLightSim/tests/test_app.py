"""入口页面与跨页面会话状态验证，使用 Streamlit 官方 AppTest。"""
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from config import DEVICES


APP = Path(__file__).resolve().parents[1] / "app.py"


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
        self.assertFalse(app.session_state.engine_ready)
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

    def test_device_page_uses_shared_entrypoint(self):
        app = AppTest.from_file(str(APP)).run(timeout=20)
        manager = app.session_state.fault_manager
        app.switch_page("pages/02_区域与设备.py").run(timeout=20)
        self.assertFalse(app.exception)
        self.assertIn("区域与设备", app.title[0].value)
        self.assertIs(app.session_state.fault_manager, manager)

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
