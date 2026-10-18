from __future__ import annotations

import unittest

from backend.services.audit_service import append_event, verify_chain


class AuditIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {"events": []}
        append_event(self.state, "REQUEST", "actor-1", "Created", "REQ-1")
        append_event(self.state, "APPROVAL", "actor-2", "Approved", "REQ-1")
        append_event(self.state, "DISPATCH", "actor-3", "Dispatched", "REQ-1")

    def test_valid_chain_passes(self) -> None:
        result = verify_chain(self.state["events"])

        self.assertTrue(result["valid"])
        self.assertEqual(result["event_count"], 3)
        self.assertEqual(result["errors"], [])

    def test_payload_tampering_fails(self) -> None:
        self.state["events"][1]["message"] = "Edited"

        result = verify_chain(self.state["events"])

        self.assertFalse(result["valid"])
        self.assertTrue(any("Event hash mismatch" in error for error in result["errors"]))

    def test_deleted_middle_event_fails(self) -> None:
        del self.state["events"][1]

        result = verify_chain(self.state["events"])

        self.assertFalse(result["valid"])
        self.assertTrue(any("sequence mismatch" in error.lower() for error in result["errors"]))

    def test_reordered_events_fail(self) -> None:
        self.state["events"].reverse()

        result = verify_chain(self.state["events"])

        self.assertFalse(result["valid"])
        self.assertTrue(any("Previous hash mismatch" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()