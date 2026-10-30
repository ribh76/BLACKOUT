"""Hand-calculated comparison measures over a two-node, 90-minute city."""

from datetime import timedelta

import pytest

from app.models.infrastructure import InfrastructureType, NodeStatus
from app.models.risk import NodeRisk, RiskRanking
from app.models.scenario import ResourceInventory
from app.models.simulation import SimulationMetrics, SimulationResult
from app.services.city_data import load_city
from app.services.counterfactual_metrics import compare_results
from app.services.dependency_data import load_dependencies
from app.services.scenarios import ScenarioStore, load_scenario
from app.services.simulation import initial_simulation_state


def _risk_row(node, score: float) -> NodeRisk:
    return NodeRisk(
        node_id=node.id,
        name=node.name,
        type=node.type,
        status=node.status,
        impact_score=0,
        human_exposure=0,
        systemic_impact=0,
        population_vulnerability=0,
        dependency_degradation=0,
        load_stress=0,
        environmental_stress=0,
        backup_resilience=0,
        failure_probability=0,
        risk_score=score,
        operational_priority=0,
        direct_dependents=0,
        downstream_dependents=0,
        downstream_node_ids=[],
        primary_drivers=[],
        quality_indicators=[],
    )


def _fixture_run(
    snapshot,
    hospital_statuses: list[NodeStatus],
    neighborhood_statuses: list[NodeStatus],
    final_risk_scores: tuple[float, float],
) -> SimulationResult:
    states = []
    for index, (hospital, neighborhood) in enumerate(
        zip(hospital_statuses, neighborhood_statuses)
    ):
        tick = initial_simulation_state(snapshot)
        tick.elapsed_minutes = index * 30
        tick.city_state.simulation_time += timedelta(minutes=index * 30)
        tick.city_state.nodes[0].status = hospital
        tick.city_state.nodes[1].status = neighborhood
        states.append(tick)
    final = states[-1].city_state
    ranking = RiskRanking(
        scenario_id=snapshot.scenario_id,
        simulation_time=final.simulation_time.isoformat(),
        count=2,
        nodes=[
            _risk_row(final.nodes[0], final_risk_scores[0]),
            _risk_row(final.nodes[1], final_risk_scores[1]),
        ],
    )
    return SimulationResult(
        scenario_id=snapshot.scenario_id,
        tick_minutes=[30, 60, 90],
        states=states,
        events=[],
        final_node_states=[node.model_copy(deep=True) for node in final.nodes],
        final_metrics=SimulationMetrics(
            affected_population=(
                final.nodes[1].population_served
                if final.nodes[1].status is not NodeStatus.OPERATIONAL
                else 0
            ),
            failed_infrastructure_count=sum(
                node.status is NodeStatus.FAILED for node in final.nodes
            ),
            critical_facility_count=sum(
                node.type is InfrastructureType.HOSPITAL
                and node.status in {NodeStatus.CRITICAL, NodeStatus.FAILED}
                for node in final.nodes
            ),
        ),
        risk_rankings={90: ranking},
    )


def _small_city():
    city = load_city()
    store = ScenarioStore(load_scenario(city), city, load_dependencies(city).edges)
    snapshot = store.pristine_scenario_state()
    snapshot.nodes = [
        next(node for node in snapshot.nodes if node.id == node_id)
        for node_id in ("hospital-downtown", "neighborhood-downtown")
    ]
    snapshot.nodes[1].population_served = 100
    snapshot.dependency_edges = []
    return snapshot


def test_hand_calculated_comparison_and_unobserved_recovery():
    snapshot = _small_city()
    baseline = _fixture_run(
        snapshot,
        [NodeStatus.CRITICAL, NodeStatus.FAILED, NodeStatus.FAILED, NodeStatus.FAILED],
        [NodeStatus.DEGRADED] * 4,
        (12, 8),
    )
    response = _fixture_run(
        snapshot,
        [NodeStatus.CRITICAL] + [NodeStatus.OPERATIONAL] * 3,
        [NodeStatus.DEGRADED, NodeStatus.DEGRADED] + [NodeStatus.OPERATIONAL] * 2,
        (3, 2),
    )
    used = ResourceInventory(
        mobile_generators=0,
        fuel_gallons=100,
        electrical_crews=0,
        traffic_crews=0,
        emergency_vehicles=1,
        response_personnel=1,
    )

    summary = compare_results(baseline, response, used)

    assert summary.baseline.critical_failures == 1
    assert summary.response.critical_failures == 0
    assert summary.improvement.critical_failures == 1
    assert (summary.baseline.people_affected, summary.response.people_affected) == (
        100,
        0,
    )
    assert summary.improvement.people_affected == 100
    assert summary.baseline.hospital_downtime_minutes == 90
    assert summary.response.hospital_downtime_minutes == 30
    assert summary.improvement.hospital_downtime_minutes == 60
    assert (summary.baseline.system_risk, summary.response.system_risk) == (20, 5)
    assert summary.improvement.system_risk == 15
    assert summary.baseline.recovery_time_minutes is None
    assert summary.response.recovery_time_minutes == 60
    assert summary.improvement.recovery_time_minutes is None
    assert (
        summary.baseline.remaining_impaired_nodes,
        summary.response.remaining_impaired_nodes,
    ) == (2, 0)
    assert summary.baseline.resource_utilization.fuel_gallons == 0
    assert summary.response.resource_utilization == used
    assert summary.improvement.additional_resources_used == used


def test_comparison_rejects_different_horizons():
    snapshot = _small_city()
    operational = [NodeStatus.OPERATIONAL] * 4
    first = _fixture_run(snapshot, operational, operational, (0, 0))
    second = first.model_copy(deep=True)
    second.tick_minutes = [30, 60]
    zero = ResourceInventory(
        mobile_generators=0,
        fuel_gallons=0,
        electrical_crews=0,
        traffic_crews=0,
        emergency_vehicles=0,
        response_personnel=0,
    )
    with pytest.raises(ValueError, match="different simulation horizons"):
        compare_results(first, second, zero)


def test_recovery_improvement_and_condition_mismatch():
    snapshot = _small_city()
    baseline = _fixture_run(
        snapshot,
        [NodeStatus.CRITICAL] * 3 + [NodeStatus.OPERATIONAL],
        [NodeStatus.DEGRADED] * 3 + [NodeStatus.OPERATIONAL],
        (5, 5),
    )
    response = _fixture_run(
        snapshot,
        [NodeStatus.CRITICAL] * 2 + [NodeStatus.OPERATIONAL] * 2,
        [NodeStatus.DEGRADED] * 2 + [NodeStatus.OPERATIONAL] * 2,
        (3, 2),
    )
    zero = ResourceInventory(
        mobile_generators=0,
        fuel_gallons=0,
        electrical_crews=0,
        traffic_crews=0,
        emergency_vehicles=0,
        response_personnel=0,
    )
    summary = compare_results(baseline, response, zero)
    assert summary.baseline.recovery_time_minutes == 90
    assert summary.response.recovery_time_minutes == 60
    assert summary.improvement.recovery_time_minutes == 30

    response.states[1].city_state.grid_load = 0.5
    with pytest.raises(ValueError, match="different clocks or conditions"):
        compare_results(baseline, response, zero)
