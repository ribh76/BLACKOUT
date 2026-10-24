"""Deterministic 30-minute cascade rules over scenario snapshots."""

from datetime import timedelta

from app.models.dependency import DependencyRequirement, DependencyType
from app.models.infrastructure import InfrastructureNode, InfrastructureType, NodeStatus
from app.models.scenario import CityState, ScenarioEvent
from app.models.simulation import (
    SimulationEvent,
    SimulationEventKind,
    SimulationMetrics,
    SimulationResult,
    SimulationState,
)
from app.services.dependency_queries import CRITICAL_FACILITY_TYPES

SIMULATION_TICKS = (30, 60, 90, 120)
TICK_MINUTES = 30
STATUS_ORDER = (
    NodeStatus.OPERATIONAL,
    NodeStatus.DEGRADED,
    NodeStatus.CRITICAL,
    NodeStatus.FAILED,
)
STATUS_PRESSURE = {
    NodeStatus.OPERATIONAL: 0.0,
    NodeStatus.DEGRADED: 0.35,
    NodeStatus.CRITICAL: 0.7,
    NodeStatus.FAILED: 1.0,
}


def initial_simulation_state(snapshot: CityState) -> SimulationState:
    """Capture T+0 without changing the caller's scenario snapshot."""

    return SimulationState(
        elapsed_minutes=0,
        city_state=snapshot.model_copy(deep=True),
        impaired_since_minutes={
            node.id: 0
            for node in snapshot.nodes
            if node.status is not NodeStatus.OPERATIONAL
        },
        healthy_minutes={},
        backup_active=set(),
    )


def _load_stress(node: InfrastructureNode, snapshot: CityState) -> float:
    """Excess local utilization plus bounded grid and heat stress."""

    local = max(0.0, node.current_load / node.capacity - 0.9)
    grid = (
        max(0.0, snapshot.grid_load - 0.9)
        if node.type is InfrastructureType.SUBSTATION
        else 0.0
    )
    heat = max(0.0, snapshot.temperature_f - 100.0) / 100.0 * node.vulnerability
    return local + grid + heat


def _dependency_pressure(
    node_id: str,
    previous: SimulationState,
    backup_coverage: float,
) -> tuple[float, str | None, bool]:
    """Combine matured provider pressures; retain strongest source for attribution."""

    nodes = {node.id: node for node in previous.city_state.nodes}
    pressure_remaining = 1.0
    strongest = 0.0
    source_id = None
    power_outage = False
    for edge in sorted(
        (
            edge
            for edge in previous.city_state.dependency_edges
            if edge.dependent_id == node_id
        ),
        key=lambda edge: edge.provider_id,
    ):
        provider = nodes[edge.provider_id]
        onset = previous.impaired_since_minutes.get(provider.id)
        if (
            onset is None
            or previous.elapsed_minutes + TICK_MINUTES - onset
            < edge.failure_delay_minutes
        ):
            continue
        contribution = STATUS_PRESSURE[provider.status] * edge.weight
        if edge.requirement is DependencyRequirement.OPTIONAL:
            contribution *= 0.5
        if edge.dependency_type is DependencyType.POWER and provider.status in (
            NodeStatus.CRITICAL,
            NodeStatus.FAILED,
        ):
            power_outage = True
            contribution *= 1.0 - backup_coverage
        pressure_remaining *= 1.0 - contribution
        if contribution > strongest:
            strongest = contribution
            source_id = provider.id
    return 1.0 - pressure_remaining, source_id, power_outage


def _next_status(
    current: NodeStatus,
    pressure: float,
    effective_ratio: float,
    stress: float,
    healthy_minutes: int,
    recovery_delay: int,
    failure_threshold: float,
) -> NodeStatus:
    """Move at most one status rung per tick; failure needs prior criticality."""

    if current is NodeStatus.FAILED:
        return current  # Repair is an intervention, not spontaneous recovery.
    if effective_ratio >= failure_threshold:
        target = NodeStatus.FAILED
    elif effective_ratio >= 1.0 or pressure >= 0.75:
        target = NodeStatus.CRITICAL
    elif pressure >= 0.2 or stress >= 0.15:
        target = NodeStatus.DEGRADED
    else:
        target = NodeStatus.OPERATIONAL

    current_index = STATUS_ORDER.index(current)
    target_index = STATUS_ORDER.index(target)
    if target_index > current_index:
        return STATUS_ORDER[current_index + 1]
    if target_index < current_index and healthy_minutes >= recovery_delay:
        return STATUS_ORDER[current_index - 1]
    return current


def advance_tick(
    previous: SimulationState,
) -> tuple[SimulationState, list[SimulationEvent]]:
    """Advance one simultaneous tick; newly changed nodes influence the next tick."""

    elapsed = previous.elapsed_minutes + TICK_MINUTES
    if elapsed not in SIMULATION_TICKS:
        raise ValueError(f"Unsupported simulation tick T+{elapsed}")
    snapshot = previous.city_state.model_copy(deep=True)
    snapshot.simulation_time += timedelta(minutes=TICK_MINUTES)
    next_state = previous.model_copy(deep=True)
    next_state.elapsed_minutes = elapsed
    next_state.city_state = snapshot
    current_nodes = {node.id: node for node in previous.city_state.nodes}
    new_nodes = {node.id: node for node in snapshot.nodes}
    events: list[SimulationEvent] = []

    for node_id in sorted(current_nodes):
        current = current_nodes[node_id]
        node = new_nodes[node_id]
        backup_coverage = 0.0
        if current.backup_remaining > 0 and current.current_load > 0:
            backup_coverage = min(1.0, current.backup_capacity / current.current_load)
            backup_coverage *= current.backup_remaining / current.backup_capacity
        pressure, source_id, power_outage = _dependency_pressure(
            node_id, previous, backup_coverage
        )
        if not power_outage and node_id in previous.backup_active:
            next_state.backup_active.discard(node_id)
            events.append(
                SimulationEvent(
                    elapsed_minutes=elapsed,
                    time=snapshot.simulation_time,
                    kind=SimulationEventKind.BACKUP_DEACTIVATED,
                    node_id=node_id,
                    old_status=current.status,
                    new_status=current.status,
                    cause="POWER_RESTORED",
                    explanation=f"{node.name} stopped using backup power.",
                )
            )
        if power_outage and current.backup_remaining > 0:
            if node_id not in previous.backup_active:
                next_state.backup_active.add(node_id)
                events.append(
                    SimulationEvent(
                        elapsed_minutes=elapsed,
                        time=snapshot.simulation_time,
                        kind=SimulationEventKind.BACKUP_ACTIVATED,
                        node_id=node_id,
                        old_status=current.status,
                        new_status=current.status,
                        cause="POWER_DEPENDENCY",
                        source_node_id=source_id,
                        explanation=f"{node.name} activated backup power.",
                    )
                )
            node.backup_remaining = max(
                0.0, current.backup_remaining - current.current_load * TICK_MINUTES / 60
            )
            if node.backup_remaining == 0:
                next_state.backup_active.discard(node_id)
                events.append(
                    SimulationEvent(
                        elapsed_minutes=elapsed,
                        time=snapshot.simulation_time,
                        kind=SimulationEventKind.BACKUP_DEPLETED,
                        node_id=node_id,
                        old_status=current.status,
                        new_status=current.status,
                        cause="BACKUP_EXHAUSTED",
                        source_node_id=source_id,
                        explanation=f"{node.name} exhausted its backup reserve.",
                    )
                )

        stress = _load_stress(current, previous.city_state)
        effective_ratio = current.current_load / current.capacity * (1.0 + pressure)
        effective_ratio += stress
        if pressure < 0.2 and stress < 0.15:
            next_state.healthy_minutes[node_id] = (
                previous.healthy_minutes.get(node_id, 0) + TICK_MINUTES
            )
        else:
            next_state.healthy_minutes[node_id] = 0
        next_status = _next_status(
            current.status,
            pressure,
            effective_ratio,
            stress,
            next_state.healthy_minutes[node_id],
            current.recovery_time_minutes,
            current.failure_threshold,
        )
        if next_status is current.status:
            continue
        node.status = next_status
        if current.status is NodeStatus.OPERATIONAL:
            next_state.impaired_since_minutes[node_id] = elapsed
        if next_status is NodeStatus.OPERATIONAL:
            next_state.impaired_since_minutes.pop(node_id, None)
        cause = "DEPENDENCY_PRESSURE" if source_id else "LOAD_STRESS"
        if STATUS_ORDER.index(next_status) < STATUS_ORDER.index(current.status):
            cause = "RECOVERY_DELAY_ELAPSED"
        events.append(
            SimulationEvent(
                elapsed_minutes=elapsed,
                time=snapshot.simulation_time,
                kind=SimulationEventKind.STATUS_TRANSITION,
                node_id=node_id,
                old_status=current.status,
                new_status=next_status,
                cause=cause,
                source_node_id=source_id,
                explanation=(
                    f"{node.name} changed from {current.status.value} "
                    f"to {next_status.value}."
                ),
            )
        )
        snapshot.event_history.append(
            ScenarioEvent(
                sequence=len(snapshot.event_history),
                time=snapshot.simulation_time,
                node_id=node_id,
                status=next_status,
            )
        )
    return next_state, events


def _final_metrics(state: SimulationState) -> SimulationMetrics:
    nodes = state.city_state.nodes
    return SimulationMetrics(
        affected_population=sum(
            node.population_served
            for node in nodes
            if node.type is InfrastructureType.NEIGHBORHOOD
            and node.status is not NodeStatus.OPERATIONAL
        ),
        failed_infrastructure_count=sum(
            node.status is NodeStatus.FAILED for node in nodes
        ),
        critical_facility_count=sum(
            node.type in CRITICAL_FACILITY_TYPES
            and node.status in (NodeStatus.CRITICAL, NodeStatus.FAILED)
            for node in nodes
        ),
    )


def run_simulation(snapshot: CityState) -> SimulationResult:
    """Run the fixed T+30/60/90/120 clock from an initial scenario snapshot."""

    state = initial_simulation_state(snapshot)
    states = [state.model_copy(deep=True)]
    events = [
        SimulationEvent(
            elapsed_minutes=0,
            time=event.time,
            kind=SimulationEventKind.STATUS_TRANSITION,
            node_id=event.node_id,
            old_status=NodeStatus.OPERATIONAL,
            new_status=event.status,
            cause="INITIAL_SCENARIO_EVENT",
            explanation=(
                f"{event.node_id} changed from OPERATIONAL to {event.status.value}."
            ),
        )
        for event in snapshot.event_history
    ]
    for _ in SIMULATION_TICKS:
        state, tick_events = advance_tick(state)
        states.append(state.model_copy(deep=True))
        events.extend(tick_events)
    return SimulationResult(
        scenario_id=snapshot.scenario_id,
        tick_minutes=list(SIMULATION_TICKS),
        states=states,
        events=events,
        final_metrics=_final_metrics(state),
    )
