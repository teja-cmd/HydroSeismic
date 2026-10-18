from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi import HTTPException

from backend import main
from backend.auth.authorization import Principal, Role
from backend.schemas.approval import ApprovalBody
from backend.schemas.requests import CreateRequestBody


def state_fixture():
    return {
        "mode": "SYNTHETIC_DEMO",
        "zones": [{"id": "HZ-01", "name": "Riverbank North", "score": 94, "risk": "CRITICAL", "status": "Alert issued"}],
        "inventory": [{"resource": "WATER", "quantity": 100}],
        "requests": [],
        "inventory_movements": [],
        "inventory_reconciliations": [],
        "dispatches": [],
        "deliveries": [],
        "hazard_events": [],
        "events": [],
    }


class RequestCreationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_state_file = main.STATE_FILE
        self.original_lock_file = main.STATE_LOCK_FILE
        self.directory = TemporaryDirectory()
        main.STATE_FILE = Path(self.directory.name) / "state.json"
        main.STATE_LOCK_FILE = Path(self.directory.name) / "state.lock"
        main.save_state(state_fixture())

    def tearDown(self) -> None:
        main.STATE_FILE = self.original_state_file
        main.STATE_LOCK_FILE = self.original_lock_file
        self.directory.cleanup()

    def test_requester_is_derived_from_principal_and_cannot_self_approve(self) -> None:
        creator = Principal("officer-requester", frozenset({Role.GOVERNMENT_OFFICER}))
        created = main.create_allocation(
            CreateRequestBody(zone_id="HZ-01", resource="WATER", requested=20, reason="Urgent supply need"),
            creator,
        )["request"]

        self.assertEqual(created["requester_id"], "officer-requester")
        self.assertEqual(created["status"], "PENDING")
        self.assertEqual(main.get_state()["events"][0]["event_type"], "REQUEST_CREATED")

        with self.assertRaises(HTTPException) as self_review:
            main.review(
                created["id"],
                ApprovalBody(decision="APPROVE", reason="Attempted self approval", approved_qty=10),
                creator,
            )
        self.assertEqual(self_review.exception.status_code, 403)

        reviewer = Principal("independent-officer", frozenset({Role.GOVERNMENT_OFFICER}))
        reviewed = main.review(
            created["id"],
            ApprovalBody(decision="APPROVE", reason="Independently reviewed", approved_qty=10),
            reviewer,
        )
        self.assertEqual(reviewed["request"]["approved"], 10)
        self.assertEqual(main.inventory()["inventory"][0]["reserved"], 10)

    def test_unknown_zone_and_blank_reason_are_rejected(self) -> None:
        principal = Principal("requester-1", frozenset({Role.REQUESTER}))
        with self.assertRaises(HTTPException) as missing_zone:
            main.create_allocation(
                CreateRequestBody(zone_id="UNKNOWN", resource="WATER", requested=1, reason="Need"),
                principal,
            )
        self.assertEqual(missing_zone.exception.status_code, 404)
        with self.assertRaises(ValueError):
            CreateRequestBody(zone_id="HZ-01", resource="WATER", requested=1, reason=" ")


if __name__ == "__main__":
    unittest.main()