"""Comparable measures derived from complete counterfactual timelines."""

from math import fsum

from app.models.counterfactual import (
    ComparisonImprovement,
    ComparisonSummary,
    RunOutcomeMetrics,
)
from app.models.infrastructure import InfrastructureType, NodeStatus
from app.models.scenario import ResourceInventory
from app.models.simulation import SimulationResult
from app.services.dependency_queries import CRITICAL_FACILITY_TYPES


def _validate_matching_runs(
    baseline: SimulationResult, response: SimulationResult
) -> None:
    """Reject a comparison whose clocks or external conditions differ."""

    if baseline.scenario_id != response.scenario_id:
        raise ValueError("Comparison runs use different scenarios")
    if baseline.tick_minutes != response.tick_minutes:
        raise ValueError("Comparison runs use different simulation horizons")
    if len(baseline.states) != len(response.states) or not baseline.states:
        raise ValueError("Comparison timelines have different lengths")
    for first, second in zip(baseline.states, response.states):
        a, b = first.city_state, second.city_state
        if (
            first.elapsed_minutes != second.elapsed_minutes
            or a.simulation_time != b.simulation_time
            or a.temperature_f != b.temperature_f
            or a.grid_load != b.grid_load
            or a.duration_minutes != b.duration_minutes
            or a.scenario_id != b.scenario_id
        ):
            raise ValueError("Comparison runs use different clocks or conditions")


def _recovery_time(result: SimulationResult) -> int | None:
    """First tick with every node operational through the remaining horizon."""

    for index, state in enumerate(result.states):
        if all(
            node.status is NodeStatus.OPERATIONAL
            for later in result.states[index:]
            for node in later.city_state.nodes
        ):
            return state.elapsed_minutes
    return None


def _hospital_downtime(result: SimulationResult) -> int:
    """Sum critical/failed hospital minutes over half-open tick intervals."""

    return sum(
        (following.elapsed_minutes - current.elapsed_minutes)
        * sum(
            node.type is InfrastructureType.HOSPITAL
            and node.status in {NodeStatus.CRITICAL, NodeStatus.FAILED}
            for node in current.city_state.nodes
        )
        for current, following in zip(result.states, result.states[1:])
    )


def _metrics(
    result: SimulationResult, resources: ResourceInventory
) -> RunOutcomeMetrics:
    final = result.states[-1]
    risk = result.risk_rankings.get(final.elapsed_minutes)
    if risk is None:
        raise ValueError("Final risk ranking is missing from comparison run")
    recovery = _recovery_time(result)
    return RunOutcomeMetrics(
        critical_failures=sum(
            node.type in CRITICAL_FACILITY_TYPES and node.status is NodeStatus.FAILED
            for node in final.city_state.nodes
        ),
        people_affected=result.final_metrics.affected_population,
        hospital_downtime_minutes=_hospital_downtime(result),
        system_risk=round(fsum(node.risk_score for node in risk.nodes), 6),
        recovery_time_minutes=recovery,
        recovered_by_horizon=recovery is not None,
        remaining_impaired_nodes=sum(
            node.status is not NodeStatus.OPERATIONAL for node in final.city_state.nodes
        ),
        resource_utilization=resources.model_copy(deep=True),
    )


def compare_results(
    baseline: SimulationResult,
    response: SimulationResult,
    resources_used: ResourceInventory,
) -> ComparisonSummary:
    """Return signed changes and an explicit interpretation of each measure."""

    _validate_matching_runs(baseline, response)
    zero = ResourceInventory(**dict.fromkeys(resources_used.model_dump(), 0))
    before = _metrics(baseline, zero)
    after = _metrics(response, resources_used)
    recovery_change = (
        before.recovery_time_minutes - after.recovery_time_minutes
        if before.recovery_time_minutes is not None
        and after.recovery_time_minutes is not None
        else None
    )
    return ComparisonSummary(
        baseline=before,
        response=after,
        improvement=ComparisonImprovement(
            critical_failures=before.critical_failures - after.critical_failures,
            people_affected=before.people_affected - after.people_affected,
            hospital_downtime_minutes=(
                before.hospital_downtime_minutes - after.hospital_downtime_minutes
            ),
            system_risk=round(before.system_risk - after.system_risk, 6),
            recovery_time_minutes=recovery_change,
            remaining_impaired_nodes=(
                before.remaining_impaired_nodes - after.remaining_impaired_nodes
            ),
            additional_resources_used=resources_used.model_copy(deep=True),
        ),
        assumptions=[
            "Critical failures count FAILED substations, hospitals, pharmacies, "
            "shelters, and cooling centers at the final tick.",
            "People affected uses the simulator's final affected-neighborhood count.",
            "Hospital downtime sums CRITICAL or FAILED hospital-minutes over "
            "half-open intervals between simulator ticks.",
            "System risk sums final 0-100 node risk scores, matching the optimizer.",
            "Recovery is the first tick when all nodes are OPERATIONAL for the "
            "rest of the horizon; null means it was not observed.",
            "Resources are reserved for the full response plan; baseline uses zero.",
            "Improvement is baseline minus response for harm metrics; positive "
            "means less harm. Additional resources used is response minus baseline.",
        ],
    )
