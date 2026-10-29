"""Capture and retrieve the complete no-intervention counterfactual baseline."""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.scenarios import require_scenario, scenario_store
from app.models.counterfactual import BaselineRunRecord
from app.services.counterfactual import BaselineRunStore
from app.services.scenarios import ScenarioStore

router = APIRouter(prefix="/scenarios", tags=["counterfactual"])


def baseline_store(request: Request) -> BaselineRunStore:
    return request.app.state.baseline_runs


@router.post("/{scenario_id}/counterfactual/baseline", response_model=BaselineRunRecord)
def create_baseline(
    scenario_id: str,
    store: Annotated[ScenarioStore, Depends(scenario_store)],
    history: Annotated[BaselineRunStore, Depends(baseline_store)],
) -> BaselineRunRecord:
    require_scenario(store, scenario_id)
    try:
        return history.save_baseline(store)
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(
            status_code=503, detail="Unable to record baseline run"
        ) from exc


@router.get(
    "/{scenario_id}/counterfactual/baseline/{run_id}",
    response_model=BaselineRunRecord,
)
def get_baseline(
    scenario_id: str,
    run_id: str,
    store: Annotated[ScenarioStore, Depends(scenario_store)],
    history: Annotated[BaselineRunStore, Depends(baseline_store)],
) -> BaselineRunRecord:
    require_scenario(store, scenario_id)
    try:
        record = history.get(scenario_id, run_id)
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise HTTPException(
            status_code=503, detail="Unable to read baseline run"
        ) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Baseline run not found")
    return record
