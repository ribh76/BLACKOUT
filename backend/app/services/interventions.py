"""Initial manual-response action catalog and proposal validation."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.models.dependency import DependencyType
from app.models.infrastructure import InfrastructureType, NodeStatus
from app.models.intervention import ExecutionStatus, Intervention, InterventionType
from app.models.scenario import CityState, ResourceInventory, ScenarioEvent
from app.models.simulation import SimulationEvent, SimulationEventKind, SimulationState

SIMULATION_HORIZON_MINUTES = 120
RELOCATION_CAPACITY = 100


class InterventionError(ValueError):
    """A proposed intervention cannot be used with this city snapshot."""


@dataclass(frozen=True)
class InterventionDefinition:
    target_types: frozenset[InfrastructureType]
    execution_delay_minutes: int
    duration_minutes: int
    resource_costs: ResourceInventory
    prerequisites: tuple[str, ...]
    expected_effects: tuple[str, ...]
    failure_conditions: tuple[str, ...]


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
        0,
        30,
        ResourceInventory(
            mobile_generators=1,
            fuel_gallons=120,
            electrical_crews=1,
            traffic_crews=0,
            emergency_vehicles=1,
            response_personnel=2,
        ),
        ("Target has a power dependency and is not failed.",),
        ("Temporary power reduces power-dependency pressure while fuel lasts.",),
        ("The target fails before installation or its power dependency disappears.",),
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
        0,
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
        ("The target loses its backup system before delivery.",),
    ),
    InterventionType.REPAIR_SUBSTATION: InterventionDefinition(
        frozenset({InfrastructureType.SUBSTATION}),
        0,
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
        ("The substation is already operational when the crew arrives.",),
    ),
    InterventionType.RESTORE_INTERSECTION: InterventionDefinition(
        frozenset({InfrastructureType.INTERSECTION}),
        0,
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
        ("The intersection is already operational when the crew arrives.",),
    ),
    InterventionType.RELOCATE_POPULATION: InterventionDefinition(
        frozenset({InfrastructureType.NEIGHBORHOOD}),
        30,
        60,
        ResourceInventory(
            mobile_generators=0,
            fuel_gallons=0,
            electrical_crews=0,
            traffic_crews=0,
            emergency_vehicles=2,
            response_personnel=4,
        ),
        ("Neighborhood is affected or at risk; receiving site has 100 places.",),
        ("Up to 100 residents move to an available shelter or cooling center.",),
        ("No receiving site has 100 free places at completion.",),
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
    offset = (start_time - state.simulation_time).total_seconds() / 60
    if offset % 30:
        raise InterventionError("start_time must align with a 30-minute tick")
    completion = start_time + timedelta(
        minutes=definition.execution_delay_minutes + definition.duration_minutes
    )
    if completion > state.simulation_time + timedelta(
        minutes=min(state.duration_minutes, SIMULATION_HORIZON_MINUTES)
    ):
        raise InterventionError(
            "intervention cannot finish within the scenario horizon"
        )
    if target.status is NodeStatus.OPERATIONAL:
        if action_type is InterventionType.REPAIR_SUBSTATION:
            raise InterventionError(f"{target.name} is already operational")
        if action_type in {
            InterventionType.RESTORE_INTERSECTION,
            InterventionType.RELOCATE_POPULATION,
        } and not (
            _has_impaired_provider(state, target_node_id)
            and completion > state.simulation_time + timedelta(minutes=30)
        ):
            raise InterventionError(
                f"{target.name} is operational and has no eligible impending disruption"
            )
    if action_type is InterventionType.SEND_FUEL and target.backup_capacity == 0:
        raise InterventionError(f"{target.name} has no backup capacity")
    if (
        action_type
        in {
            InterventionType.DEPLOY_GENERATOR,
            InterventionType.SEND_FUEL,
        }
        and target.current_load == 0
    ):
        raise InterventionError(f"{target.name} has no active load to protect")
    if (
        action_type is InterventionType.DEPLOY_GENERATOR
        and target.status is NodeStatus.FAILED
    ):
        raise InterventionError(
            f"{target.name} is failed; a generator cannot restore it"
        )
    if action_type is InterventionType.DEPLOY_GENERATOR and not any(
        edge.dependent_id == target_node_id
        and edge.dependency_type is DependencyType.POWER
        for edge in state.dependency_edges
    ):
        raise InterventionError(f"{target.name} has no power dependency")
    if action_type is InterventionType.RELOCATE_POPULATION and not _receiving_sites(
        state
    ):
        raise InterventionError("No operational receiving site has 100 free places")
    if (
        action_type is InterventionType.RELOCATE_POPULATION
        and target.population_served == 0
    ):
        raise InterventionError(f"{target.name} has no residents to relocate")
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
        execution_delay_minutes=definition.execution_delay_minutes,
        duration_minutes=definition.duration_minutes,
        prerequisites=list(definition.prerequisites),
        resource_costs=definition.resource_costs.model_copy(deep=True),
        expected_effects=list(definition.expected_effects),
        failure_conditions=list(definition.failure_conditions),
    )


def _receiving_sites(state: CityState):
    return sorted(
        (
            node
            for node in state.nodes
            if node.type
            in {InfrastructureType.SHELTER, InfrastructureType.COOLING_CENTER}
            and node.status is NodeStatus.OPERATIONAL
            and node.capacity - node.current_load >= RELOCATION_CAPACITY
        ),
        key=lambda node: node.id,
    )


def _has_impaired_provider(state: CityState, target_node_id: str) -> bool:
    impaired = {
        node.id for node in state.nodes if node.status is not NodeStatus.OPERATIONAL
    }
    return any(
        edge.dependent_id == target_node_id and edge.provider_id in impaired
        for edge in state.dependency_edges
    )


def validate_intervention_plan(
    state: CityState, interventions: list[Intervention]
) -> list[Intervention]:
    """Validate an immutable action plan, including aggregate resource use."""

    remaining = state.resource_inventory.model_copy(deep=True)
    ids: set[str] = set()
    targets: set[tuple[InterventionType, str]] = set()
    validated = []
    for action in interventions:
        if action.id in ids:
            raise InterventionError(f"Duplicate intervention ID {action.id!r}")
        pair = (action.type, action.target_node_id)
        if pair in targets:
            raise InterventionError(
                f"Duplicate {action.type.value} action for {action.target_node_id!r}"
            )
        proposal_state = state.model_copy(deep=True)
        proposal_state.resource_inventory = remaining
        canonical = propose_intervention(
            proposal_state,
            action.id,
            action.type,
            action.target_node_id,
            action.start_time,
        )
        if action != canonical:
            raise InterventionError(
                f"Intervention {action.id!r} differs from the action definition"
            )
        for resource, cost in action.resource_costs.model_dump().items():
            setattr(remaining, resource, getattr(remaining, resource) - cost)
        ids.add(action.id)
        targets.add(pair)
        validated.append(action.model_copy(deep=True))
    return validated


def execute_intervention(
    state: SimulationState, action: Intervention
) -> SimulationEvent:
    """Apply a completed action to a simulator snapshot and record its outcome."""

    snapshot = state.city_state
    target = next(node for node in snapshot.nodes if node.id == action.target_node_id)
    old_status = target.status
    failure = None
    receiving = None
    moved = 0
    if action.type is InterventionType.DEPLOY_GENERATOR:
        if target.status is NodeStatus.FAILED:
            failure = "target failed before generator installation"
        elif not any(
            edge.dependent_id == target.id
            and edge.dependency_type is DependencyType.POWER
            for edge in snapshot.dependency_edges
        ):
            failure = "target no longer has a power dependency"
        else:
            reserve = target.current_load * 2
            target.backup_capacity += reserve
            target.backup_remaining += reserve
    elif action.type is InterventionType.SEND_FUEL:
        if target.backup_capacity == 0:
            failure = "target has no backup system"
        else:
            reserve = target.current_load
            target.backup_capacity += reserve
            target.backup_remaining += reserve
    elif action.type is InterventionType.REPAIR_SUBSTATION:
        if target.status is NodeStatus.OPERATIONAL:
            failure = "substation was already operational"
        else:
            target.status = NodeStatus.OPERATIONAL
            state.impaired_since_minutes.pop(target.id, None)
            state.healthy_minutes[target.id] = 0
    elif action.type is InterventionType.RESTORE_INTERSECTION:
        if target.status is NodeStatus.OPERATIONAL:
            failure = "intersection was already operational"
        else:
            target.status = NodeStatus.OPERATIONAL
            state.impaired_since_minutes.pop(target.id, None)
            state.signal_unpowered_minutes[target.id] = 0
            state.healthy_minutes[target.id] = 0
    else:
        sites = _receiving_sites(snapshot)
        if target.status is NodeStatus.OPERATIONAL:
            failure = "neighborhood is no longer affected"
        elif not sites:
            failure = "no operational receiving site has 100 free places"
        elif target.population_served == 0:
            failure = "no residents remain to relocate"
        else:
            receiving = sites[0]
            moved = min(RELOCATION_CAPACITY, target.population_served)
            target.population_served -= moved
            receiving.current_load += moved
    action.execution_status = (
        ExecutionStatus.FAILED if failure else ExecutionStatus.COMPLETED
    )
    if target.status is not old_status:
        snapshot.event_history.append(
            ScenarioEvent(
                sequence=len(snapshot.event_history),
                time=snapshot.simulation_time,
                node_id=target.id,
                status=target.status,
            )
        )
    return SimulationEvent(
        elapsed_minutes=state.elapsed_minutes,
        time=snapshot.simulation_time,
        kind=(
            SimulationEventKind.INTERVENTION_FAILED
            if failure
            else SimulationEventKind.INTERVENTION_COMPLETED
        ),
        node_id=target.id,
        old_status=old_status,
        new_status=target.status,
        cause=action.type.value,
        intervention_id=action.id,
        intervention_type=action.type,
        receiving_node_id=receiving.id if receiving else None,
        explanation=(
            f"{action.type.value} failed at {target.name}: {failure}."
            if failure
            else f"{action.type.value} completed at {target.name}"
            + (f"; moved {moved} residents to {receiving.name}." if receiving else ".")
        ),
        population_relocated=moved,
    )
