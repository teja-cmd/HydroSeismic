from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi import HTTPException

from backend import main
from backend.auth.authorization import Principal, Role
from backend.schemas.approval import ApprovalBody
from backend.schemas.inventory import ReasonBody


def state_fixture():
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
                "recommended": 20,
                "approved": 0,
                "dispatched": 0,
                "delivered": 0,
                "released": 0,
                "requested": 20,
                "priority": 80,
                "reason": "Test demand",
                "status": "PENDING",
                "approval_status": "PENDING",
            }
        ],
        "inventory_movements": [],
        "events": [],
    }


class InventoryWorkflowTests(unittest.TestCase):
    def test_cancel_prepared_shipment_releases_capacity_without_stock_consumption(self) -> None:
        original_state_file = main.STATE_FILE
        original_lock_file = main.STATE_LOCK_FILE
        with TemporaryDirectory() as directory:
            try:
                main.STATE_FILE = Path(directory) / "state.json"
                main.STATE_LOCK_FILE = Path(directory) / "state.lock"
                main.save_state(state_fixture())
                officer = Principal("officer-1", frozenset({Role.GOVERNMENT_OFFICER}))
                warehouse = Principal("warehouse-1", frozenset({Role.WAREHOUSE_STAFF}))
                main.review(
                    "REQ-1",
                    ApprovalBody(decision="APPROVE", reason="Approved for preparation", approved_qty=20),
                    officer,
                )
                prepared = main.prepare_dispatch(
                    "REQ-1",
                    main.PrepareDispatchBody(quantity=12),
                    warehouse,
                )["dispatch"]

                canceled = main.cancel_prepared_dispatch(
                    prepared["dispatch_id"],
                    main.ReasonBody(reason="Vehicle unavailable"),
                    warehouse,
                )["dispatch"]

                self.assertEqual(canceled["status"], "CANCELED")
                self.assertEqual(main.inventory()["inventory"][0]["on_hand"], 100)
                self.assertEqual(main.get_state()["requests"][0]["dispatched"], 0)
                self.assertEqual(
                    [movement["movement_type"] for movement in main.get_state()["inventory_movements"]],
                    ["RESERVED"],
                )
            finally:
                main.STATE_FILE = original_state_file
                main.STATE_LOCK_FILE = original_lock_file

    def test_prepared_dispatch_holds_approved_capacity_until_commit(self) -> None:
        original_state_file = main.STATE_FILE
        original_lock_file = main.STATE_LOCK_FILE
        with TemporaryDirectory() as directory:
            try:
                main.STATE_FILE = Path(directory) / "state.json"
                main.STATE_LOCK_FILE = Path(directory) / "state.lock"
                main.save_state(state_fixture())
                officer = Principal("officer-1", frozenset({Role.GOVERNMENT_OFFICER}))
                warehouse = Principal("warehouse-1", frozenset({Role.WAREHOUSE_STAFF}))
                main.review(
                    "REQ-1",
                    ApprovalBody(decision="APPROVE", reason="Approved for dispatch test", approved_qty=20),
                    officer,
                )
                body = main.PrepareDispatchBody(quantity=12, idempotency_key="prepare-key-0001")
                prepared = main.prepare_dispatch("REQ-1", body, warehouse)
                self.assertEqual(prepared["dispatch"]["status"], "PREPARED")
                self.assertEqual(main.inventory()["inventory"][0]["on_hand"], 100)

                replay = main.prepare_dispatch("REQ-1", body, warehouse)
                self.assertTrue(replay["replayed"])
                with self.assertRaises(HTTPException) as over_capacity:
                    main.prepare_dispatch("REQ-1", main.PrepareDispatchBody(quantity=9), warehouse)
                self.assertEqual(over_capacity.exception.status_code, 400)

                dispatched = main.commit_dispatch(prepared["dispatch"]["dispatch_id"], warehouse)
                self.assertEqual(dispatched["dispatch"]["status"], "DISPATCHED")
                self.assertEqual(main.inventory()["inventory"][0]["on_hand"], 88)
                with self.assertRaises(HTTPException) as duplicate_commit:
                    main.commit_dispatch(prepared["dispatch"]["dispatch_id"], warehouse)
                self.assertEqual(duplicate_commit.exception.status_code, 409)
                self.assertEqual(len(main.get_state()["events"]), 3)
            finally:
                main.STATE_FILE = original_state_file
                main.STATE_LOCK_FILE = original_lock_file

    def test_reserve_dispatch_deliver_and_release_balances(self) -> None:
        original_state_file = main.STATE_FILE
        original_lock_file = main.STATE_LOCK_FILE
        with TemporaryDirectory() as directory:
            try:
                main.STATE_FILE = Path(directory) / "state.json"
                main.STATE_LOCK_FILE = Path(directory) / "state.lock"
                main.save_state(state_fixture())
                officer = Principal("officer-1", frozenset({Role.GOVERNMENT_OFFICER}))
                warehouse = Principal("warehouse-1", frozenset({Role.WAREHOUSE_STAFF}))

                main.review(
                    "REQ-1",
                    ApprovalBody(decision="APPROVE", reason="Approved for test", approved_qty=20),
                    officer,
                )
                reserved = main.inventory()["inventory"][0]
                self.assertEqual((reserved["on_hand"], reserved["reserved"], reserved["available"]), (100, 20, 80))

                dispatch_body = main.DispatchBody(officer_id="body-spoof", dispatch_qty=8)
                dispatch_response = main.dispatch(
                    "REQ-1",
                    dispatch_body,
                    warehouse,
                )
                duplicate_dispatch = main.dispatch("REQ-1", dispatch_body, warehouse)
                self.assertTrue(duplicate_dispatch["replayed"])
                dispatch_record = dispatch_response["dispatch"]
                main.mark_in_transit(
                    dispatch_record["dispatch_id"],
                    main.DispatchTransitionBody(status="IN_TRANSIT"),
                    warehouse,
                )
                dispatched = main.inventory()["inventory"][0]
                self.assertEqual((dispatched["on_hand"], dispatched["reserved"], dispatched["available"]), (92, 12, 80))

                delivery_body = main.DeliveryBody(officer_id="body-spoof", delivered_qty=5, note="Partial receipt")
                delivery_response = main.delivery(
                    "REQ-1",
                    delivery_body,
                    warehouse,
                )
                self.assertTrue(main.delivery("REQ-1", delivery_body, warehouse)["replayed"])
                self.assertEqual(delivery_response["delivery"]["quantity"], 5)
                delivered = main.inventory()["inventory"][0]
                self.assertEqual(delivered["on_hand"], 92)
                self.assertEqual(delivered["delivered"], 5)

                canceled = main.cancel_allocation(
                    "REQ-1",
                    ReasonBody(reason="Remaining units no longer required"),
                    officer,
                )
                final_stock = main.inventory()["inventory"][0]
                self.assertEqual(canceled["released"], 12)
                self.assertEqual(final_stock["reserved"], 0)
                self.assertEqual(final_stock["available"], 92)
                current_dispatch = main.get_dispatch(dispatch_record["dispatch_id"], warehouse)["dispatch"]
                self.assertEqual(current_dispatch["status"], "PARTIALLY_DELIVERED")
                self.assertEqual(
                    [entry["status"] for entry in current_dispatch["status_history"]],
                    ["PREPARED", "DISPATCHED", "IN_TRANSIT", "PARTIALLY_DELIVERED"],
                )

                with self.assertRaises(HTTPException) as raised:
                    main.cancel_allocation(
                        "REQ-1",
                        ReasonBody(reason="Duplicate release"),
                        officer,
                    )
                self.assertEqual(raised.exception.status_code, 409)

                persisted = main.get_state()
                self.assertEqual(
                    [movement["movement_type"] for movement in persisted["inventory_movements"]],
                    ["RESERVED", "DISPATCHED", "DELIVERED", "RESERVATION_RELEASED"],
                )
                self.assertEqual(len(persisted["events"]), 5)
            finally:
                main.STATE_FILE = original_state_file
                main.STATE_LOCK_FILE = original_lock_file

    def test_failed_shipment_records_reason_and_keeps_consumed_stock_accounted(self) -> None:
        original_state_file = main.STATE_FILE
        original_lock_file = main.STATE_LOCK_FILE
        with TemporaryDirectory() as directory:
            try:
                main.STATE_FILE = Path(directory) / "state.json"
                main.STATE_LOCK_FILE = Path(directory) / "state.lock"
                main.save_state(state_fixture())
                officer = Principal("officer-1", frozenset({Role.GOVERNMENT_OFFICER}))
                warehouse = Principal("warehouse-1", frozenset({Role.WAREHOUSE_STAFF}))
                main.review(
                    "REQ-1",
                    ApprovalBody(decision="APPROVE", reason="Approved for test", approved_qty=20),
                    officer,
                )
                dispatched = main.dispatch(
                    "REQ-1",
                    main.DispatchBody(officer_id="body-spoof", dispatch_qty=10),
                    warehouse,
                )["dispatch"]

                failed = main.fail_dispatch(
                    dispatched["dispatch_id"],
                    main.DispatchFailureBody(reason="Access route blocked"),
                    warehouse,
                )["dispatch"]

                self.assertEqual(failed["status"], "DELIVERY_FAILED")
                self.assertEqual(failed["status_history"][-1]["reason"], "Access route blocked")
                self.assertEqual(main.inventory()["inventory"][0]["on_hand"], 90)
                with self.assertRaises(HTTPException) as raised:
                    main.delivery(
                        "REQ-1",
                        main.DeliveryBody(officer_id="body-spoof", delivered_qty=1),
                        warehouse,
                    )
                self.assertEqual(raised.exception.status_code, 409)
            finally:
                main.STATE_FILE = original_state_file
                main.STATE_LOCK_FILE = original_lock_file

    def test_partial_delivery_records_shortage_and_reason(self) -> None:
        original_state_file = main.STATE_FILE
        original_lock_file = main.STATE_LOCK_FILE
        with TemporaryDirectory() as directory:
            try:
                main.STATE_FILE = Path(directory) / "state.json"
                main.STATE_LOCK_FILE = Path(directory) / "state.lock"
                main.save_state(state_fixture())
                officer = Principal("officer-1", frozenset({Role.GOVERNMENT_OFFICER}))
                warehouse = Principal("warehouse-1", frozenset({Role.WAREHOUSE_STAFF}))
                main.review(
                    "REQ-1",
                    ApprovalBody(decision="APPROVE", reason="Approved for test", approved_qty=20),
                    officer,
                )
                main.dispatch(
                    "REQ-1",
                    main.DispatchBody(officer_id="body-spoof", dispatch_qty=10),
                    warehouse,
                )

                with self.assertRaises(ValueError):
                    main.DeliveryBody(officer_id="body-spoof", delivered_qty=7, shortage_qty=3)

                receipt = main.delivery(
                    "REQ-1",
                    main.DeliveryBody(
                        officer_id="body-spoof",
                        delivered_qty=7,
                        shortage_qty=3,
                        shortage_reason="Damaged in transit",
                        note="Counted at receiving point",
                    ),
                    warehouse,
                )["delivery"]
                state = main.get_state()

                self.assertEqual(receipt["quantity"], 7)
                self.assertEqual(receipt["shortage"], 3)
                self.assertEqual(receipt["shortage_reason"], "Damaged in transit")
                self.assertEqual(state["requests"][0]["delivered"], 7)
                self.assertEqual(state["requests"][0]["shortage"], 3)
                self.assertEqual(state["inventory_movements"][-1]["movement_type"], "SHORTAGE_REPORTED")
                self.assertEqual(state["events"][-1]["event_type"], "DELIVERY_SHORTAGE_REPORTED")
            finally:
                main.STATE_FILE = original_state_file
                main.STATE_LOCK_FILE = original_lock_file


if __name__ == "__main__":
    unittest.main()