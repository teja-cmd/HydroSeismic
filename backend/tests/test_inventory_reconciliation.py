from __future__ import annotations

import unittest

from backend.services.inventory_service import InventoryNotFound, reconcile_inventory


class InventoryReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {
            "inventory": [{"resource": "WATER", "quantity": 100}],
            "requests": [
                {
                    "resource": "WATER",
                    "approved": 30,
                    "dispatched": 10,
                    "delivered": 5,
                }
            ],
        }

    def test_count_reconciliation_reports_variance_without_mutation(self) -> None:
        before = {"quantity": self.state["inventory"][0]["quantity"]}

        report = reconcile_inventory(
            self.state,
            [{"resource": "WATER", "observed_quantity": 87}],
            warehouse_id="DEMO-WH-01",
        )

        self.assertEqual(report["lines"][0]["expected_on_hand"], 90)
        self.assertEqual(report["lines"][0]["discrepancy"], -3)
        self.assertFalse(report["mutated_inventory"])
        self.assertEqual({"quantity": self.state["inventory"][0]["quantity"]}, before)

    def test_unknown_observed_resource_is_rejected(self) -> None:
        with self.assertRaises(InventoryNotFound):
            reconcile_inventory(
                self.state,
                [{"resource": "SHELTER", "observed_quantity": 2}],
                warehouse_id="DEMO-WH-01",
            )


if __name__ == "__main__":
    unittest.main()