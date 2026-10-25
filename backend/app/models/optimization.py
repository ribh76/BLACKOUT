"""Reproducible inputs for resource allocation; no selection is implied."""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.intervention import ExecutionStatus, Intervention
from app.models.scenario import CityState, ResourceInventory


class ObjectiveWeights(BaseModel):
    """Relative weights, kept as supplied; at least one objective is active."""

    model_config = ConfigDict(extra="forbid", strict=True)

    risk_reduction: float = Field(default=0.5, ge=0, allow_inf_nan=False)
    population_protection: float = Field(default=0.3, ge=0, allow_inf_nan=False)
    critical_facility_protection: float = Field(default=0.2, ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def require_active_objective(self) -> "ObjectiveWeights":
        if not any(self.model_dump().values()):
            raise ValueError("at least one objective weight must be positive")
        return self


class OptimizationInputRequest(BaseModel):
    """Omit the snapshot to use the stored current state, or pass playback state."""

    model_config = ConfigDict(extra="forbid", strict=True)

    current_city_state: CityState | None = None
    planning_horizon_minutes: int = Field(default=120, ge=30, le=120, multiple_of=30)
    objective_weights: ObjectiveWeights = Field(default_factory=ObjectiveWeights)
    high_risk_threshold: float = Field(default=50.0, ge=0, le=100, allow_inf_nan=False)


class OptimizationInput(BaseModel):
    """Candidates are independently feasible alternatives, not a combined plan.

    Horizon minutes are relative to current_city_state.simulation_time. The
    inventory is the unconsumed inventory of that exact snapshot.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    current_city_state: CityState
    candidate_interventions: list[Intervention]
    resource_inventory: ResourceInventory
    planning_horizon_minutes: int = Field(ge=30, le=120, multiple_of=30)
    objective_weights: ObjectiveWeights
    high_risk_threshold: float = Field(ge=0, le=100, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_context(self) -> "OptimizationInput":
        state = self.current_city_state
        if self.resource_inventory != state.resource_inventory:
            raise ValueError("resource inventory must match the current city state")
        if self.planning_horizon_minutes > state.duration_minutes:
            raise ValueError("planning horizon exceeds the scenario duration")
        node_ids = {node.id for node in state.nodes}
        if len(node_ids) != len(state.nodes):
            raise ValueError("current city state contains duplicate node IDs")
        if any(
            edge.provider_id not in node_ids or edge.dependent_id not in node_ids
            for edge in state.dependency_edges
        ):
            raise ValueError("current city dependency references an unknown node")
        if any(event.node_id not in node_ids for event in state.event_history):
            raise ValueError("current city event references an unknown node")
        ids = set()
        targets = set()
        deadline = state.simulation_time + timedelta(
            minutes=self.planning_horizon_minutes
        )
        for action in self.candidate_interventions:
            pair = (action.type, action.target_node_id)
            if action.id in ids or pair in targets:
                raise ValueError("candidate interventions must be unique")
            ids.add(action.id)
            targets.add(pair)
            if action.target_node_id not in node_ids:
                raise ValueError(
                    "candidate target does not exist in current city state"
                )
            if action.execution_status is not ExecutionStatus.PLANNED:
                raise ValueError("candidate interventions must be planned")
            offset = (action.start_time - state.simulation_time).total_seconds() / 60
            completion = action.start_time + timedelta(
                minutes=action.execution_delay_minutes + action.duration_minutes
            )
            if offset < 0 or offset % 30 or completion > deadline:
                raise ValueError(
                    "candidate timing must fit the planning horizon and ticks"
                )
            if any(
                cost > getattr(self.resource_inventory, resource)
                for resource, cost in action.resource_costs.model_dump().items()
            ):
                raise ValueError("each candidate must be independently affordable")
        return self


class OptimizationPlanRequest(OptimizationInputRequest):
    method: Literal["auto", "heuristic", "ortools"] = "auto"


class OptimizationOutcome(BaseModel):
    """Horizon-end metrics; system risk is the sum of existing 0–100 node scores."""

    model_config = ConfigDict(extra="forbid", strict=True)

    system_risk: float = Field(ge=0, allow_inf_nan=False)
    affected_population: int = Field(ge=0)
    critical_facilities_at_risk: int = Field(ge=0)


class OptimizationBenefit(BaseModel):
    """Signed baseline-minus-intervention differences; negative means harm."""

    model_config = ConfigDict(extra="forbid", strict=True)

    expected_risk_reduction: float = Field(allow_inf_nan=False)
    population_benefit: int
    critical_facility_benefit: int
    objective_score: float = Field(allow_inf_nan=False)
    objective_units: int


class CandidateAssessment(OptimizationBenefit):
    intervention: Intervention
    resource_cost: ResourceInventory
    time_to_effect_minutes: int = Field(ge=0)
    projected_outcome: OptimizationOutcome
    completes_successfully: bool


class CandidateAssessments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    optimization_input: OptimizationInput
    baseline_outcome: OptimizationOutcome
    candidates: list[CandidateAssessment]


class RejectedCandidate(BaseModel):
    candidate_id: str
    reason: str


class RankedAction(CandidateAssessment):
    rank: int = Field(ge=1)
    priority_rank: int = Field(ge=1)


class OptimizationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    assessment: CandidateAssessments
    method_requested: Literal["auto", "heuristic", "ortools"]
    method_used: Literal["heuristic", "ortools"]
    solver_status: str
    fallback_reason: str | None = None
    run_id: str | None = None
    recorded_at: datetime | None = Field(default=None, strict=False)
    selected_candidates: list[RankedAction]
    rejected_candidates: list[RejectedCandidate]
    resource_utilization: ResourceInventory
    remaining_resources: ResourceInventory
    additive_objective_units: int
    selection_adjusted_after_replay: bool
    projected_outcome: OptimizationOutcome
    plan_benefit: OptimizationBenefit
    assumptions: list[str]


class CandidateSelection(BaseModel):
    selected_ids: list[str]
    method_used: Literal["heuristic", "ortools"]
    solver_status: str
    fallback_reason: str | None = None


class OptimizationRunRecord(BaseModel):
    schema_version: Literal[1] = 1
    run_id: str
    recorded_at: datetime = Field(strict=False)
    replay_of: str | None = None
    engine_fingerprint: str
    runtime_versions: dict[str, str]
    input_sha256: str
    output_sha256: str
    plan: OptimizationPlan


class OptimizationRunSummary(BaseModel):
    run_id: str
    recorded_at: datetime = Field(strict=False)
    method_used: str
    selected_action_count: int


class OptimizationReplay(BaseModel):
    original_run_id: str
    matches_original: bool
    engine_matches_original: bool
    runtime_matches_original: bool
    plan: OptimizationPlan
