from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field

from .allocation import AllocationSimulation, ResourceType


RiskDelta = Annotated[int, Field(ge=-100, le=100)]
Percentage = Annotated[int, Field(ge=0, le=100)]


class ScenarioInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    exposure_multiplier: float = Field(default=1.0, ge=0, le=10)
    risk_score_delta: dict[str, RiskDelta] = Field(default_factory=dict)
    urgency_by_zone: dict[str, Percentage] = Field(default_factory=dict)
    infrastructure_impact_by_zone: dict[str, Percentage] = Field(default_factory=dict)
    medical_need_by_zone: dict[str, Percentage] = Field(default_factory=dict)
    resource_availability_reduction: dict[ResourceType, Percentage] = Field(default_factory=dict)


class ScenarioResult(BaseModel):
    mode: str = "SIMULATION_ONLY"
    committed: bool = False
    name: str
    baseline_metrics: dict[str, int | float]
    simulated_metrics: dict[str, int | float]
    affected_zones: list[dict[str, int | float | str]]
    baseline_recommendations: AllocationSimulation
    simulated_recommendations: AllocationSimulation
    assumptions: list[str]
    unsupported_inputs: list[str]