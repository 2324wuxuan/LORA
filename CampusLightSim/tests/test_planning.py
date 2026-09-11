"""Quantity arithmetic, ownership, and compatibility with representative models."""
import unittest
from copy import deepcopy
from config import CAMPUS_PLANNING_AREAS, DEVICES, validate_config
from planning import LIGHTING_PLAN, calculate_item, estimate_lighting_plan, road_item


class LightingPlanTests(unittest.TestCase):
    def test_main_building_includes_all_rooms_floors_and_roads(self):
        result = estimate_lighting_plan()
        rows = {row["item_id"]: row for row in result["rows"]}
        self.assertEqual(rows["MAIN-ROOM"]["control_nodes"], 100)
        self.assertEqual(rows["MAIN-ROOM"]["fixtures"], 1200)
        self.assertEqual(rows["MAIN-CORRIDOR"]["control_nodes"], 40)
        self.assertEqual(rows["MAIN-STAIR"]["control_nodes"], 20)
        self.assertEqual(rows["MAIN-ROAD"]["fixtures"], 16)
        self.assertEqual(result["areas"]["PA01"], dict(control_nodes=178, fixtures=1380))

    def test_campus_totals_and_unique_ownership(self):
        result = estimate_lighting_plan()
        self.assertEqual(result["control_nodes"], 1690)
        self.assertEqual(result["fixtures"], 8363)
        self.assertEqual(set(result["areas"]), set(CAMPUS_PLANNING_AREAS))
        for area_id, area in CAMPUS_PLANNING_AREAS.items():
            self.assertEqual(area["recommended_nodes"], result["areas"][area_id]["control_nodes"])
            self.assertEqual(area["recommended_fixtures"], result["areas"][area_id]["fixtures"])
        self.assertEqual(len(DEVICES), result["control_nodes"])
        self.assertEqual(validate_config(), (True, []))
        self.assertEqual(next(r for r in result["rows"] if r["item_id"] == "CANTEEN")["area_id"], "PA03")
        with self.assertRaises(ValueError):
            estimate_lighting_plan([LIGHTING_PLAN[0], LIGHTING_PLAN[0]])

    def test_editing_assumptions_recalculates_fixtures_not_controllers(self):
        plan = deepcopy(LIGHTING_PLAN)
        plan[0]["fixtures_per_node"] = 16
        result = estimate_lighting_plan(plan)
        self.assertEqual(result["fixtures"], 8363 + 400)
        self.assertEqual(result["control_nodes"], 1690)
        self.assertEqual(LIGHTING_PLAN[0]["fixtures_per_node"], 12)

    def test_road_rounding_and_endpoints(self):
        open_row = road_item("TEST", "PA07", "道路", 2, 51)
        self.assertEqual(calculate_item(open_row)["control_nodes"], 8)
        self.assertEqual(calculate_item({**open_row, "closed": True})["control_nodes"], 6)
        with self.assertRaises(ValueError):
            calculate_item({**open_row, "spacing_m": 0})
        with self.assertRaises(ValueError):
            calculate_item({**open_row, "routes": -1})


if __name__ == "__main__":
    unittest.main()
