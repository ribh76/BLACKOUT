"""Persisted inputs and complete output for a no-intervention replay."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

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
