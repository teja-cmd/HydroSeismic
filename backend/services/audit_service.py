from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any


def event_hash(event: dict[str, Any]) -> str:
    payload = json.dumps(event, sort_keys=True, separators=(",", ":")).encode()
    return sha256(payload).hexdigest()


def append_event(
    state: dict[str, Any],
    event_type: str,
    actor: str,
    message: str,
    request_id: str | None = None,
    *,
    actor_id: str | None = None,
    decision: str | None = None,
    reason: str | None = None,
) -> None:
    events = state["events"]
    previous_hash = events[-1]["hash"] if events else "GENESIS"
    event: dict[str, Any] = {
        "event_id": f"AUD-{len(events) + 1:04d}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "actor": actor,
        "message": message,
        "request_id": request_id,
        "previous_hash": previous_hash,
    }
    if actor_id is not None:
        event["actor_id"] = actor_id
    if decision is not None:
        event["decision"] = decision
    if reason is not None:
        event["reason"] = reason
    event["hash"] = event_hash(event)
    events.append(event)


def verify_chain(events: list[dict[str, Any]]) -> dict[str, Any]:
    previous_hash = "GENESIS"
    errors: list[str] = []
    for index, event in enumerate(events, start=1):
        expected_id = f"AUD-{index:04d}"
        if event.get("event_id") != expected_id:
            errors.append(f"Event sequence mismatch at position {index}")
        if event.get("previous_hash") != previous_hash:
            errors.append(f"Previous hash mismatch at {event.get('event_id', expected_id)}")
        content = {key: value for key, value in event.items() if key != "hash"}
        if event_hash(content) != event.get("hash"):
            errors.append(f"Event hash mismatch at {event.get('event_id', expected_id)}")
        previous_hash = event.get("hash", "INVALID")
    return {"valid": not errors, "event_count": len(events), "errors": errors}