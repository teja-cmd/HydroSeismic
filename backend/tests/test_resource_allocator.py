from __future__ import annotations

import unittest

from pydantic import ValidationError

from backend.schemas.allocation import AllocationScenario
from backend.services.resource_allocator import simulate_allocation


def zone(zone_id: str, *, urgency: int, population: int = 1000, water: int = 10):
    return {
        "zone_id": zone_id,
        "risk_score": 80,
        "exposed_population": population,
        "urgency": urgency,
        "infrastructure_impact": 50,
        "medical_need": 25,
        "demand": {"WATER": water},
    }


class ResourceAllocatorTests(unittest.TestCase):
    def test_zero_stock_reports_full_unmet_demand(self) -> None:
        scenario = AllocationScenario(zones=[zone("Z1", urgency=80)], available_stock={"WATER": 0})

        result = simulate_allocation(scenario).recommendations[0]

        self.assertEqual(result.allocated, 0)
        self.assertEqual(result.unmet, result.requested)
        self.assertEqual(result.shortage, result.recommended)
        self.assertIn("available stock allowed 0", result.explanation)

    def test_partial_stock_allocates_without_exceeding_inventory(self) -> None:
        scenario = AllocationScenario(zones=[zone("Z1", urgency=80)], available_stock={"WATER": 4})

        result = simulate_allocation(scenario).recommendations[0]

        self.assertEqual(result.allocated, 4)
        self.assertEqual(result.unmet, result.requested - 4)
        self.assertEqual(result.shortage, result.recommended - 4)
        self.assertEqual(result.available_after, 0)

    def test_competing_zones_allocate_first_to_higher_priority(self) -> None:
        scenario = AllocationScenario(
            zones=[zone("LOW", urgency=10), zone("URGENT", urgency=100)],
            available_stock={"WATER": 8},
        )

        results = simulate_allocation(scenario).recommendations

        self.assertEqual(results[0].zone_id, "URGENT")
        self.assertEqual(results[0].allocated, results[0].recommended)
        self.assertEqual(results[1].allocated, 0)
        self.assertLessEqual(sum(result.allocated for result in results), 8)

    def test_negative_demand_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AllocationScenario(zones=[zone("Z1", urgency=80, water=-1)], available_stock={})

    def test_stock_already_reserved_is_not_available_to_scenario(self) -> None:
        scenario = AllocationScenario(
            zones=[zone("Z1", urgency=80, water=30)],
            available_stock={"WATER": 7},
        )

        result = simulate_allocation(scenario).recommendations[0]

        self.assertEqual(result.available_before, 7)
        self.assertEqual(result.allocated, 7)
        self.assertEqual(result.unmet, result.requested - 7)

    def test_scenario_is_deterministic_and_does_not_mutate_input(self) -> None:
        scenario = AllocationScenario(
            zones=[zone("Z1", urgency=80)],
            available_stock={"WATER": 10},
        )
        before = scenario.model_dump()

        first = simulate_allocation(scenario).model_dump()
        second = simulate_allocation(scenario).model_dump()

        self.assertEqual(first, second)
        self.assertEqual(scenario.model_dump(), before)
        self.assertFalse(first["committed"])

    def test_weights_must_sum_to_one(self) -> None:
        with self.assertRaises(ValidationError):
            AllocationScenario(
                zones=[zone("Z1", urgency=80)],
                available_stock={},
                weights={"risk_score": 1},
            )

    def test_response_explains_custom_weights(self) -> None:
        scenario = AllocationScenario(
            zones=[zone("Z1", urgency=80)],
            available_stock={},
            weights={
                "risk_score": 0.2,
                "exposure": 0.2,
                "urgency": 0.2,
                "infrastructure_impact": 0.2,
                "medical_need": 0.2,
            },
        )

        result = simulate_allocation(scenario)

        self.assertIn("risk_score*0.20", result.priority_formula)


if __name__ == "__main__":
    unittest.main()