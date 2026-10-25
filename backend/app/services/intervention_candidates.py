"""Find feasible manual actions and forecast their immediate completion effects."""

from datetime import datetime, timedelta

from app.models.dependency import DependencyType
from app.models.infrastructure import InfrastructureType
from app.models.intervention import (
    ExecutionStatus,
    InterventionCandidate,
    InterventionEffectEstimate,
    NodeInterventionCandidates,
    UnavailableIntervention,
)
from app.models.scenario import CityState
from app.models.simulation import SimulationEventKind
from app.services.interventions import (
    INTERVENTION_DEFINITIONS,
    SIMULATION_HORIZON_MINUTES,
    InterventionError,
    execute_intervention,
    propose_intervention,
)
from app.services.simulation import run_simulation
from app.services.simulation_pressure import TICK_MINUTES


def candidate_interventions(
    snapshot: CityState, node_id: str, start_time: datetime | None = None
) -> NodeInterventionCandidates:
    """Return independently affordable actions at their earliest feasible start.

    Estimates advance the unchanged baseline to completion and apply one action
    there. They are conditional forecasts, not effects applied at request time.
    """

    nodes = {node.id: node for node in snapshot.nodes}
    if node_id not in nodes:
        raise InterventionError(f"Unknown target node {node_id!r}")
    if start_time is not None:
        if start_time.tzinfo is None or start_time.utcoffset() is None:
            raise InterventionError("start_time must include a timezone")
        offset = (start_time - snapshot.simulation_time).total_seconds() / 60
        if offset < 0 or offset > min(
            snapshot.duration_minutes, SIMULATION_HORIZON_MINUTES
        ):
            raise InterventionError("start_time must be within the simulation horizon")
        if offset % TICK_MINUTES:
            raise InterventionError("start_time must align with a 30-minute tick")
        starts = [start_time]
    else:
        starts = [
            snapshot.simulation_time + timedelta(minutes=minute)
            for minute in range(0, SIMULATION_HORIZON_MINUTES + 1, TICK_MINUTES)
        ]

    target_ids = {node_id}
    if nodes[node_id].type is InfrastructureType.EMERGENCY_ROUTE:
        target_ids.update(
            edge.provider_id
            for edge in snapshot.dependency_edges
            if edge.dependent_id == node_id
            and edge.dependency_type is DependencyType.ACCESS
            and nodes[edge.provider_id].type is InfrastructureType.INTERSECTION
        )
    baseline = run_simulation(snapshot)
    states = {state.city_state.simulation_time: state for state in baseline.states}
    candidates = []
    unavailable = []
    for target_id in sorted(target_ids):
        for action_type, definition in INTERVENTION_DEFINITIONS.items():
            if nodes[target_id].type not in definition.target_types:
                continue
            reasons = []
            for start in starts:
                offset_minutes = int(
                    (start - snapshot.simulation_time).total_seconds() / 60
                )
                try:
                    action = propose_intervention(
                        snapshot,
                        f"candidate:{target_id}:{action_type}:{offset_minutes}",
                        action_type,
                        target_id,
                        start,
                    )
                except InterventionError as exc:
                    reasons.append(str(exc))
                    continue
                completion_time = start + timedelta(
                    minutes=action.execution_delay_minutes + action.duration_minutes
                )
                projected = states[completion_time].model_copy(deep=True)
                event = execute_intervention(projected, action.model_copy(deep=True))
                if event.kind is SimulationEventKind.INTERVENTION_FAILED:
                    reasons.append(event.explanation)
                    continue
                candidates.append(
                    InterventionCandidate(
                        intervention=action,
                        estimated_immediate_effects=InterventionEffectEstimate(
                            completion_time=completion_time,
                            execution_status=ExecutionStatus.COMPLETED,
                            explanation=event.explanation,
                            node_effects=event.node_effects,
                            population_relocated=event.population_relocated,
                            receiving_node_id=event.receiving_node_id,
                            assumptions=[
                                "Forecast applies this action alone after the baseline "
                                "cascade at completion.",
                                "Pressure changes affect the following cascade tick.",
                                "Candidates are alternatives; validate combined costs.",
                            ],
                        ),
                    )
                )
                break
            else:
                unavailable.append(
                    UnavailableIntervention(
                        type=action_type, target_node_id=target_id, reason=reasons[0]
                    )
                )
    return NodeInterventionCandidates(
        scenario_id=snapshot.scenario_id,
        node_id=node_id,
        simulation_time=snapshot.simulation_time,
        candidates=candidates,
        unavailable_actions=unavailable,
    )
