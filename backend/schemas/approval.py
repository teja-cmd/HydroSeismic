from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ApprovalBody(BaseModel):
    decision: Literal["APPROVE", "REJECT"]
    reason: str = Field(min_length=1, max_length=500)
    approved_qty: int | None = Field(default=None, ge=0)
    reviewer_id: str | None = Field(default=None, min_length=3, max_length=80)

    @field_validator("reason")
    @classmethod
    def require_nonblank_reason(cls, value: str) -> str:
        reason = value.strip()
        if not reason:
            raise ValueError("A non-blank review reason is required")
        return reason

    @field_validator("decision", mode="before")
    @classmethod
    def normalize_decision(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value