from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from backend import main
from backend.auth.authorization import Principal, Role
from backend.schemas.approval import ApprovalBody
from backend.schemas.inventory import ReasonBody
from backend.schemas.requests import CreateRequestBody


def initial_state():
    return {
        "mode": "SYNTHETIC_DEMO",
        "zones": [{"id": "HZ-01", "name": "Riverbank North", "lat": 13.2, "lng": 79.1, "score": 90, "risk": "CRITICAL", "exposure": 1000, "population": 1200, "hazard": "Flood", "status": "Alert issued", "reason": "Test scenario"}],
        "inventory": [{"resource": "WATER", "quantity": 100, "unit": "litres"}],
        "requests": [],
        "inventory_movements": [],
        "inventory_reconciliations": [],
        "dispatches": [],
        "deliveries": [],
        "hazard_events": [],
        "events": [],
    }


class ReliefLifecycleTests(unittest.TestCase):
    def test_request_to_delivery_and_audit_integrity(self) -> None:
        original_state_file = main.STATE_FILE
        original_lock_file = main.STATE_LOCK_FILE
        with TemporaryDirectory() as directory:
            try:
                main.STATE_FILE = Path(directory) / "state.json"
                main.STATE_LOCK_FILE = Path(directory) / "state.lock"
                main.save_state(initial_state())
                requester = Principal("requester-1", frozenset({Role.REQUESTER}))
                approver = Principal("officer-1", frozenset({Role.GOVERNMENT_OFFICER}))
                warehouse = Principal("warehouse-1", frozenset({Role.WAREHOUSE_STAFF}))
                auditor = Principal("auditor-1", frozenset({Role.AUDITOR}))

                created = main.create_allocation(
                    CreateRequestBody(
                        zone_id="HZ-01",
                        resource="WATER",
                        requested=20,
                        reason="Provide drinking water to affected households",
                    ),
                    requester,
                )["request"]
                self.assertEqual(created["requester_id"], requester.subject)

                approved = main.review(
                    created["id"],
                    ApprovalBody(decision="APPROVE", reason="Need independently verified", approved_qty=15),
                    approver,
                )["request"]
                self.assertEqual(approved["approved"], 15)

                prepared = main.prepare_dispatch(
                    created["id"],
                    main.PrepareDispatchBody(quantity=10, source_warehouse="WH-01"),
                    warehouse,
                )["dispatch"]
                committed = main.commit_dispatch(prepared["dispatch_id"], warehouse)["dispatch"]
                self.assertEqual(committed["status"], "DISPATCHED")

                main.mark_in_transit(
                    prepared["dispatch_id"],
                    main.DispatchTransitionBody(status="IN_TRANSIT"),
                    warehouse,
                )
                receipt = main.delivery(
                    created["id"],
                    main.DeliveryBody(
                        officer_id="legacy-compatible-field",
                        delivered_qty=8,
                        shortage_qty=2,
                        shortage_reason="Two units damaged in transit",
                        note="Receiving count completed",
                    ),
                    warehouse,
                )["delivery"]
                self.assertEqual(receipt["quantity"], 8)
                self.assertEqual(receipt["shortage"], 2)

                inventory = main.inventory()["inventory"][0]
                self.assertEqual(inventory["on_hand"], 90)
                self.assertEqual(inventory["reserved"], 5)
                self.assertEqual(inventory["delivered"], 8)
                audit = main.audit(page=1, page_size=100, event_type=None, request_id=None, principal=auditor)
                self.assertTrue(audit["valid"])
                self.assertEqual(audit["event_count"], 6)
                self.assertEqual(main.get_state()["events"][-1]["event_type"], "DELIVERY_SHORTAGE_REPORTED")
            finally:
                main.STATE_FILE = original_state_file
                main.STATE_LOCK_FILE = original_lock_file


if __name__ == "__main__":
    unittest.main()