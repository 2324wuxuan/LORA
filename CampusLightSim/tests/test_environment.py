"""Focused tests for Fang's environment simulation and scenario parameters."""

import unittest
from datetime import datetime

from analysis.energy import (
    calculate_energy,
    calculate_saving_rate,
    calculate_traditional_daily_energy,
    simulate_smart_daily_energy,
)
from config import (
    BASE_DIR,
    CAMPUS_MAP,
    CAMPUS_PLANNING_AREAS,
    DEVICES,
    SIMULATION_ESTIMATE_LABEL,
    ZONES,
    validate_config,
)
from control.lighting import auto_control, reset_state
from simulator.environment import (
    generate_environment_series,
    get_environment,
    get_lux,
    get_occupancy,
    get_occupancy_probability,
)


class EnvironmentSimulationTests(unittest.TestCase):
    def test_config_is_valid(self):
        valid, errors = validate_config()
        self.assertTrue(valid, errors)

    def test_campus_wide_planning_and_map_are_configured(self):
        self.assertEqual(len(CAMPUS_PLANNING_AREAS), 8)
        self.assertEqual(len(ZONES), 1690)
        self.assertEqual(len(DEVICES), 1690)
        self.assertTrue((BASE_DIR / CAMPUS_MAP["asset_path"]).is_file())
        planned_landmarks = {
            landmark
            for area in CAMPUS_PLANNING_AREAS.values()
            for landmark in area["landmarks"]
        }
        for landmark in ("主楼", "图书馆", "体育场", "教一楼", "学生公寓群"):
            self.assertIn(landmark, planned_landmarks)
        linked_zones = {
            zone_id
            for area in CAMPUS_PLANNING_AREAS.values()
            for zone_id in area["linked_zone_ids"]
        }
        self.assertEqual(linked_zones, set(ZONES))

    def test_phase_two_and_three_parameters_are_marked_as_estimates(self):
        for area_id, area in CAMPUS_PLANNING_AREAS.items():
            if area_id == "PA01":
                continue
            self.assertEqual(area["parameter_source"], SIMULATION_ESTIMATE_LABEL)
            self.assertEqual(area["simulation_nodes"], area["recommended_nodes"])
            self.assertEqual(len(area["linked_zone_ids"]), area["recommended_nodes"])
            zone_id = area["linked_zone_ids"][0]
            self.assertEqual(ZONES[zone_id]["parameter_source"], SIMULATION_ESTIMATE_LABEL)
            device = next(item for item in DEVICES.values() if item["zone_id"] == zone_id)
            self.assertEqual(device["parameter_source"], SIMULATION_ESTIMATE_LABEL)

    def test_environment_contract_and_repeatability(self):
        timestamp = datetime(2026, 9, 9, 10, 0)
        first = get_environment("Z01", timestamp)
        second = get_environment("Z01", timestamp)
        self.assertEqual(first, second)
        self.assertEqual(set(first), {"timestamp", "zone_id", "lux", "occupancy"})
        self.assertEqual(first["zone_id"], "Z01")
        self.assertIsInstance(first["occupancy"], bool)

    def test_zone_aliases_are_supported(self):
        self.assertEqual(get_lux("Classroom", "10:00"), get_lux("Z01", "10:00"))

    def test_daylight_curve_and_zone_attenuation(self):
        noon = datetime(2026, 9, 9, 12)
        midnight = datetime(2026, 9, 9, 0)
        self.assertGreater(get_lux("Z01", noon), get_lux("Z01", midnight))
        self.assertLess(get_lux("Z01", noon), get_lux("Z02", noon))
        self.assertLess(get_lux("Z02", noon), get_lux("Z03", noon))

    def test_configured_campus_activity_patterns(self):
        self.assertEqual(get_occupancy_probability("Z01", "10:00"), 0.90)
        self.assertEqual(get_occupancy_probability("Z01", "23:00"), 0.01)
        self.assertGreater(
            get_occupancy_probability("Z02", "10:30"),
            get_occupancy_probability("Z02", "09:30"),
        )
        self.assertGreater(
            get_occupancy_probability("Z03", "19:00"),
            get_occupancy_probability("Z03", "03:00"),
        )
        self.assertEqual(
            get_occupancy("Z03", "19:00"),
            get_occupancy("Z03", "19:00"),
        )

    def test_full_day_contains_288_samples(self):
        samples = list(generate_environment_series("Z01", datetime(2026, 9, 9)))
        self.assertEqual(len(samples), 288)
        self.assertEqual(samples[-1]["timestamp"], datetime(2026, 9, 9, 23, 55))

    def test_all_representative_zones_return_environment_and_lighting(self):
        timestamp = datetime(2026, 9, 9, 19, 0)
        reset_state()
        for zone_id in ZONES:
            sample = get_environment(zone_id, timestamp)
            brightness = auto_control(zone_id, sample["lux"], sample["occupancy"], timestamp)
            self.assertGreaterEqual(sample["lux"], 0)
            self.assertIsInstance(sample["occupancy"], bool)
            self.assertGreaterEqual(brightness, 0)
            self.assertLessEqual(brightness, 100)

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaises(KeyError):
            get_lux("Z99", "10:00")
        with self.assertRaises(ValueError):
            get_lux("Z01", 24)


class EnergyScenarioTests(unittest.TestCase):
    def test_energy_formula(self):
        self.assertAlmostEqual(calculate_energy(60, 5), 0.005)

    def test_traditional_scenario_and_saving_rate(self):
        self.assertAlmostEqual(calculate_traditional_daily_energy(), 4404.96)
        self.assertEqual(calculate_saving_rate(4, 3), 25.0)

    def test_all_zones_participate_in_smart_energy_simulation(self):
        result = simulate_smart_daily_energy(datetime(2026, 9, 9))
        self.assertEqual(set(result["device_energy_kwh"]), set(DEVICES))
        self.assertEqual(set(result["zone_energy_kwh"]), set(ZONES))
        self.assertEqual(
            set(result["planning_area_energy_kwh"]),
            set(CAMPUS_PLANNING_AREAS),
        )
        self.assertEqual(result["sample_count"], 288 * len(DEVICES))
        self.assertGreater(result["total_energy_kwh"], 0)


if __name__ == "__main__":
    unittest.main()
