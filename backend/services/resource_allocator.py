from __future__ import annotations

from math import ceil

if __package__ and "." in __package__:
    from ..schemas.allocation import (
        AllocationScenario,
        AllocationSimulation,
        ResourceRecommendation,
        ResourceType,
        ZoneDemand,
    )
else:
    from schemas.allocation import (
        AllocationScenario,
        AllocationSimulation,
        ResourceRecommendation,
        ResourceType,
        ZoneDemand,
    )


def priority_score(
    zone: ZoneDemand,
    *,
    maximum_exposure: int,
    weights: dict[str, float],
) -> float:
    normalized_exposure = (
        zone.exposed_population / maximum_exposure * 100
        if maximum_exposure
        else 0.0
    )
    score = (
        zone.risk_score * weights["risk_score"]
        + normalized_exposure * weights["exposure"]
        + zone.urgency * weights["urgency"]
        + zone.infrastructure_impact * weights["infrastructure_impact"]
        + zone.medical_need * weights["medical_need"]
    )
    return round(score, 2)


def simulate_allocation(scenario: AllocationScenario) -> AllocationSimulation:
    maximum_exposure = max(zone.exposed_population for zone in scenario.zones)
    weights = scenario.weights.model_dump()
    formula = (
        f"risk_score*{weights['risk_score']:.2f} + "
        f"normalized_exposure*{weights['exposure']:.2f} + "
        f"urgency*{weights['urgency']:.2f} + "
        f"infrastructure_impact*{weights['infrastructure_impact']:.2f} + "
        f"medical_need*{weights['medical_need']:.2f}; "
        "recommendation=ceil(requested*priority_score/100)"
    )
    ranked = sorted(
        (
            (priority_score(zone, maximum_exposure=maximum_exposure, weights=weights), zone)
            for zone in scenario.zones
        ),
        key=lambda item: (-item[0], item[1].zone_id),
    )
    stock = dict(scenario.available_stock)
    recommendations: list[ResourceRecommendation] = []

    for score, zone in ranked:
        for resource, requested in sorted(zone.demand.items(), key=lambda item: item[0].value):
            recommended = min(requested, ceil(requested * score / 100))
            available_before = stock.get(resource, 0)
            allocated = min(recommended, available_before)
            available_after = available_before - allocated
            unmet = requested - allocated
            stock[resource] = available_after
            recommendations.append(
                ResourceRecommendation(
                    zone_id=zone.zone_id,
                    resource=resource,
                    priority_score=score,
                    requested=requested,
                    recommended=recommended,
                    allocated=allocated,
                    unmet=unmet,
                    shortage=recommended - allocated,
                    available_before=available_before,
                    available_after=available_after,
                    explanation=(
                        f"Priority {score:.2f}/100 uses risk {zone.risk_score:.1f}, "
                        f"exposure {zone.exposed_population:,}, urgency {zone.urgency:.1f}, "
                        f"infrastructure impact {zone.infrastructure_impact:.1f}, and "
                        f"medical need {zone.medical_need:.1f}. Requested {requested}; "
                        f"recommended {recommended}; available stock allowed {allocated}; "
                        f"unmet requested demand {unmet}; shortage against recommendation "
                        f"{recommended - allocated}."
                    ),
                )
            )

    return AllocationSimulation(
        priority_formula=formula,
        recommendations=recommendations,
    )