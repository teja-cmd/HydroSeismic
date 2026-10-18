from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from fastapi import HTTPException

from backend import main
from backend.auth.authorization import Principal, Role
from backend.schemas.alert import AlertAcknowledgementBody, HazardEventInput, HazardValidationBody


class AlertWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_state_file = main.STATE_FILE
        self.original_lock_file = main.STATE_LOCK_FILE
        self.directory = TemporaryDirectory()
        main.STATE_FILE = Path(self.directory.name) / "state.json"
        main.STATE_LOCK_FILE = Path(self.directory.name) / "state.lock"
        state = {
            "mode": "SYNTHETIC_DEMO",
            "zones": [{"id": "HZ-01"}],
            "requests": [],
            "inventory": [],
            "inventory_movements": [],
            "dispatches": [],
            "deliveries": [],
            "hazard_events": [],
            "events": [],
        }
        main.save_state(state)
        self.ingester = Principal("feed-admin", frozenset({Role.ADMINISTRATOR}))
        self.reviewer = Principal("gov-officer", frozenset({Role.GOVERNMENT_OFFICER}))

    def tearDown(self) -> None:
        main.STATE_FILE = self.original_state_file
        main.STATE_LOCK_FILE = self.original_lock_file
        self.directory.cleanup()

    def make_event(self) -> HazardEventInput:
        current = datetime.now(timezone.utc)
        return HazardEventInput(
            source="reviewed-demo-source",
            source_event_id="EV-001",
            event_type="FLOOD_FORECAST",
            event_time=current - timedelta(minutes=1),
            observed_at=current,
            confidence=0.7,
            severity="HIGH",
            target_zone_ids=["HZ-01"],
            expires_at=current + timedelta(hours=1),
        )

    def test_alert_requires_independent_validation_then_acknowledges(self) -> None:
        ingested = main.ingest_event(self.make_event(), self.ingester)["event"]
        self.assertEqual(ingested["validation_status"], "PENDING_REVIEW")
        self.assertEqual(main.alerts(self.reviewer)["alerts"], [])

        with self.assertRaises(HTTPException) as self_review:
            main.review_hazard_event(
                ingested["event_id"],
                HazardValidationBody(decision="VALIDATE", reason="Same identity"),
                self.ingester,
            )
        self.assertEqual(self_review.exception.status_code, 403)

        validated = main.review_hazard_event(
            ingested["event_id"],
            HazardValidationBody(decision="VALIDATE", reason="Source independently checked"),
            self.reviewer,
        )["event"]
        self.assertEqual(main.alerts(self.reviewer)["alerts"][0]["event_id"], validated["event_id"])

        main.acknowledge_alert_route(
            validated["event_id"],
            AlertAcknowledgementBody(reason="Local response desk notified"),
            self.reviewer,
        )
        with self.assertRaises(HTTPException) as duplicate_ack:
            main.acknowledge_alert_route(
                validated["event_id"],
                AlertAcknowledgementBody(reason="Repeated acknowledgement"),
                self.reviewer,
            )
        self.assertEqual(duplicate_ack.exception.status_code, 409)
        self.assertEqual(len(main.get_state()["events"]), 3)

    def test_duplicate_feed_event_is_rejected_without_second_record(self) -> None:
        body = self.make_event()
        main.ingest_event(body, self.ingester)

        with self.assertRaises(HTTPException) as duplicate:
            main.ingest_event(body, self.ingester)

        self.assertEqual(duplicate.exception.status_code, 409)
        self.assertEqual(len(main.get_state()["hazard_events"]), 1)


if __name__ == "__main__":
    unittest.main()