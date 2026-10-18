from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def require_nonblank_reason(cls, value: str) -> str:
        reason = value.strip()
        if not reason:
            raise ValueError("A non-blank reason is required")
        return reason


class StockAdjustmentBody(ReasonBody):
    delta: int


class ObservedStock(BaseModel):
    resource: str = Field(min_length=1, max_length=80)
    observed_quantity: int = Field(ge=0)


class InventoryReconciliationBody(BaseModel):
    warehouse_id: str = Field(default="DEMO-WH-01", min_length=1, max_length=80)
    observations: list[ObservedStock] = Field(min_length=1, max_length=100)

    @field_validator("observations")
    @classmethod
    def reject_duplicate_resources(cls, values: list[ObservedStock]) -> list[ObservedStock]:
        resources = [value.resource for value in values]
        if len(resources) != len(set(resources)):
            raise ValueError("Each resource may appear only once per reconciliation")
        return values