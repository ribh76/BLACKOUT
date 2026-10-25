"""Reproducible inputs for resource allocation; no selection is implied."""

from datetime import timedelta

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
