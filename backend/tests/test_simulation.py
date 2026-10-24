"""Deterministic cascade rules at the public simulation-service boundary."""

from datetime import timedelta

import pytest

from app.models.dependency import DependencyEdge, DependencyRequirement
from app.models.infrastructure import NodeStatus
from app.models.simulation import SimulationEventKind
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
