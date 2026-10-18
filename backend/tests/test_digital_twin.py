from __future__ import annotations

from copy import deepcopy
import unittest

from backend.schemas.scenario import ScenarioInput
from backend.services.digital_twin_service import simulate_digital_twin


class DigitalTwinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {
            "zones": [
                {"id": "Z1", "score": 70, "exposure": 100, "risk": "HIGH"},
                {"id": "Z2", "score": 40, "exposure": 50, "risk": "MODERATE"},
            ],
            "inventory": [{"resource": "WATER", "quantity": 20}],
            "requests": [
                {
                    "zone_id": "Z1",
                    "resource": "WATER",
                    "requested": 10,
                    "approved": 0,
                    "dispatched": 0,
                    "delivered": 0,
                    "approval_status": "PENDING",
                }
            ],
        }

    def test_scenario_is_deterministic_and_state_is_unchanged(self) -> None:
        original = deepcopy(self.state)
        scenario = ScenarioInput(
            name="Rising water what-if",
            exposure_multiplier=1.5,
            risk_score_delta={"Z1": 20, "Z2": 30},
            resource_availability_reduction={"WATER": 50},
        )

        first = simulate_digital_twin(self.state, scenario).model_dump()
        second = simulate_digital_twin(self.state, scenario).model_dump()

        self.assertEqual(first, second)
        self.assertEqual(self.state, original)
        self.assertFalse(first["committed"])
        self.assertEqual(first["simulated_metrics"]["total_exposed_population"], 225)
        self.assertEqual(first["baseline_metrics"]["high_critical_zones"], 1)
        self.assertEqual(first["simulated_metrics"]["high_critical_zones"], 2)
        self.assertEqual(first["affected_zones"][0]["simulated_score"], 90)
        self.assertTrue(first["unsupported_inputs"])

    def test_risk_and_exposure_are_clamped_or_scaled_at_boundaries(self) -> None:
        result = simulate_digital_twin(
            self.state,
            ScenarioInput(
                name="Boundary test",
                exposure_multiplier=0,
                risk_score_delta={"Z1": 100},
            ),
        )

        self.assertEqual(result.affected_zones[0]["simulated_score"], 100)
        self.assertEqual(result.simulated_metrics["total_exposed_population"], 0)

    def test_unknown_zone_inputs_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown zone IDs"):
            simulate_digital_twin(
                self.state,
                ScenarioInput(name="Invalid", risk_score_delta={"UNKNOWN": 5}),
            )


if __name__ == "__main__":
    unittest.main()