from __future__ import annotations

from typing import Any

if __package__ and "." in __package__:
    from ..schemas.allocation import AllocationScenario, ResourceType, ZoneDemand
    from ..schemas.scenario import ScenarioInput, ScenarioResult
    from .inventory_service import inventory_snapshot
    from .resource_allocator import simulate_allocation
else:
    from schemas.allocation import AllocationScenario, ResourceType, ZoneDemand
    from schemas.scenario import ScenarioInput, ScenarioResult
    from services.inventory_service import inventory_snapshot
    from services.resource_allocator import simulate_allocation


def _metrics(zones: list[dict[str, Any]]) -> dict[str, int | float]:
    return {
        "zone_count": len(zones),
        "total_exposed_population": sum(zone["exposure"] for zone in zones),
        "high_critical_zones": sum(zone["risk"] in {"HIGH", "CRITICAL"} for zone in zones),
        "mean_risk_score": round(
            sum(zone["score"] for zone in zones) / len(zones), 2
        ) if zones else 0,
    }


def _demands_by_zone(state: dict[str, Any]) -> dict[str, dict[ResourceType, int]]:
    demand: dict[str, dict[ResourceType, int]] = {}
    for request in state["requests"]:
        if request.get("approval_status") != "PENDING":
            continue
        resource = ResourceType(request["resource"])
        zone_demand = demand.setdefault(request["zone_id"], {})
        zone_demand[resource] = zone_demand.get(resource, 0) + request["requested"]
    return demand


def simulate_digital_twin(
    state: dict[str, Any],
    scenario: ScenarioInput,
) -> ScenarioResult:
    zones = state["zones"]
    zone_ids = {zone["id"] for zone in zones}
    referenced_ids = (
        set(scenario.risk_score_delta)
        | set(scenario.urgency_by_zone)
        | set(scenario.infrastructure_impact_by_zone)
        | set(scenario.medical_need_by_zone)
    )
    unknown_ids = sorted(referenced_ids - zone_ids)
    if unknown_ids:
        raise ValueError(f"Unknown zone IDs: {', '.join(unknown_ids)}")

    simulated_zones = []
    affected_zones = []
    for zone in zones:
        simulated = dict(zone)
        simulated["score"] = max(
            0,
            min(100, zone["score"] + scenario.risk_score_delta.get(zone["id"], 0)),
        )
        simulated["risk"] = (
            "CRITICAL"
            if simulated["score"] >= 85
            else "HIGH"
            if simulated["score"] >= 70
            else "MODERATE"
            if simulated["score"] >= 40
            else "LOW"
        )
        simulated["exposure"] = round(zone["exposure"] * scenario.exposure_multiplier)
        simulated_zones.append(simulated)
        if simulated["score"] != zone["score"] or simulated["exposure"] != zone["exposure"]:
            affected_zones.append(
                {
                    "zone_id": zone["id"],
                    "baseline_score": zone["score"],
                    "simulated_score": simulated["score"],
                    "baseline_exposure": zone["exposure"],
                    "simulated_exposure": simulated["exposure"],
                }
            )

    demand_by_zone = _demands_by_zone(state)
    baseline_demands = [
        ZoneDemand(
            zone_id=zone["id"],
            risk_score=zone["score"],
            exposed_population=zone["exposure"],
            urgency=scenario.urgency_by_zone.get(zone["id"], zone["score"]),
            infrastructure_impact=scenario.infrastructure_impact_by_zone.get(zone["id"], 0),
            medical_need=scenario.medical_need_by_zone.get(zone["id"], 0),
            demand=demand_by_zone.get(zone["id"], {}),
        )
        for zone in zones
    ]
    simulated_demands = [
        demand.model_copy(
            update={
                "risk_score": next(zone["score"] for zone in simulated_zones if zone["id"] == demand.zone_id),
                "exposed_population": next(zone["exposure"] for zone in simulated_zones if zone["id"] == demand.zone_id),
            }
        )
        for demand in baseline_demands
    ]

    stock = {
        ResourceType(item["resource"]): item["available"]
        for item in inventory_snapshot(state)
        if item["resource"] in ResourceType._value2member_map_
    }
    simulated_stock = {
        resource: quantity
        - round(quantity * scenario.resource_availability_reduction.get(resource, 0) / 100)
        for resource, quantity in stock.items()
    }
    baseline_recommendations = simulate_allocation(
        AllocationScenario(zones=baseline_demands, available_stock=stock)
    )
    simulated_recommendations = simulate_allocation(
        AllocationScenario(zones=simulated_demands, available_stock=simulated_stock)
    )

    assumptions = [
        "Scenario calculations are deterministic and do not write to requests or inventory.",
        "Pending request quantities are used as demand; no additional demand is inferred.",
        "Zone risk score is used as the default urgency proxy when no zone urgency is supplied.",
        "Risk score changes and population exposure multipliers are user-provided what-if assumptions, not forecasts.",
    ]
    return ScenarioResult(
        name=scenario.name,
        baseline_metrics=_metrics(zones),
        simulated_metrics=_metrics(simulated_zones),
        affected_zones=affected_zones,
        baseline_recommendations=baseline_recommendations,
        simulated_recommendations=simulated_recommendations,
        assumptions=assumptions,
        unsupported_inputs=[
            "Road network, closures, and response travel accessibility are not in the current data model.",
            "Hospital, shelter, and facility capacities are not in the current data model.",
            "No validated flood-depth or hazard-feed adapter is configured.",
        ],
    )