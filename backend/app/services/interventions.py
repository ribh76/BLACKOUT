"""Initial manual-response action catalog and proposal validation."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.models.dependency import DependencyType
from app.models.infrastructure import InfrastructureType, NodeStatus
from app.models.intervention import Intervention, InterventionType
from app.models.scenario import CityState, ResourceInventory


class InterventionError(ValueError):
    """A proposed intervention cannot be used with this city snapshot."""


@dataclass(frozen=True)
class InterventionDefinition:
    target_types: frozenset[InfrastructureType]
    duration_minutes: int
    resource_costs: ResourceInventory
    prerequisites: tuple[str, ...]
    expected_effects: tuple[str, ...]


INTERVENTION_DEFINITIONS: dict[InterventionType, InterventionDefinition] = {
    InterventionType.DEPLOY_GENERATOR: InterventionDefinition(
        frozenset(
            {
                InfrastructureType.HOSPITAL,
                InfrastructureType.PHARMACY,
                InfrastructureType.SHELTER,
                InfrastructureType.COOLING_CENTER,
            }
        ),
        30,
        ResourceInventory(
            mobile_generators=1,
            fuel_gallons=120,
            electrical_crews=1,
            traffic_crews=0,
            emergency_vehicles=1,
            response_personnel=2,
        ),
        ("Target has a power dependency and space for temporary generation.",),
        ("Temporary power reduces power-dependency pressure while fuel lasts.",),
    ),
    InterventionType.SEND_FUEL: InterventionDefinition(
        frozenset(
            {
                InfrastructureType.HOSPITAL,
                InfrastructureType.PHARMACY,
                InfrastructureType.SHELTER,
                InfrastructureType.COOLING_CENTER,
            }
        ),
        30,
        ResourceInventory(
            mobile_generators=0,
            fuel_gallons=100,
            electrical_crews=0,
            traffic_crews=0,
            emergency_vehicles=1,
            response_personnel=1,
        ),
        ("Target has backup generation or a deployed mobile generator.",),
        ("Backup power duration increases after fuel delivery.",),
    ),
    InterventionType.REPAIR_SUBSTATION: InterventionDefinition(
        frozenset({InfrastructureType.SUBSTATION}),
        60,
        ResourceInventory(
            mobile_generators=0,
            fuel_gallons=0,
            electrical_crews=1,
            traffic_crews=0,
            emergency_vehicles=1,
            response_personnel=2,
        ),
        ("Substation is degraded, critical, or failed.",),
        ("Restored substation power reduces downstream dependency pressure.",),
    ),
    InterventionType.RESTORE_INTERSECTION: InterventionDefinition(
        frozenset({InfrastructureType.INTERSECTION}),
        30,
        ResourceInventory(
            mobile_generators=0,
            fuel_gallons=0,
            electrical_crews=0,
            traffic_crews=1,
            emergency_vehicles=1,
            response_personnel=2,
        ),
        ("Intersection is degraded, critical, or failed.",),
        ("Signals and access through the intersection are restored.",),
    ),
    InterventionType.RELOCATE_POPULATION: InterventionDefinition(
        frozenset({InfrastructureType.NEIGHBORHOOD}),
        60,
        ResourceInventory(
            mobile_generators=0,
            fuel_gallons=0,
            electrical_crews=0,
            traffic_crews=0,
            emergency_vehicles=2,
            response_personnel=4,
        ),
        ("Neighborhood is affected and an accessible receiving site is available.",),
        ("Residents are moved out of the exposed neighborhood.",),
    ),
}


def propose_intervention(
    state: CityState,
    intervention_id: str,
    action_type: InterventionType,
    target_node_id: str,
    start_time: datetime,
) -> Intervention:
    """Describe one eligible, affordable action without changing the snapshot."""

    definition = INTERVENTION_DEFINITIONS[action_type]
    target = next((node for node in state.nodes if node.id == target_node_id), None)
    if target is None:
        raise InterventionError(f"Unknown target node {target_node_id!r}")
    if target.type not in definition.target_types:
        raise InterventionError(
            f"{action_type.value} cannot target {target.type.value} nodes"
        )
    if start_time.tzinfo is None or start_time.utcoffset() is None:
        raise InterventionError("start_time must include a timezone")
    if start_time < state.simulation_time:
        raise InterventionError("start_time cannot precede the snapshot time")
    if start_time + timedelta(minutes=definition.duration_minutes) > (
        state.simulation_time + timedelta(minutes=state.duration_minutes)
    ):
        raise InterventionError(
            "intervention cannot finish within the scenario horizon"
        )
    if (
        action_type
        in {
            InterventionType.REPAIR_SUBSTATION,
            InterventionType.RESTORE_INTERSECTION,
            InterventionType.RELOCATE_POPULATION,
        }
        and target.status is NodeStatus.OPERATIONAL
    ):
        raise InterventionError(f"{target.name} is already operational")
    if action_type is InterventionType.SEND_FUEL and target.backup_capacity == 0:
        raise InterventionError(f"{target.name} has no backup capacity")
    if action_type is InterventionType.DEPLOY_GENERATOR and not any(
        edge.dependent_id == target_node_id
        and edge.dependency_type is DependencyType.POWER
        for edge in state.dependency_edges
    ):
        raise InterventionError(f"{target.name} has no power dependency")
    for resource, needed in definition.resource_costs.model_dump().items():
        available = getattr(state.resource_inventory, resource)
        if available < needed:
            raise InterventionError(
                f"Insufficient {resource}: need {needed}, available {available}"
            )
    return Intervention(
        id=intervention_id,
        type=action_type,
        target_node_id=target_node_id,
        start_time=start_time,
        duration_minutes=definition.duration_minutes,
        prerequisites=list(definition.prerequisites),
        resource_costs=definition.resource_costs.model_copy(deep=True),
        expected_effects=list(definition.expected_effects),
    )
