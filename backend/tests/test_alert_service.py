from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from backend.schemas.alert import HazardEventInput
from backend.services.alert_service import (
    AlertError,
    AlertConflict,
    AlertForbidden,
    acknowledge_alert,
    ingest_hazard_event,
    list_active_alerts,
    validate_hazard_event,
)


def event_input(**overrides):
    current = datetime.now(timezone.utc)
    values = {
        "source": "demo-reviewed-feed",
        "source_event_id": "SRC-001",
        "event_type": "FLOOD_OBSERVED",
        "event_time": current - timedelta(minutes=5),
        "observed_at": current,
        "confidence": 0.8,
        "severity": "HIGH",
        "geometry": {"type": "Point", "coordinates": [79.09, 13.21]},
        "target_zone_ids": ["HZ-01", "HZ-02"],
        "expires_at": current + timedelta(hours=1),
    }
    values.update(overrides)
    return HazardEventInput(**values)


class AlertServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {"hazard_events": [], "events": []}
        self.event = ingest_hazard_event(
            self.state,
            event_input().model_dump(mode="json"),
            actor_id="feed-operator-1",
            known_zone_ids={"HZ-01", "HZ-02"},
        )

    def test_new_source_event_waits_for_human_validation(self) -> None:
        self.assertEqual(self.event["validation_status"], "PENDING_REVIEW")
        self.assertEqual(list_active_alerts(self.state), [])
        self.assertEqual(self.event["notification_status"], "NOT_CONFIGURED")

    def test_duplicate_source_event_is_rejected(self) -> None:
        with self.assertRaises(AlertConflict):
            ingest_hazard_event(
                self.state,
                event_input().model_dump(mode="json"),
                actor_id="feed-operator-2",
                known_zone_ids={"HZ-01", "HZ-02"},
            )

    def test_unknown_zone_reference_is_rejected(self) -> None:
        with self.assertRaises(AlertError):
            ingest_hazard_event(
                self.state,
                event_input().model_dump(mode="json"),
                actor_id="feed-operator-2",
                known_zone_ids={"HZ-01"},
            )

    def test_stale_event_is_rejected_at_schema_boundary(self) -> None:
        current = datetime.now(timezone.utc)
        with self.assertRaises(ValueError):
            event_input(
                event_time=current - timedelta(hours=2),
                observed_at=current - timedelta(hours=1),
                expires_at=current - timedelta(minutes=1),
            )

    def test_event_submitter_cannot_validate_event(self) -> None:
        with self.assertRaises(AlertForbidden):
            validate_hazard_event(
                self.state,
                self.event["event_id"],
                actor_id="feed-operator-1",
                decision="VALIDATE",
                reason="Self review",
            )

    def test_validated_event_becomes_active_and_can_be_acknowledged_once(self) -> None:
        validated = validate_hazard_event(
            self.state,
            self.event["event_id"],
            actor_id="officer-1",
            decision="VALIDATE",
            reason="Confirmed against the cited source bulletin",
        )

        self.assertEqual(len(list_active_alerts(self.state)), 1)
        acknowledged = acknowledge_alert(
            self.state,
            validated["event_id"],
            actor_id="officer-2",
            reason="Zone response desk informed",
        )
        self.assertEqual(acknowledged["acknowledgements"][0]["actor_id"], "officer-2")
        with self.assertRaises(AlertConflict):
            acknowledge_alert(
                self.state,
                validated["event_id"],
                actor_id="officer-2",
                reason="Duplicate acknowledgement",
            )

    def test_expired_validated_event_is_not_returned(self) -> None:
        self.event["expires_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        validate_hazard_event(
            self.state,
            self.event["event_id"],
            actor_id="officer-1",
            decision="VALIDATE",
            reason="Historical event review",
        )

        self.assertEqual(list_active_alerts(self.state), [])

    def test_invalid_geometry_and_timestamps_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            event_input(geometry={"type": "Point", "coordinates": [500, 200]})
        with self.assertRaises(ValueError):
            event_input(event_time=datetime.now())


if __name__ == "__main__":
    unittest.main()