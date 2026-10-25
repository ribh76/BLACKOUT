"""Deterministic greedy and CP-SAT allocation over the same scored alternatives."""

from typing import Literal

from app.models.optimization import (
    CandidateAssessment,
    CandidateAssessments,
    CandidateSelection,
    OptimizationInput,
    OptimizationPlan,
    RejectedCandidate,
)
from app.models.scenario import ResourceInventory
from app.services.interventions import validate_intervention_plan
from app.services.optimization_scoring import (
    assess_candidates,
    estimate_benefit,
    failed_action_ids,
    horizon_outcome,
)
from app.services.simulation import run_simulation


def _priority(candidate: CandidateAssessment) -> tuple[int, int, str]:
    return (
        -candidate.objective_units,
        candidate.time_to_effect_minutes,
        candidate.intervention.id,
    )


def _eligible(candidate: CandidateAssessment) -> bool:
    return candidate.completes_successfully and candidate.objective_units > 0


def _heuristic(assessment: CandidateAssessments) -> list[str]:
    remaining = assessment.optimization_input.resource_inventory.model_dump()
    selected = []
    targets = set()
    for candidate in sorted(assessment.candidates, key=_priority):
        action = candidate.intervention
        costs = action.resource_costs.model_dump()
        if not _eligible(candidate) or action.target_node_id in targets:
            continue
        if any(cost > remaining[resource] for resource, cost in costs.items()):
            continue
        selected.append(action.id)
        targets.add(action.target_node_id)
        for resource, cost in costs.items():
            remaining[resource] -= cost
    return selected


def _load_cp_model():
    # Keep the baseline usable when the optional native solver cannot be imported.
    from ortools.sat.python import cp_model

    return cp_model


def select_candidates(
    assessment: CandidateAssessments,
    *,
    method: Literal["auto", "heuristic", "ortools"] = "auto",
) -> CandidateSelection:
    """Select binary alternatives with conservative, whole-plan resource use."""

    if method not in {"auto", "heuristic", "ortools"}:
        raise ValueError(f"Unknown optimization method {method!r}")
    if method == "heuristic":
        return CandidateSelection(
            selected_ids=_heuristic(assessment),
            method_used="heuristic",
            solver_status="HEURISTIC",
        )
    try:
        cp_model = _load_cp_model()
    except (ImportError, OSError) as exc:
        return CandidateSelection(
            selected_ids=_heuristic(assessment),
            method_used="heuristic",
            solver_status="UNAVAILABLE",
            fallback_reason=f"OR-Tools unavailable: {exc}",
        )
    model = cp_model.CpModel()
    candidates = sorted(assessment.candidates, key=lambda c: c.intervention.id)
    variables = [model.new_bool_var(c.intervention.id) for c in candidates]
    for (
        resource,
        available,
    ) in assessment.optimization_input.resource_inventory.model_dump().items():
        model.add(
            sum(
                getattr(c.intervention.resource_costs, resource) * variable
                for c, variable in zip(candidates, variables)
            )
            <= available
        )
    targets = {}
    for candidate, variable in zip(candidates, variables):
        targets.setdefault(candidate.intervention.target_node_id, []).append(variable)
        if not _eligible(candidate):
            model.add(variable == 0)
    for group in targets.values():
        model.add(sum(group) <= 1)
    primary = sum(c.objective_units * v for c, v in zip(candidates, variables))
    model.maximize(primary)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 0
    solver.parameters.max_deterministic_time = 5.0
    status = solver.solve(model)
    if status == cp_model.MODEL_INVALID:
        raise ValueError(f"Invalid allocation model: {model.validate()}")
    if status not in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
        return CandidateSelection(
            selected_ids=_heuristic(assessment),
            method_used="heuristic",
            solver_status=solver.status_name(status),
            fallback_reason=(
                "OR-Tools returned no feasible selection within its search budget."
            ),
        )
    selected = [
        c.intervention.id for c, v in zip(candidates, variables) if solver.value(v)
    ]
    primary_status = solver.status_name(status)
    if status == cp_model.OPTIMAL and candidates:
        # Fix the optimum before applying a bounded, deterministic tie preference.
        optimum = sum(
            c.objective_units for c in candidates if c.intervention.id in selected
        )
        model.add(primary == optimum)
        ordered = sorted(candidates, key=_priority)
        preferences = {
            c.intervention.id: len(ordered) - i for i, c in enumerate(ordered)
        }
        model.maximize(
            sum(
                preferences[c.intervention.id] * v
                for c, v in zip(candidates, variables)
            )
        )
        tie_status = solver.solve(model)
        if tie_status in {cp_model.OPTIMAL, cp_model.FEASIBLE}:
            selected = [
                c.intervention.id
                for c, v in zip(candidates, variables)
                if solver.value(v)
            ]
    return CandidateSelection(
        selected_ids=selected, method_used="ortools", solver_status=primary_status
    )


def plan_response(
    inputs: OptimizationInput,
    *,
    method: Literal["auto", "heuristic", "ortools"] = "auto",
) -> OptimizationPlan:
    assessment = assess_candidates(inputs)
    selection = select_candidates(assessment, method=method)
    selected_ids = set(selection.selected_ids)
    candidates = sorted(assessment.candidates, key=_priority)
    state = assessment.optimization_input.current_city_state
    horizon = assessment.optimization_input.planning_horizon_minutes
    removed = {}
    # Combined actions can invalidate each other's completion prerequisites.
    while True:
        selected = [c for c in candidates if c.intervention.id in selected_ids]
        plan = [c.intervention for c in selected]
        validate_intervention_plan(state, plan)
        simulation = run_simulation(state, plan)
        failed = failed_action_ids(simulation, horizon)
        if not failed:
            break
        for candidate_id in failed:
            removed[candidate_id] = "Fails during combined-plan simulation."
        selected_ids -= failed
    outcome = horizon_outcome(simulation, horizon)
    benefit = estimate_benefit(inputs, assessment.baseline_outcome, outcome)
    if selected and benefit.objective_units <= 0:
        for candidate_id in selected_ids:
            removed[candidate_id] = (
                "Combined plan provides no positive weighted benefit."
            )
        selected_ids = set()
        selected = []
        outcome = assessment.baseline_outcome.model_copy(deep=True)
        benefit = estimate_benefit(inputs, assessment.baseline_outcome, outcome)
    inventory = assessment.optimization_input.resource_inventory.model_dump()
    used = {
        resource: sum(
            getattr(c.intervention.resource_costs, resource) for c in selected
        )
        for resource in inventory
    }
    rejected = []
    selected_targets = {c.intervention.target_node_id for c in selected}
    for candidate in candidates:
        candidate_id = candidate.intervention.id
        if candidate_id in selected_ids:
            continue
        if candidate_id in removed:
            reason = removed[candidate_id]
        elif not candidate.completes_successfully:
            reason = "Fails during single-action simulation."
        elif candidate.objective_units <= 0:
            reason = "No positive weighted benefit at objective precision."
        elif candidate.intervention.target_node_id in selected_targets:
            reason = "Another action was selected for this target."
        elif any(
            used[r] + cost > inventory[r]
            for r, cost in candidate.intervention.resource_costs.model_dump().items()
        ):
            reason = "Insufficient remaining resources."
        else:
            reason = "Not selected by the allocation objective."
        rejected.append(RejectedCandidate(candidate_id=candidate_id, reason=reason))
    return OptimizationPlan(
        assessment=assessment,
        method_requested=method,
        method_used=selection.method_used,
        solver_status=selection.solver_status,
        fallback_reason=selection.fallback_reason,
        selected_candidates=selected,
        rejected_candidates=rejected,
        resource_utilization=ResourceInventory(**used),
        remaining_resources=ResourceInventory(
            **{r: inventory[r] - used[r] for r in inventory}
        ),
        additive_objective_units=sum(c.objective_units for c in selected),
        selection_adjusted_after_replay=bool(removed),
        projected_outcome=outcome,
        plan_benefit=benefit,
        assumptions=[
            "Benefits compare horizon-end outcomes with the no-action baseline.",
            "Single-action benefits are additive selection estimates; "
            "combined-plan benefit is replayed separately.",
            "Resources are reserved for the whole plan; one action per target.",
            "Objective uses normalized benefit rounded to one million integer units.",
            "OR-Tools optimality refers to the additive model before combined-plan "
            "validation; removed actions are not replaced.",
            "Risk and outcomes use synthetic data and existing snapshot rules.",
        ],
    )
