from __future__ import annotations

from collections.abc import Callable
from typing import Any

if __package__ and "." in __package__:
    from ..auth.authorization import Principal, REVIEWER_ROLES
    from .inventory_service import append_inventory_movement, available_quantity
else:
    from auth.authorization import Principal, REVIEWER_ROLES
    from services.inventory_service import append_inventory_movement, available_quantity


class ApprovalError(Exception):
    status_code = 400


class ApprovalForbidden(ApprovalError):
    status_code = 403


class ApprovalNotFound(ApprovalError):
    status_code = 404


class ApprovalConflict(ApprovalError):
    status_code = 409


class ApprovalInvalid(ApprovalError):
    status_code = 400


AuditAppender = Callable[..., None]


def review_allocation(
    state: dict[str, Any],
    request_id: str,
    *,
    principal: Principal,
    decision: str,
    reason: str,
    approved_qty: int | None,
    append_audit: AuditAppender,
) -> dict[str, Any]:
    if not principal.roles.intersection(REVIEWER_ROLES):
        raise ApprovalForbidden("Government officer or administrator role is required")

    request = next(
        (item for item in state["requests"] if item["id"] == request_id),
        None,
    )
    if request is None:
        raise ApprovalNotFound("Request not found")
    if request.get("approval_status") != "PENDING" or request.get("status") != "PENDING":
        raise ApprovalConflict("Only pending requests can be reviewed")

    requester_id = request.get("requester_id")
    if not requester_id:
        raise ApprovalConflict("Request has no verified requester identity")
    if requester_id == principal.subject:
        raise ApprovalForbidden("Requesters cannot review their own requests")

    normalized_decision = decision.upper()
    if normalized_decision not in {"APPROVE", "REJECT"}:
        raise ApprovalInvalid("decision must be APPROVE or REJECT")
    clean_reason = reason.strip()
    if not clean_reason:
        raise ApprovalInvalid("A non-blank review reason is required")

    if normalized_decision == "REJECT":
        request["approval_status"] = "REJECTED"
        request["status"] = "REJECTED"
        request["approved"] = 0
        event_type = "ALLOCATION_REJECTED"
        message = f"Rejected {request['resource']} request. {clean_reason}"
    else:
        available = available_quantity(state, request["resource"])
        quantity = approved_qty if approved_qty is not None else request["recommended"]
        if quantity < 1:
            raise ApprovalInvalid("Approved quantity must be greater than zero")
        if quantity > available:
            raise ApprovalInvalid(
                f"Only {available} {request['resource']} available to reserve"
            )
        request["approval_status"] = "APPROVED"
        request["status"] = "APPROVED"
        request["approved"] = quantity
        append_inventory_movement(
            state,
            movement_type="RESERVED",
            actor_id=principal.subject,
            resource=request["resource"],
            quantity=quantity,
            reason=clean_reason,
            request_id=request_id,
        )
        event_type = "ALLOCATION_APPROVED"
        message = f"Approved {quantity} {request['resource']}. {clean_reason}"

    append_audit(
        state,
        event_type,
        principal.subject,
        message,
        request_id,
        actor_id=principal.subject,
        decision=normalized_decision,
        reason=clean_reason,
    )
    return request