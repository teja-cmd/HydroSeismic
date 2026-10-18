from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .audit_service import append_event


class AlertError(Exception):
    status_code = 400


class AlertNotFound(AlertError):
    status_code = 404


class AlertConflict(AlertError):
    status_code = 409


class AlertForbidden(AlertError):
    status_code = 403


def ingest_hazard_event(
    state: dict[str, Any],
    event_data: dict[str, Any],
    *,
    actor_id: str,
    known_zone_ids: set[str],
) -> dict[str, Any]:
    unknown_zones = sorted(set(event_data["target_zone_ids"]) - known_zone_ids)
    if unknown_zones:
        raise AlertError(f"Unknown target zones: {', '.join(unknown_zones)}")
    duplicate = next(
        (
            event
            for event in state["hazard_events"]
            if event["source"] == event_data["source"]
            and event["source_event_id"] == event_data["source_event_id"]
        ),
        None,
    )
    if duplicate:
        raise AlertConflict("This source event has already been ingested")

    event = {
        "event_id": f"HE-{uuid4().hex}",
        **event_data,
        "ingested_by": actor_id,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "validation_status": "PENDING_REVIEW",
        "validation": None,
        "acknowledgements": [],
        "notification_status": "NOT_CONFIGURED",
    }
    for timestamp_field in ("event_time", "observed_at", "expires_at"):
        value = event[timestamp_field]
        if isinstance(value, datetime):
            event[timestamp_field] = value.isoformat()
    state["hazard_events"].append(event)
    append_event(
        state,
        "HAZARD_EVENT_INGESTED",
        actor_id,
        f"Hazard event {event['source_event_id']} from {event['source']} entered pending review.",
        actor_id=actor_id,
    )
    return event


def validate_hazard_event(
    state: dict[str, Any],
    event_id: str,
    *,
    actor_id: str,
    decision: str,
    reason: str,
) -> dict[str, Any]:
    event = next(
        (item for item in state["hazard_events"] if item["event_id"] == event_id),
        None,
    )
    if event is None:
        raise AlertNotFound("Hazard event not found")
    if event["validation_status"] != "PENDING_REVIEW":
        raise AlertConflict("Hazard event has already been reviewed")
    if event["ingested_by"] == actor_id:
        raise AlertForbidden("The event submitter cannot validate their own event")

    normalized_decision = decision.upper()
    if normalized_decision not in {"VALIDATE", "REJECT"}:
        raise AlertError("decision must be VALIDATE or REJECT")
    status = "VALIDATED" if normalized_decision == "VALIDATE" else "REJECTED"
    validation = {
        "decision": normalized_decision,
        "actor_id": actor_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason.strip(),
    }
    event["validation_status"] = status
    event["validation"] = validation
    append_event(
        state,
        f"HAZARD_EVENT_{status}",
        actor_id,
        f"Hazard event {event['event_id']} {status.lower()}. {validation['reason']}",
        actor_id=actor_id,
        decision=normalized_decision,
        reason=validation["reason"],
    )
    return event


def list_active_alerts(
    state: dict[str, Any],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    current_time = now or datetime.now(timezone.utc)
    return [
        event
        for event in reversed(state["hazard_events"])
        if event["validation_status"] == "VALIDATED"
        and datetime.fromisoformat(event["expires_at"]) > current_time
    ]


def acknowledge_alert(
    state: dict[str, Any],
    event_id: str,
    *,
    actor_id: str,
    reason: str,
) -> dict[str, Any]:
    event = next(
        (item for item in state["hazard_events"] if item["event_id"] == event_id),
        None,
    )
    if event is None:
        raise AlertNotFound("Hazard event not found")
    if event["validation_status"] != "VALIDATED":
        raise AlertConflict("Only validated alerts can be acknowledged")
    if datetime.fromisoformat(event["expires_at"]) <= datetime.now(timezone.utc):
        raise AlertConflict("Expired alerts cannot be acknowledged")
    if any(item["actor_id"] == actor_id for item in event["acknowledgements"]):
        raise AlertConflict("This actor has already acknowledged the alert")

    acknowledgement = {
        "actor_id": actor_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "reason": reason.strip(),
    }
    event["acknowledgements"].append(acknowledgement)
    append_event(
        state,
        "ALERT_ACKNOWLEDGED",
        actor_id,
        f"Alert {event_id} acknowledged. {acknowledgement['reason']}",
        actor_id=actor_id,
        reason=acknowledgement["reason"],
    )
    return event