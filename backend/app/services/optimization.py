"""Prepare a bounded, state-driven candidate pool for a future allocator."""

from datetime import timedelta

from app.models.infrastructure import NodeStatus
from app.models.intervention import InterventionType
from app.models.optimization import (
    ObjectiveWeights,
    OptimizationInput,
    OptimizationInputRequest,
)
from app.models.scenario import CityState
from app.models.simulation import SimulationEventKind
from app.services.interventions import (
    INTERVENTION_DEFINITIONS,
    InterventionError,
    execute_intervention,
    propose_intervention,
)
from app.services.risk import rank_risk
from app.services.simulation import run_simulation


def build_optimization_input(
    snapshot: CityState,
    *,
    planning_horizon_minutes: int = 120,
    objective_weights: ObjectiveWeights | None = None,
    high_risk_threshold: float = 50.0,
) -> OptimizationInput:
    """Generate one immediate action per eligible type/target pair.

    Target current FAILED/CRITICAL nodes or nodes at/above the risk-score cutoff
    (0–100). Do not search future statuses for targets or future start times for
    eligibility. Catalog validation enforces type, prerequisites, costs, and
    timing. A shared baseline forecast rejects actions that fail at completion.
    The caller's state and inventory are never consumed or changed.
    """

    options = OptimizationInputRequest(
        planning_horizon_minutes=planning_horizon_minutes,
        objective_weights=objective_weights or ObjectiveWeights(),
        high_risk_threshold=high_risk_threshold,
    )
    result = OptimizationInput(
        current_city_state=snapshot.model_copy(deep=True),
        candidate_interventions=[],
        resource_inventory=snapshot.resource_inventory.model_copy(deep=True),
        planning_horizon_minutes=options.planning_horizon_minutes,
        objective_weights=options.objective_weights.model_copy(deep=True),
        high_risk_threshold=options.high_risk_threshold,
    )
    state = result.current_city_state
    risk = {row.node_id: row.risk_score for row in rank_risk(state).nodes}
    eligible = sorted(
        (
            node
            for node in state.nodes
            if node.status in {NodeStatus.FAILED, NodeStatus.CRITICAL}
            or risk[node.id] >= options.high_risk_threshold
        ),
        key=lambda node: node.id,
    )
    baseline = run_simulation(state)
    states = {tick.city_state.simulation_time: tick for tick in baseline.states}
    deadline = state.simulation_time + timedelta(
        minutes=options.planning_horizon_minutes
    )
    candidates = []
    for node in eligible:
        for action_type, definition in INTERVENTION_DEFINITIONS.items():
            if node.type not in definition.target_types:
                continue
            # Extra fuel cannot restore a facility that has already failed.
            if (
                action_type is InterventionType.SEND_FUEL
                and node.status is NodeStatus.FAILED
            ):
                continue
            try:
                action = propose_intervention(
                    state,
                    f"candidate:{node.id}:{action_type}:0",
                    action_type,
                    node.id,
                    state.simulation_time,
                )
            except InterventionError:
                continue
            completion = action.start_time + timedelta(
                minutes=action.execution_delay_minutes + action.duration_minutes
            )
            if completion > deadline:
                continue
            projected = states[completion].model_copy(deep=True)
            if (
                action_type is InterventionType.SEND_FUEL
                and next(
                    n for n in projected.city_state.nodes if n.id == node.id
                ).status
                is NodeStatus.FAILED
            ):
                continue
            event = execute_intervention(projected, action.model_copy(deep=True))
            if event.kind is SimulationEventKind.INTERVENTION_FAILED:
                continue
            if event.node_effects or event.population_relocated:
                candidates.append(action)
    # Revalidate the assembled public contract as well as individual actions.
    return OptimizationInput.model_validate(
        {**result.model_dump(), "candidate_interventions": candidates}
    )
