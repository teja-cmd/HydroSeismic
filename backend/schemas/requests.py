from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from .allocation import ResourceType


class CreateRequestBody(BaseModel):
    zone_id: str = Field(min_length=1, max_length=80)
    resource: ResourceType
    requested: int = Field(gt=0, le=1_000_000)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("zone_id", "reason")
    @classmethod
    def trim_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("This field cannot be blank")
        return cleaned