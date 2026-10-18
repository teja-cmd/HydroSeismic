from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend import main
from backend.auth.authorization import Principal, Role
from backend.schemas.inventory import InventoryReconciliationBody, ObservedStock


def make_state():
    return {
        "mode": "SYNTHETIC_DEMO",
        "zones": [],
        "inventory": [{"resource": "WATER", "quantity": 100, "unit": "litres"}],
        "requests": [
            {
                "id": "REQ-1",
                "requester_id": "requester-1",
                "zone_id": "HZ-1",
                "zone": "Test Zone",
                "resource": "WATER",
                "requested": 20,
                "recommended": 20,
                "priority": 80,
                "reason": "Test demand",
                "status": "PARTIALLY_DISPATCHED",
                "approval_status": "APPROVED",
                "approved": 20,
                "dispatched": 10,
                "delivered": 0,
                "shortage": 0,
            }
        ],
        "inventory_movements": [],
        "dispatches": [
            {
                "dispatch_id": "DSP-000001",
                "request_id": "REQ-1",
                "source_warehouse": "DEMO-WH-01",
                "destination_zone": "HZ-1",
                "resource": "WATER",
                "quantity": 10,
                "delivered": 0,
                "status": "DELIVERY_FAILED",
                "status_history": [],
            }
        ],
        "deliveries": [],
        "events": [],
    }


class ReconciliationWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_state_file = main.STATE_FILE
        self.original_lock_file = main.STATE_LOCK_FILE
        self.directory = TemporaryDirectory()
        main.STATE_FILE = Path(self.directory.name) / "state.json"
        main.STATE_LOCK_FILE = Path(self.directory.name) / "state.lock"
        main.save_state(make_state())
        self.administrator = Principal("admin-1", frozenset({Role.ADMINISTRATOR}))

    def tearDown(self) -> None:
        main.STATE_FILE = self.original_state_file
        main.STATE_LOCK_FILE = self.original_lock_file
        self.directory.cleanup()

    def test_inventory_count_reports_discrepancy_without_adjustment(self) -> None:
        report = main.inventory_reconciliation(
            InventoryReconciliationBody(
                warehouse_id="DEMO-WH-01",
                observations=[ObservedStock(resource="WATER", observed_quantity=88)],
            ),
            self.administrator,
        )

        self.assertEqual(report["lines"][0]["expected_on_hand"], 90)
        self.assertEqual(report["lines"][0]["discrepancy"], -2)
        self.assertEqual(main.inventory()["inventory"][0]["on_hand"], 90)
        persisted = main.get_state()
        self.assertEqual(persisted["events"][-1]["event_type"], "INVENTORY_RECONCILIATION_REPORTED")
        self.assertEqual(persisted["inventory_reconciliations"][0]["actor_id"], "admin-1")

    def test_failed_dispatch_return_is_applied_once(self) -> None:
        body = main.DispatchReconciliationBody(returned_qty=10, reason="Warehouse verified return")

        first = main.reconcile_dispatch("DSP-000001", body, self.administrator)
        replay = main.reconcile_dispatch("DSP-000001", body, self.administrator)

        self.assertFalse(first["replayed"])
        self.assertTrue(replay["replayed"])
        self.assertEqual(main.inventory()["inventory"][0]["on_hand"], 100)
        state = main.get_state()
        self.assertEqual(state["requests"][0]["dispatched"], 0)
        self.assertEqual(state["inventory_movements"][-1]["movement_type"], "RETURNED_TO_INVENTORY")
        self.assertEqual(len(state["events"]), 1)

    def test_failed_dispatch_can_be_reconciled_in_multiple_returns(self) -> None:
        first = main.reconcile_dispatch(
            "DSP-000001",
            main.DispatchReconciliationBody(returned_qty=4, reason="First returned pallet", idempotency_key="return-key-0001"),
            self.administrator,
        )
        self.assertEqual(first["dispatch"]["status"], "DELIVERY_FAILED")
        self.assertEqual(main.inventory()["inventory"][0]["on_hand"], 94)

        second = main.reconcile_dispatch(
            "DSP-000001",
            main.DispatchReconciliationBody(returned_qty=6, reason="Remaining pallet returned", idempotency_key="return-key-0002"),
            self.administrator,
        )

        self.assertEqual(second["dispatch"]["status"], "RECONCILED")
        self.assertEqual(main.inventory()["inventory"][0]["on_hand"], 100)
        self.assertEqual(len(second["dispatch"]["reconciliations"]), 2)


if __name__ == "__main__":
    unittest.main()