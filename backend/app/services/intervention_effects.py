"""Describe actual intervention changes using the cascade's pressure rules."""

from app.models.infrastructure import InfrastructureNode, InfrastructureType, NodeStatus
from app.models.intervention import InterventionNodeEffect
from app.models.simulation import SimulationState
from app.services.simulation_pressure import backup_power_coverage, dependency_pressure


def _backup_minutes(node: InfrastructureNode) -> float | None:
    return 60 * node.backup_remaining / node.current_load if node.current_load else None


def _exposed_population(node: InfrastructureNode) -> int:
    return (
        node.population_served
        if node.type is InfrastructureType.NEIGHBORHOOD
        and node.status is not NodeStatus.OPERATIONAL
        else 0
    )


def describe_intervention_effects(
    before: SimulationState, after: SimulationState
) -> list[InterventionNodeEffect]:
    """Capture node changes and pressure changes at the same simulation clock."""

    previous_nodes = {node.id: node for node in before.city_state.nodes}
    effects = []
    for node in sorted(after.city_state.nodes, key=lambda node: node.id):
        previous = previous_nodes[node.id]
        old_pressure, old_power, *_ = dependency_pressure(
            node.id, before, backup_power_coverage(previous)
        )
        new_pressure, new_power, *_ = dependency_pressure(
            node.id, after, backup_power_coverage(node)
        )
        if (
            previous == node
            and abs(old_pressure - new_pressure) < 1e-12
            and abs(old_power - new_power) < 1e-12
        ):
            continue
        effects.append(
            InterventionNodeEffect(
                node_id=node.id,
                before=previous.model_copy(deep=True),
                after=node.model_copy(deep=True),
                dependency_pressure_before=old_pressure,
                dependency_pressure_after=new_pressure,
                power_pressure_before=old_power,
                power_pressure_after=new_power,
                backup_duration_minutes_before=_backup_minutes(previous),
                backup_duration_minutes_after=_backup_minutes(node),
                exposed_population_before=_exposed_population(previous),
                exposed_population_after=_exposed_population(node),
                power_restored=(
                    old_power > 0
                    and new_power < 1e-12
                    or node.type is InfrastructureType.SUBSTATION
                    and previous.status is not NodeStatus.OPERATIONAL
                    and node.status is NodeStatus.OPERATIONAL
                ),
                route_reopened=(
                    node.type is InfrastructureType.EMERGENCY_ROUTE
                    and previous.status is not NodeStatus.OPERATIONAL
                    and node.status is NodeStatus.OPERATIONAL
                ),
            )
        )
    return effects
