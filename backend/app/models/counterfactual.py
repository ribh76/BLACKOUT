"""Persisted inputs and complete output for a no-intervention replay."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.optimization import OptimizationPlan
from app.models.scenario import CityState, ResourceInventory, Scenario
from app.models.simulation import SimulationResult


class BaselineRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    run_id: str
    recorded_at: datetime
    mode: Literal["NO_INTERVENTION"] = "NO_INTERVENTION"
    scenario: Scenario
    pristine_state: CityState
    initial_state: CityState
    result: SimulationResult
    engine_fingerprint: str
    input_sha256: str
    output_sha256: str


class ComparisonRequest(BaseModel):
    """Reuse saved artifacts by ID, or generate either one from the scenario."""

    model_config = ConfigDict(extra="forbid", strict=True)

    baseline_run_id: str | None = None
    optimization_run_id: str | None = None
    method: Literal["auto", "heuristic", "ortools"] = "auto"


class RunOutcomeMetrics(BaseModel):
    """Comparable end-state and full-timeline measures for one simulation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    critical_failures: int = Field(ge=0)
    people_affected: int = Field(ge=0)
    hospital_downtime_minutes: int = Field(ge=0)
    system_risk: float = Field(ge=0, allow_inf_nan=False)
    recovery_time_minutes: int | None = Field(default=None, ge=0)
    recovered_by_horizon: bool
    remaining_impaired_nodes: int = Field(ge=0)
    resource_utilization: ResourceInventory


class ComparisonImprovement(BaseModel):
    """Baseline minus response for harm; positive values are improvements."""

    model_config = ConfigDict(extra="forbid", strict=True)

    critical_failures: int
    people_affected: int
    hospital_downtime_minutes: int
    system_risk: float = Field(allow_inf_nan=False)
    recovery_time_minutes: int | None = None
    remaining_impaired_nodes: int
    additional_resources_used: ResourceInventory


class ComparisonSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    baseline: RunOutcomeMetrics
    response: RunOutcomeMetrics
    improvement: ComparisonImprovement
    assumptions: list[str]


class ComparisonRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    comparison_id: str
    recorded_at: datetime
    scenario_id: str
    scenario_schema_version: int
    city_schema_version: int
    scenario_fingerprint: str
    baseline_engine_fingerprint: str
    response_engine_fingerprint: str
    baseline_run_id: str
    optimization_run_id: str | None
    plan_source: Literal["generated", "stored"]
    initial_snapshot_sha256: str
    snapshot_equivalent: Literal[True] = True
    baseline: BaselineRunRecord
    response_initial_state: CityState
    plan: OptimizationPlan
    response_result: SimulationResult
    summary: ComparisonSummary | None = None
    input_sha256: str
    output_sha256: str
    record_sha256: str = ""
