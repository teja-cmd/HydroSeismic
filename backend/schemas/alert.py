from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class HazardKind(str, Enum):
    EARTHQUAKE_OBSERVATION = "EARTHQUAKE_OBSERVATION"
    EARTHQUAKE_HAZARD_ASSESSMENT = "EARTHQUAKE_HAZARD_ASSESSMENT"
    OFFICIAL_WARNING = "OFFICIAL_WARNING"
    FLOOD_FORECAST = "FLOOD_FORECAST"
    FLOOD_OBSERVED = "FLOOD_OBSERVED"


class AlertSeverity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


Confidence = Annotated[float, Field(ge=0, le=1)]


class PointGeometry(BaseModel):
    type: Literal["Point"]
    coordinates: tuple[float, float]

    @field_validator("coordinates")
    @classmethod
    def validate_wgs84(cls, value: tuple[float, float]) -> tuple[float, float]:
        longitude, latitude = value
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError("Point coordinates must be valid WGS84 longitude/latitude")
        return value


class HazardEventInput(BaseModel):
    source: str = Field(min_length=1, max_length=120)
    source_event_id: str = Field(min_length=1, max_length=160)
    event_type: HazardKind
    event_time: datetime
    observed_at: datetime
    confidence: Confidence | None = None
    severity: AlertSeverity
    geometry: PointGeometry | None = None
    target_zone_ids: list[str] = Field(min_length=1, max_length=100)
    expires_at: datetime

    @field_validator("source", "source_event_id")
    @classmethod
    def trim_identity_fields(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Source identifiers cannot be blank")
        return cleaned

    @field_validator("event_time", "observed_at", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Hazard event timestamps must include a timezone")
        return value.astimezone(timezone.utc)

    @field_validator("target_zone_ids")
    @classmethod
    def unique_target_zones(cls, value: list[str]) -> list[str]:
        cleaned = [zone_id.strip() for zone_id in value]
        if any(not zone_id for zone_id in cleaned):
            raise ValueError("Target zone IDs cannot be blank")
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("Target zone IDs must be unique")
        return cleaned

    @model_validator(mode="after")
    def valid_event_window(self) -> HazardEventInput:
        if self.observed_at < self.event_time:
            raise ValueError("Observation time cannot precede the event time")
        if self.expires_at <= self.observed_at:
            raise ValueError("Alert expiry must be after the observation time")
        if self.expires_at <= datetime.now(timezone.utc):
            raise ValueError("Expired hazard events cannot be ingested")
        return self


class HazardValidationBody(BaseModel):
    decision: Literal["VALIDATE", "REJECT"]
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def require_nonblank_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A non-blank validation reason is required")
        return cleaned

    @field_validator("decision", mode="before")
    @classmethod
    def normalize_decision(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


class AlertAcknowledgementBody(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def require_nonblank_reason(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A non-blank acknowledgement reason is required")
        return cleaned