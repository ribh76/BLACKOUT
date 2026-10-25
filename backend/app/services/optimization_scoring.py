"""Score actual single-action counterfactuals at the requested horizon."""

from math import fsum

from app.models.infrastructure import InfrastructureType, NodeStatus
from app.models.optimization import (
    CandidateAssessment,
    CandidateAssessments,
    OptimizationBenefit,
    OptimizationInput,
    OptimizationOutcome,
)
from app.models.scenario import CityState
from app.models.simulation import SimulationEventKind, SimulationResult
from app.services.dependency_queries import CRITICAL_FACILITY_TYPES
from app.services.interventions import validate_intervention_plan
from app.services.risk import rank_risk
from app.services.simulation import run_simulation

OBJECTIVE_SCALE = 1_000_000


def horizon_outcome(result: SimulationResult, horizon: int) -> OptimizationOutcome:
    state = next(t.city_state for t in result.states if t.elapsed_minutes == horizon)
    return OptimizationOutcome(
        system_risk=round(fsum(n.risk_score for n in rank_risk(state).nodes), 6),
        affected_population=sum(
            n.population_served
            for n in state.nodes
            if n.type is InfrastructureType.NEIGHBORHOOD
            and n.status is not NodeStatus.OPERATIONAL
        ),
        critical_facilities_at_risk=sum(
            n.type in CRITICAL_FACILITY_TYPES
            and n.status in {NodeStatus.CRITICAL, NodeStatus.FAILED}
            for n in state.nodes
        ),
    )


def estimate_benefit(
    inputs: OptimizationInput,
    baseline: OptimizationOutcome,
    projected: OptimizationOutcome,
) -> OptimizationBenefit:
    risk = round(baseline.system_risk - projected.system_risk, 6)
    population = baseline.affected_population - projected.affected_population
    facilities = (
        baseline.critical_facilities_at_risk - projected.critical_facilities_at_risk
    )
    state = inputs.current_city_state
    # Fixed denominators prevent a different normalization for each alternative.
    denominators = (
        max(1, 100 * len(state.nodes)),
        max(
            1,
            sum(
                n.population_served
                for n in state.nodes
                if n.type is InfrastructureType.NEIGHBORHOOD
            ),
        ),
        max(1, sum(n.type in CRITICAL_FACILITY_TYPES for n in state.nodes)),
    )
    weights = inputs.objective_weights
    values = (
        weights.risk_reduction,
        weights.population_protection,
        weights.critical_facility_protection,
    )
    largest = max(values)
    scaled = [value / largest for value in values]
    total = fsum(scaled)
    score = fsum(
        (weight / total) * (benefit / denominator)
        for weight, benefit, denominator in zip(
            scaled, (risk, population, facilities), denominators
        )
    )
    return OptimizationBenefit(
        expected_risk_reduction=risk,
        population_benefit=population,
        critical_facility_benefit=facilities,
        objective_score=score,
        objective_units=round(score * OBJECTIVE_SCALE),
    )


def failed_action_ids(result: SimulationResult, horizon: int) -> set[str]:
    return {
        event.intervention_id
        for event in result.events
        if event.kind is SimulationEventKind.INTERVENTION_FAILED
        and event.elapsed_minutes <= horizon
        and event.intervention_id is not None
    }


def assess_candidates(inputs: OptimizationInput) -> CandidateAssessments:
    # Revalidate mutable Pydantic instances before using them at the service seam.
    inputs = OptimizationInput.model_validate(inputs.model_dump())
    state: CityState = inputs.current_city_state
    horizon = inputs.planning_horizon_minutes
    baseline = horizon_outcome(run_simulation(state), horizon)
    candidates = []
    for action in sorted(inputs.candidate_interventions, key=lambda item: item.id):
        # Validate each alternative alone, never their aggregate resource costs.
        validate_intervention_plan(state, [action])
        result = run_simulation(state, [action])
        projected = horizon_outcome(result, horizon)
        candidates.append(
            CandidateAssessment(
                **estimate_benefit(inputs, baseline, projected).model_dump(),
                intervention=action.model_copy(deep=True),
                resource_cost=action.resource_costs.model_copy(deep=True),
                time_to_effect_minutes=int(
                    (action.start_time - state.simulation_time).total_seconds() / 60
                )
                + action.execution_delay_minutes
                + action.duration_minutes,
                projected_outcome=projected,
                completes_successfully=action.id
                not in failed_action_ids(result, horizon),
            )
        )
    return CandidateAssessments(
        optimization_input=inputs,
        baseline_outcome=baseline,
        candidates=candidates,
    )
