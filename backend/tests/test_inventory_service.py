from __future__ import annotations

import unittest

from backend.services.inventory_service import (
    InventoryConflict,
    InventoryError,
    adjust_stock,
    inventory_snapshot,
    release_unused_reservation,
)


def make_state():
    return {
        "inventory": [{"resource": "WATER", "quantity": 100, "unit": "litres"}],
        "requests": [
            {
                "id": "REQ-1",
                "resource": "WATER",
                "approval_status": "APPROVED",
                "status": "PARTIALLY_DISPATCHED",
                "approved": 50,
                "dispatched": 20,
                "delivered": 10,
            }
        ],
    }


class InventoryServiceTests(unittest.TestCase):
    def test_stock_balances_include_reserved_and_dispatched_units(self) -> None:
        snapshot = inventory_snapshot(make_state())[0]

        self.assertEqual(snapshot["quantity"], 100)
        self.assertEqual(snapshot["on_hand"], 80)
        self.assertEqual(snapshot["reserved"], 30)
        self.assertEqual(snapshot["available"], 50)
        self.assertEqual(snapshot["dispatched"], 20)
        self.assertEqual(snapshot["delivered"], 10)

    def test_cancel_releases_unused_reservation_once(self) -> None:
        state = make_state()

        request, released = release_unused_reservation(
            state,
            "REQ-1",
            actor_id="officer-1",
            reason="Response plan changed",
        )

        self.assertEqual(released, 30)
        self.assertEqual(request["released"], 30)
        self.assertEqual(request["status"], "CANCELED")
        self.assertEqual(inventory_snapshot(state)[0]["available"], 80)
        self.assertEqual(state["inventory_movements"][0]["actor_id"], "officer-1")
        with self.assertRaises(InventoryConflict):
            release_unused_reservation(
                state,
                "REQ-1",
                actor_id="officer-1",
                reason="Repeated cancellation",
            )

    def test_decrease_cannot_consume_reserved_or_dispatched_stock(self) -> None:
        with self.assertRaises(InventoryError):
            adjust_stock(
                make_state(),
                "WATER",
                -51,
                actor_id="admin-1",
                reason="Damaged stock",
            )

    def test_stock_adjustment_records_actor_reason_and_delta(self) -> None:
        state = make_state()

        adjust_stock(
            state,
            "WATER",
            12,
            actor_id="admin-1",
            reason="Verified delivery to warehouse",
        )

        self.assertEqual(state["inventory"][0]["quantity"], 112)
        movement = state["inventory_movements"][0]
        self.assertEqual(movement["quantity"], 12)
        self.assertEqual(movement["reason"], "Verified delivery to warehouse")


if __name__ == "__main__":
    unittest.main()