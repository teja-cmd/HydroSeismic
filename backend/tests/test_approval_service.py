from __future__ import annotations

from copy import deepcopy
import unittest

from backend.auth.authorization import Principal, Role
from backend.main import append_event, event_hash
from backend.schemas.approval import ApprovalBody
from backend.services.approval_service import (
    ApprovalConflict,
    ApprovalForbidden,
    ApprovalInvalid,
    review_allocation,
)


def make_state(*, requester_id: str | None = "requester-1", status: str = "PENDING"):
    request = {
        "id": "REQ-TEST",
        "resource": "WATER",
        "recommended": 25,
        "approved": 0,
        "dispatched": 0,
        "delivered": 0,
        "status": status,
        "approval_status": status,
    }
    if requester_id is not None:
        request["requester_id"] = requester_id
    return {
        "mode": "SYNTHETIC_DEMO",
        "zones": [],
        "requests": [request],
        "inventory": [{"resource": "WATER", "quantity": 100}],
        "events": [],
    }


class ApprovalServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = make_state()
        self.officer = Principal("officer-1", frozenset({Role.GOVERNMENT_OFFICER}))

    def review(self, *, principal: Principal | None = None, decision: str = "APPROVE"):
        return review_allocation(
            self.state,
            "REQ-TEST",
            principal=principal or self.officer,
            decision=decision,
            reason="Verified by the regional review team",
            approved_qty=20,
            append_audit=append_event,
        )

    def test_non_reviewer_roles_are_denied(self) -> None:
        for role in (Role.WAREHOUSE_STAFF, Role.AUDITOR):
            with self.subTest(role=role), self.assertRaises(ApprovalForbidden):
                self.review(principal=Principal("staff-1", frozenset({role})))

    def test_requester_cannot_review_own_request(self) -> None:
        with self.assertRaises(ApprovalForbidden):
            self.review(principal=Principal("requester-1", frozenset({Role.ADMINISTRATOR})))

    def test_request_without_owner_fails_closed(self) -> None:
        self.state = make_state(requester_id=None)
        with self.assertRaises(ApprovalConflict):
            self.review()

    def test_duplicate_review_is_rejected(self) -> None:
        self.review()
        with self.assertRaises(ApprovalConflict):
            self.review()
        self.assertEqual(len(self.state["events"]), 1)

    def test_non_pending_state_is_rejected(self) -> None:
        self.state = make_state(status="DISPATCHED")
        with self.assertRaises(ApprovalConflict):
            self.review()

    def test_approval_records_verified_actor_and_reason(self) -> None:
        request = self.review()
        event = self.state["events"][0]

        self.assertEqual(request["approval_status"], "APPROVED")
        self.assertEqual(request["approved"], 20)
        self.assertEqual(event["actor_id"], "officer-1")
        self.assertEqual(event["request_id"], "REQ-TEST")
        self.assertEqual(event["decision"], "APPROVE")
        self.assertEqual(event["reason"], "Verified by the regional review team")
        self.assertTrue(event["timestamp"])
        self.assertEqual(event["hash"], event_hash({k: v for k, v in event.items() if k != "hash"}))

    def test_rejection_is_recorded_with_reason(self) -> None:
        request = self.review(decision="REJECT")
        event = self.state["events"][0]

        self.assertEqual(request["approval_status"], "REJECTED")
        self.assertEqual(event["decision"], "REJECT")
        self.assertEqual(event["actor_id"], "officer-1")
        self.assertEqual(event["reason"], "Verified by the regional review team")

    def test_review_reason_must_be_nonblank(self) -> None:
        with self.assertRaises(ValueError):
            ApprovalBody(decision="reject", reason="   ")
        with self.assertRaises(ValueError):
            ApprovalBody(decision="approve")


class ConcurrentApprovalTests(unittest.TestCase):
    def test_only_one_concurrent_review_commits(self) -> None:
        from concurrent.futures import ThreadPoolExecutor
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from threading import Barrier

        from fastapi import HTTPException

        from backend import main

        original_state_file = main.STATE_FILE
        original_lock_file = main.STATE_LOCK_FILE
        barrier = Barrier(2)
        with TemporaryDirectory() as directory:
            try:
                main.STATE_FILE = Path(directory) / "state.json"
                main.STATE_LOCK_FILE = Path(directory) / "state.lock"
                main.save_state(deepcopy(make_state()))
                body = ApprovalBody(
                    decision="APPROVE",
                    reason="Concurrent review test",
                    reviewer_id="spoofed-body-identity",
                )
                principal = Principal("officer-2", frozenset({Role.GOVERNMENT_OFFICER}))

                def submit_review() -> int:
                    barrier.wait()
                    try:
                        main.review("REQ-TEST", body, principal)
                    except HTTPException as exc:
                        return exc.status_code
                    return 200

                with ThreadPoolExecutor(max_workers=2) as executor:
                    results = sorted(executor.map(lambda _: submit_review(), range(2)))

                self.assertEqual(results, [200, 409])
                events = main.get_state()["events"]
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]["actor_id"], "officer-2")
            finally:
                main.STATE_FILE = original_state_file
                main.STATE_LOCK_FILE = original_lock_file


if __name__ == "__main__":
    unittest.main()