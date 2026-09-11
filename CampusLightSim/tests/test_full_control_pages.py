"""Verify that added devices are reachable through real page controls."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
from streamlit.testing.v1 import AppTest
from config import DEVICES
from database import db

PAGES = Path(__file__).resolve().parents[1] / "pages"


class FullControlPageTests(unittest.TestCase):
    def test_hundredth_classroom_can_be_controlled_independently(self):
        with TemporaryDirectory() as directory, patch.object(db, "DATABASE_PATH", Path(directory)/"test.db"):
            app = AppTest.from_file(str(PAGES/"05_远程控制.py")).run(timeout=30)
            self.assertFalse(app.exception)
            target = "CL-MAIN-ROOM-0100"
            label = f"{target} · {DEVICES[target]['device_name']}"
            app.selectbox[1].select(label).run(timeout=30)
            next(b for b in app.button if b.label == "🔆 远程开灯（100%）").click().run(timeout=30)
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state.devices[target]["brightness"], 100)
            self.assertEqual(app.session_state.devices["CL-N01"]["brightness"], 0)
            self.assertEqual(len(db.get_operation_logs(target)), 1)

    def test_full_simulation_button_runs_all_nodes(self):
        app = AppTest.from_file(str(PAGES/"09_实验与测试.py")).run(timeout=30)
        next(b for b in app.button if b.label == "运行全部节点联合仿真").click().run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state.full_simulation_summary["节点数"], 1690)
        self.assertEqual(app.session_state.full_simulation_summary["采样数"], 1690)


if __name__ == "__main__":
    unittest.main()
