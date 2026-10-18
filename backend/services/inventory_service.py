from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class InventoryError(Exception):
    status_code = 400


class InventoryNotFound(InventoryError):
    status_code = 404


class InventoryConflict(InventoryError):
    status_code = 409


def inventory_snapshot(state: dict[str, Any]) -> list[dict[str, Any]]:
    snapshot = []
    for item in state["inventory"]:
        matching = [
            request
            for request in state["requests"]
            if request["resource"] == item["resource"]
        ]
        dispatched = sum(request.get("dispatched", 0) for request in matching)
        delivered = sum(request.get("delivered", 0) for request in matching)
        reserved = sum(
            max(
                0,
                request.get("approved", 0)
                - request.get("dispatched", 0)
                - request.get("released", 0),
            )
            for request in matching
        )
        on_hand = max(0, item["quantity"] - dispatched)
        available = max(0, on_hand - reserved)
        snapshot.append(
            {
                **item,
                "on_hand": on_hand,
                "reserved": reserved,
                "available": available,
                "dispatched": dispatched,
                "delivered": delivered,
            }
        )
    return snapshot


def available_quantity(state: dict[str, Any], resource: str) -> int:
    item = next(
        (item for item in inventory_snapshot(state) if item["resource"] == resource),
        None,
    )
    return item["available"] if item else 0


def reconcile_inventory(
    state: dict[str, Any],
    observations: list[dict[str, Any]],
    *,
    warehouse_id: str,
) -> dict[str, Any]:
    expected = {item["resource"]: item for item in inventory_snapshot(state)}
    lines = []
    for observation in observations:
        resource = observation["resource"]
        if resource not in expected:
            raise InventoryNotFound(f"Resource not found: {resource}")
        expected_quantity = expected[resource]["on_hand"]
        observed_quantity = observation["observed_quantity"]
        discrepancy = observed_quantity - expected_quantity
        lines.append(
            {
                "resource": resource,
                "expected_on_hand": expected_quantity,
                "observed_quantity": observed_quantity,
                "discrepancy": discrepancy,
                "status": "MATCH" if discrepancy == 0 else "DISCREPANCY",
            }
        )
    return {
        "warehouse_id": warehouse_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mutated_inventory": False,
        "lines": lines,
    }


def append_inventory_movement(
    state: dict[str, Any],
    *,
    movement_type: str,
    actor_id: str,
    resource: str,
    quantity: int,
    reason: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    movements = state.setdefault("inventory_movements", [])
    movement = {
        "movement_id": f"INV-{len(movements) + 1:06d}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "movement_type": movement_type,
        "actor_id": actor_id,
        "resource": resource,
        "quantity": quantity,
        "reason": reason,
        "request_id": request_id,
    }
    movements.append(movement)
    return movement


def release_unused_reservation(
    state: dict[str, Any],
    request_id: str,
    *,
    actor_id: str,
    reason: str,
) -> tuple[dict[str, Any], int]:
    request = next(
        (item for item in state["requests"] if item["id"] == request_id),
        None,
    )
    if request is None:
        raise InventoryNotFound("Request not found")
    if request.get("approval_status") != "APPROVED":
        raise InventoryConflict("Only approved requests can release a reservation")

    releasable = (
        request.get("approved", 0)
        - request.get("dispatched", 0)
        - request.get("released", 0)
    )
    if releasable <= 0:
        raise InventoryConflict("No unused reservation remains to release")

    request["released"] = request.get("released", 0) + releasable
    request["approval_status"] = "CANCELED"
    request["status"] = "CANCELED"
    append_inventory_movement(
        state,
        movement_type="RESERVATION_RELEASED",
        actor_id=actor_id,
        resource=request["resource"],
        quantity=releasable,
        reason=reason,
        request_id=request_id,
    )
    return request, releasable


def adjust_stock(
    state: dict[str, Any],
    resource: str,
    delta: int,
    *,
    actor_id: str,
    reason: str,
) -> dict[str, Any]:
    item = next((entry for entry in state["inventory"] if entry["resource"] == resource), None)
    if item is None:
        raise InventoryNotFound("Resource not found")
    if delta == 0:
        raise InventoryError("Adjustment must be non-zero")
    if delta < 0 and -delta > available_quantity(state, resource):
        raise InventoryError("Stock adjustment cannot consume reserved or dispatched units")

    item["quantity"] += delta
    append_inventory_movement(
        state,
        movement_type="STOCK_ADJUSTED",
        actor_id=actor_id,
        resource=resource,
        quantity=delta,
        reason=reason,
    )
    return item