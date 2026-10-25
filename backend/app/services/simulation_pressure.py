"""Shared pressure and backup calculations for simulation and effect estimates."""

from app.models.dependency import DependencyRequirement, DependencyType
from app.models.infrastructure import InfrastructureNode, InfrastructureType, NodeStatus
from app.models.simulation import DependencyCause, SimulationState

TICK_MINUTES = 30
STATUS_PRESSURE = {
    NodeStatus.OPERATIONAL: 0.0,
    NodeStatus.DEGRADED: 0.35,
    NodeStatus.CRITICAL: 0.7,
    NodeStatus.FAILED: 1.0,
}


def backup_power_coverage(node: InfrastructureNode) -> float:
    """Fraction of power demand covered by the current backup reserve."""

    if node.backup_remaining <= 0 or node.current_load <= 0:
        return 0.0
    coverage = min(1.0, node.backup_capacity / node.current_load)
    if node.type is not InfrastructureType.HOSPITAL:
        coverage *= node.backup_remaining / node.backup_capacity
    return coverage


def dependency_pressure(
    node_id: str,
    previous: SimulationState,
    backup_coverage: float,
) -> tuple[float, float, float, str | None, str | None, bool, list[DependencyCause]]:
    """Combine matured provider pressures; retain strongest source for attribution."""

    nodes = {node.id: node for node in previous.city_state.nodes}
    pressure_remaining = 1.0
    power_remaining = 1.0
    other_remaining = 1.0
    strongest = 0.0
    source_id = None
    power_source_id = None
    power_outage = False
    causes = []
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
            if power_source_id is None:
                power_source_id = provider.id
            contribution *= 1.0 - backup_coverage
        if edge.dependency_type is DependencyType.POWER:
            power_remaining *= 1.0 - contribution
        else:
            other_remaining *= 1.0 - contribution
        pressure_remaining *= 1.0 - contribution
        if provider.status is not NodeStatus.OPERATIONAL:
            causes.append(
                DependencyCause(
                    provider_id=provider.id,
                    provider_status=provider.status,
                    dependency_type=edge.dependency_type,
                    weight=edge.weight,
                    contribution=contribution,
                )
            )
        if contribution > strongest:
            strongest = contribution
            source_id = provider.id
    return (
        1.0 - pressure_remaining,
        1.0 - power_remaining,
        1.0 - other_remaining,
        source_id or power_source_id,
        power_source_id,
        power_outage,
        causes,
    )
