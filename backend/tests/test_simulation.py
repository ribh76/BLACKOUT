"""Deterministic cascade rules at the public simulation-service boundary."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.dependency import DependencyEdge, DependencyRequirement
from app.models.infrastructure import NodeStatus
from app.models.simulation import SimulationEventKind, SimulationResult
from app.services.city_data import load_city
from app.services.dependency_data import load_dependencies
from app.services.scenarios import (
    ScenarioStore,
    apply_initial_event,
    load_scenario,
)
from app.services.simulation import (
    SIMULATION_TICKS,
    advance_tick,
    initial_simulation_state,
    run_simulation,
)


def started_snapshot():
    city = load_city()
    store = ScenarioStore(load_scenario(city), city, load_dependencies(city).edges)
    return store.start_scenario()


def test_transition_retains_all_matured_dependency_causes() -> None:
    snapshot = started_snapshot()
    snapshot.dependency_edges = [
        edge.model_copy(update={"failure_delay_minutes": 0})
        for edge in snapshot.dependency_edges
        if edge.dependent_id == "hospital-downtown"
        and edge.provider_id in {"substation-03", "warehouse-north"}
    ]
    warehouse = next(node for node in snapshot.nodes if node.id == "warehouse-north")
    warehouse.status = NodeStatus.FAILED
    _, events = advance_tick(initial_simulation_state(snapshot))
    event = next(
        event
        for event in events
        if event.node_id == "hospital-downtown"
        and event.kind is SimulationEventKind.STATUS_TRANSITION
    )
    assert {cause.provider_id for cause in event.dependency_causes} == {
        "substation-03",
        "warehouse-north",
    }
    assert all(
        cause.provider_status is NodeStatus.FAILED for cause in event.dependency_causes
    )
    assert all(cause.contribution > 0 for cause in event.dependency_causes)
    assert {cause.dependency_type.value for cause in event.dependency_causes} == {
        "POWER",
        "SUPPLY",
    }


def one_edge(provider_id: str, dependent_id: str, delay: int = 0) -> DependencyEdge:
    city = load_city()
    edge = next(
        edge
        for edge in load_dependencies(city).edges
        if edge.provider_id == provider_id and edge.dependent_id == dependent_id
    )
    return edge.model_copy(update={"failure_delay_minutes": delay})


def node_status(result, minute: int, node_id: str) -> NodeStatus:
    state = next(state for state in result.states if state.elapsed_minutes == minute)
    return next(node.status for node in state.city_state.nodes if node.id == node_id)


def test_fixed_clock_and_replay_are_deterministic_without_mutating_input() -> None:
    snapshot = started_snapshot()
    original = snapshot.model_dump(mode="json")

    first = run_simulation(snapshot)
    second = run_simulation(snapshot)

    assert SIMULATION_TICKS == (30, 60, 90, 120)
    assert first.tick_minutes == [30, 60, 90, 120]
    assert [state.elapsed_minutes for state in first.states] == [0, 30, 60, 90, 120]
    assert [state.city_state.simulation_time for state in first.states] == [
        snapshot.simulation_time + timedelta(minutes=minute)
        for minute in (0, 30, 60, 90, 120)
    ]
    assert first == second
    assert snapshot.model_dump(mode="json") == original
    assert first.events[0].node_id == "substation-03"
    assert first.events[0].old_status is NodeStatus.OPERATIONAL
    assert first.events[0].new_status is NodeStatus.FAILED


def test_dependency_delay_and_one_rung_status_progression() -> None:
    snapshot = started_snapshot()
    snapshot.dependency_edges = [
        one_edge("substation-03", "hospital-downtown", delay=60)
    ]
    result = run_simulation(snapshot)

    assert [
        node_status(result, minute, "hospital-downtown")
        for minute in (0, 30, 60, 90, 120)
    ] == [
        NodeStatus.OPERATIONAL,
        NodeStatus.OPERATIONAL,
        NodeStatus.DEGRADED,
        NodeStatus.CRITICAL,
        NodeStatus.FAILED,
    ]
    transitions = [
        event
        for event in result.events
        if event.node_id == "hospital-downtown"
        and event.kind is SimulationEventKind.STATUS_TRANSITION
    ]
    assert [event.elapsed_minutes for event in transitions] == [60, 90, 120]
    assert all(event.source_node_id == "substation-03" for event in transitions)


def test_multi_hop_pressure_uses_previous_tick_only() -> None:
    snapshot = started_snapshot()
    snapshot.dependency_edges = [
        one_edge("substation-03", "intersection-santa-clara-market"),
        one_edge("intersection-santa-clara-market", "hospital-downtown").model_copy(
            update={"weight": 1.0, "requirement": DependencyRequirement.CRITICAL}
        ),
    ]
    result = run_simulation(snapshot)

    assert (
        node_status(result, 30, "intersection-santa-clara-market")
        is NodeStatus.DEGRADED
    )
    assert node_status(result, 30, "hospital-downtown") is NodeStatus.OPERATIONAL
    assert node_status(result, 60, "hospital-downtown") is NodeStatus.DEGRADED
    hospital_transition = next(
        event
        for event in result.events
        if event.node_id == "hospital-downtown"
        and event.kind is SimulationEventKind.STATUS_TRANSITION
    )
    assert hospital_transition.source_node_id == "intersection-santa-clara-market"


def test_backup_activates_depletes_and_changes_power_failure_timing() -> None:
    snapshot = started_snapshot()
    snapshot.dependency_edges = [one_edge("substation-03", "hospital-downtown")]
    result = run_simulation(snapshot)
    hospital = [
        next(node for node in state.city_state.nodes if node.id == "hospital-downtown")
        for state in result.states
    ]

    assert [node.backup_remaining for node in hospital] == [170, 64, 0, 0, 0]
    assert [node.status for node in hospital] == [
        NodeStatus.OPERATIONAL,
        NodeStatus.DEGRADED,
        NodeStatus.CRITICAL,
        NodeStatus.FAILED,
        NodeStatus.FAILED,
    ]
    backup_events = [
        (event.elapsed_minutes, event.kind)
        for event in result.events
        if event.node_id == "hospital-downtown"
        and event.kind is not SimulationEventKind.STATUS_TRANSITION
    ]
    assert backup_events == [
        (30, SimulationEventKind.BACKUP_ACTIVATED),
        (60, SimulationEventKind.BACKUP_DEPLETED),
    ]


def test_hospital_backup_delays_critical_power_loss() -> None:
    snapshot = started_snapshot()
    snapshot.dependency_edges = [one_edge("substation-03", "hospital-downtown")]
    hospital = next(node for node in snapshot.nodes if node.id == "hospital-downtown")
    hospital.backup_capacity = 500
    hospital.backup_remaining = 500
    protected = run_simulation(snapshot)
    unprotected_snapshot = snapshot.model_copy(deep=True)
    unprotected_hospital = next(
        node for node in unprotected_snapshot.nodes if node.id == "hospital-downtown"
    )
    unprotected_hospital.backup_remaining = 0
    unprotected = run_simulation(unprotected_snapshot)

    assert node_status(protected, 30, "hospital-downtown") is NodeStatus.DEGRADED
    assert node_status(protected, 60, "hospital-downtown") is NodeStatus.DEGRADED
    assert node_status(unprotected, 60, "hospital-downtown") is NodeStatus.CRITICAL


def test_pharmacy_refrigeration_escalates_after_unprotected_power_loss() -> None:
    snapshot = started_snapshot()
    snapshot.dependency_edges = [one_edge("substation-03", "pharmacy-downtown")]
    pharmacy = next(node for node in snapshot.nodes if node.id == "pharmacy-downtown")
    pharmacy.backup_remaining = 0
    result = run_simulation(snapshot)

    assert [
        state.refrigeration_unpowered_minutes.get("pharmacy-downtown", 0)
        for state in result.states
    ] == [0, 30, 60, 90, 120]
    assert [
        node_status(result, minute, "pharmacy-downtown") for minute in (0, 30, 60, 90)
    ] == [
        NodeStatus.OPERATIONAL,
        NodeStatus.DEGRADED,
        NodeStatus.CRITICAL,
        NodeStatus.FAILED,
    ]
    assert any(
        event.cause == "REFRIGERATION_LOSS"
        for event in result.events
        if event.node_id == "pharmacy-downtown"
    )


def test_pharmacy_backup_preserves_refrigeration_until_exhausted() -> None:
    snapshot = started_snapshot()
    snapshot.dependency_edges = [one_edge("substation-03", "pharmacy-downtown")]
    result = run_simulation(snapshot)

    assert [
        state.refrigeration_unpowered_minutes.get("pharmacy-downtown", 0)
        for state in result.states
    ] == [0, 0, 30, 60, 90]
    assert node_status(result, 60, "pharmacy-downtown") is NodeStatus.DEGRADED
    assert node_status(result, 90, "pharmacy-downtown") is NodeStatus.CRITICAL


def test_refrigeration_outage_does_not_fail_below_asset_threshold() -> None:
    snapshot = started_snapshot()
    snapshot.dependency_edges = [
        one_edge("substation-03", "pharmacy-downtown").model_copy(
            update={"weight": 0.1}
        )
    ]
    pharmacy = next(node for node in snapshot.nodes if node.id == "pharmacy-downtown")
    pharmacy.backup_remaining = 0
    result = run_simulation(snapshot)

    assert node_status(result, 60, "pharmacy-downtown") is NodeStatus.CRITICAL
    assert node_status(result, 90, "pharmacy-downtown") is NodeStatus.CRITICAL
    assert node_status(result, 120, "pharmacy-downtown") is NodeStatus.CRITICAL


def test_intersection_signal_loss_waits_for_backup_depletion() -> None:
    snapshot = started_snapshot()
    snapshot.dependency_edges = [
        one_edge("substation-03", "intersection-santa-clara-market")
    ]
    intersection = next(
        node for node in snapshot.nodes if node.id == "intersection-santa-clara-market"
    )
    intersection.backup_capacity = 3000
    intersection.backup_remaining = 3000
    result = run_simulation(snapshot)

    assert [
        state.signal_unpowered_minutes.get("intersection-santa-clara-market", 0)
        for state in result.states
    ] == [0, 0, 0, 0, 0]
    assert node_status(result, 120, "intersection-santa-clara-market") in (
        NodeStatus.OPERATIONAL,
        NodeStatus.DEGRADED,
    )


def test_intersection_without_backup_loses_signals_in_stages() -> None:
    snapshot = started_snapshot()
    snapshot.dependency_edges = [
        one_edge("substation-03", "intersection-santa-clara-market")
    ]
    intersection = next(
        node for node in snapshot.nodes if node.id == "intersection-santa-clara-market"
    )
    intersection.backup_remaining = 0
    result = run_simulation(snapshot)

    assert [
        state.signal_unpowered_minutes.get("intersection-santa-clara-market", 0)
        for state in result.states
    ] == [0, 30, 60, 90, 120]
    assert [
        node_status(result, minute, "intersection-santa-clara-market")
        for minute in (0, 30, 60, 90)
    ] == [
        NodeStatus.OPERATIONAL,
        NodeStatus.DEGRADED,
        NodeStatus.CRITICAL,
        NodeStatus.FAILED,
    ]
    assert any(
        event.cause == "SIGNAL_LOSS"
        for event in result.events
        if event.node_id == "intersection-santa-clara-market"
    )


def test_cooling_center_heat_demand_reduces_spare_capacity() -> None:
    snapshot = started_snapshot()
    snapshot.dependency_edges = []
    center = next(node for node in snapshot.nodes if node.id == "cooling-center-east")
    center.current_load = center.capacity * 0.9
    heated = run_simulation(snapshot)
    mild_snapshot = snapshot.model_copy(deep=True)
    mild_snapshot.temperature_f = 95
    mild = run_simulation(mild_snapshot)

    assert node_status(heated, 30, "cooling-center-east") is NodeStatus.DEGRADED
    assert node_status(mild, 30, "cooling-center-east") is NodeStatus.OPERATIONAL


def test_neighborhood_transition_records_resident_impact_once() -> None:
    snapshot = started_snapshot()
    snapshot.dependency_edges = [one_edge("substation-03", "neighborhood-downtown")]
    result = run_simulation(snapshot)

    assert node_status(result, 30, "neighborhood-downtown") is NodeStatus.DEGRADED
    neighborhood_events = [
        event for event in result.events if event.node_id == "neighborhood-downtown"
    ]
    assert [event.population_exposed for event in neighborhood_events] == [17200] * len(
        neighborhood_events
    )
    assert result.final_metrics.affected_population == 17200


def test_initial_neighborhood_event_also_records_resident_impact() -> None:
    snapshot = started_snapshot()
    snapshot.dependency_edges = []
    snapshot = apply_initial_event(
        snapshot, "neighborhood-downtown", NodeStatus.DEGRADED
    )
    result = run_simulation(snapshot)

    initial = next(
        event
        for event in result.events
        if event.elapsed_minutes == 0 and event.node_id == "neighborhood-downtown"
    )
    assert initial.population_exposed == 17200
    assert result.final_metrics.affected_population == 17200


def test_load_stress_alone_uses_failure_threshold_and_all_status_rungs() -> None:
    snapshot = started_snapshot()
    snapshot.dependency_edges = []
    node = next(node for node in snapshot.nodes if node.id == "substation-01")
    node.current_load = node.capacity
    result = run_simulation(snapshot)

    assert [
        node_status(result, minute, "substation-01") for minute in (0, 30, 60, 90, 120)
    ] == [
        NodeStatus.OPERATIONAL,
        NodeStatus.DEGRADED,
        NodeStatus.CRITICAL,
        NodeStatus.FAILED,
        NodeStatus.FAILED,
    ]


def test_recovery_waits_for_node_recovery_delay() -> None:
    snapshot = started_snapshot()
    snapshot.dependency_edges = []
    snapshot = apply_initial_event(
        snapshot, "intersection-santa-clara-market", NodeStatus.DEGRADED
    )
    first, _ = advance_tick(initial_simulation_state(snapshot))
    second, _ = advance_tick(first)

    statuses = [
        next(
            node.status
            for node in state.city_state.nodes
            if node.id == "intersection-santa-clara-market"
        )
        for state in (first, second)
    ]
    assert statuses == [NodeStatus.DEGRADED, NodeStatus.OPERATIONAL]


def test_backup_deactivates_when_power_dependency_recovers() -> None:
    snapshot = started_snapshot()
    snapshot.dependency_edges = [one_edge("substation-03", "hospital-downtown")]
    first, _ = advance_tick(initial_simulation_state(snapshot))
    assert "hospital-downtown" in first.backup_active
    first.city_state.nodes = [
        node.model_copy(update={"status": NodeStatus.OPERATIONAL})
        if node.id == "substation-03"
        else node
        for node in first.city_state.nodes
    ]
    first.impaired_since_minutes.pop("substation-03")

    second, events = advance_tick(first)
    assert "hospital-downtown" not in second.backup_active
    assert any(
        event.node_id == "hospital-downtown"
        and event.kind is SimulationEventKind.BACKUP_DEACTIVATED
        for event in events
    )


def test_advance_rejects_ticks_beyond_fixed_horizon() -> None:
    state = initial_simulation_state(started_snapshot())
    for _ in SIMULATION_TICKS:
        state, _ = advance_tick(state)
    with pytest.raises(ValueError, match="Unsupported simulation tick"):
        advance_tick(state)


def test_known_cascade_returns_complete_timeline_and_final_metrics() -> None:
    result = run_simulation(started_snapshot())

    assert [state.elapsed_minutes for state in result.states] == [0, 30, 60, 90, 120]
    assert [event.elapsed_minutes for event in result.events] == sorted(
        event.elapsed_minutes for event in result.events
    )
    assert len(result.final_node_states) == 36
    assert {node.id: node.status for node in result.final_node_states}[
        "hospital-downtown"
    ] is NodeStatus.FAILED
    assert result.final_node_states == result.states[-1].city_state.nodes
    assert result.final_metrics.affected_population == 47300
    assert result.final_metrics.failed_infrastructure_count == 12
    assert result.final_metrics.critical_facility_count == 7
    assert result.final_metrics.system_risk_score is None

    transitions = [
        event
        for event in result.events
        if event.kind is SimulationEventKind.STATUS_TRANSITION
    ]
    assert transitions
    assert all(
        event.node_id and event.cause and event.explanation for event in transitions
    )
    assert all(event.old_status is not event.new_status for event in transitions)
    assert all(
        event.time
        == result.states[event.elapsed_minutes // 30].city_state.simulation_time
        for event in transitions
    )
    hospital = [
        event
        for event in transitions
        if event.node_id == "hospital-downtown" and event.elapsed_minutes > 0
    ]
    assert [event.new_status for event in hospital] == [
        NodeStatus.DEGRADED,
        NodeStatus.CRITICAL,
        NodeStatus.FAILED,
    ]
    assert all(event.source_node_id == "substation-03" for event in hospital)
    assert "Downtown Grid Hub" in hospital[0].explanation

    for before, after in zip(result.states, result.states[1:]):
        before_status = {node.id: node.status for node in before.city_state.nodes}
        changed_nodes = {
            (node.id, before_status[node.id], node.status)
            for node in after.city_state.nodes
            if node.status is not before_status[node.id]
        }
        recorded = {
            (event.node_id, event.old_status, event.new_status)
            for event in transitions
            if event.elapsed_minutes == after.elapsed_minutes
        }
        assert recorded == changed_nodes


def test_simulate_endpoint_replays_identically_after_reset() -> None:
    path = "/api/scenarios/extreme-heat-grid-failure"
    with TestClient(app) as client:
        first = client.post(f"{path}/simulate")
        reset = client.post(f"{path}/reset")
        second = client.post(f"{path}/simulate")
        missing = client.post("/api/scenarios/unknown/simulate")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    result = SimulationResult.model_validate_json(first.text)
    assert result.final_metrics.affected_population == 47300
    assert len(result.events) > 2
    assert reset.status_code == 200
    assert reset.json()["event_history"] == []
    assert all(node["status"] == "OPERATIONAL" for node in reset.json()["nodes"])
    assert missing.status_code == 404
