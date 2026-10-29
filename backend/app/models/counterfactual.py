"""Persisted inputs and complete output for a no-intervention replay."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models.optimization import OptimizationPlan
from app.models.scenario import CityState, Scenario
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
    input_sha256: str
    output_sha256: str
    record_sha256: str = ""
