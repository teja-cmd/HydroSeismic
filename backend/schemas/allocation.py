from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, Field, model_validator


class ResourceType(str, Enum):
    WATER = "WATER"
    FOOD = "FOOD"
    MEDICAL_KITS = "MEDICAL_KITS"
    AMBULANCE = "AMBULANCE"
    RESCUE_TEAM = "RESCUE_TEAM"


NonNegativeInt = Annotated[int, Field(ge=0)]
Score = Annotated[float, Field(ge=0, le=100)]


class ZoneDemand(BaseModel):
    zone_id: str = Field(min_length=1, max_length=80)
    risk_score: Score
    exposed_population: NonNegativeInt
    urgency: Score
    infrastructure_impact: Score
    medical_need: Score
    demand: dict[ResourceType, NonNegativeInt]


class AllocationWeights(BaseModel):
    risk_score: float = Field(default=0.4, ge=0, le=1)
    exposure: float = Field(default=0.25, ge=0, le=1)
    urgency: float = Field(default=0.15, ge=0, le=1)
    infrastructure_impact: float = Field(default=0.1, ge=0, le=1)
    medical_need: float = Field(default=0.1, ge=0, le=1)

    @model_validator(mode="after")
    def weights_must_sum_to_one(self) -> AllocationWeights:
        total = sum(self.model_dump().values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError("Allocation weights must sum to 1")
        return self


class AllocationScenario(BaseModel):
    zones: list[ZoneDemand] = Field(min_length=1, max_length=500)
    available_stock: dict[ResourceType, NonNegativeInt]
    weights: AllocationWeights = Field(default_factory=AllocationWeights)


class ResourceRecommendation(BaseModel):
    zone_id: str
    resource: ResourceType
    priority_score: float
    requested: int
    recommended: int
    allocated: int
    unmet: int
    shortage: int
    available_before: int
    available_after: int
    explanation: str


class AllocationSimulation(BaseModel):
    mode: str = "SIMULATION_ONLY"
    committed: bool = False
    priority_formula: str
    recommendations: list[ResourceRecommendation]
