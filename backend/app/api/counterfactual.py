"""Capture and retrieve the complete no-intervention counterfactual baseline."""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.scenarios import require_scenario, scenario_store
from app.models.counterfactual import (
    BaselineRunRecord,
    ComparisonRequest,
    ComparisonRunRecord,
)
from app.services.counterfactual import BaselineRunStore
from app.services.interventions import InterventionError
from app.services.optimization import build_optimization_input
from app.services.optimization_history import OptimizationRunStore
from app.services.optimization_planner import plan_response
from app.services.scenarios import ScenarioStore

router = APIRouter(prefix="/scenarios", tags=["counterfactual"])


def baseline_store(request: Request) -> BaselineRunStore:
    return request.app.state.baseline_runs


def optimization_store(request: Request) -> OptimizationRunStore:
    return request.app.state.optimization_runs


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


@router.post(
    "/{scenario_id}/counterfactual/comparisons", response_model=ComparisonRunRecord
)
def create_comparison(
    scenario_id: str,
    options: ComparisonRequest,
    store: Annotated[ScenarioStore, Depends(scenario_store)],
    history: Annotated[BaselineRunStore, Depends(baseline_store)],
    plans: Annotated[OptimizationRunStore, Depends(optimization_store)],
) -> ComparisonRunRecord:
    require_scenario(store, scenario_id)
    try:
        baseline = (
            history.get(scenario_id, options.baseline_run_id)
            if options.baseline_run_id
            else history.save_baseline(store)
        )
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise HTTPException(
            status_code=503, detail="Unable to load baseline run"
        ) from exc
    if baseline is None:
        raise HTTPException(status_code=404, detail="Baseline run not found")
    if baseline.engine_fingerprint != history.engine_fingerprint:
        raise HTTPException(
            status_code=409,
            detail="Baseline engine version differs from running engine",
        )
    try:
        response_initial = history.verified_response_initial_state(baseline)
        if options.optimization_run_id:
            try:
                saved_plan = plans.get(scenario_id, options.optimization_run_id)
            except ValueError as exc:
                raise HTTPException(
                    status_code=503, detail="Unable to read optimization run"
                ) from exc
            if saved_plan is None:
                raise HTTPException(
                    status_code=404, detail="Optimization run not found"
                )
            plan = saved_plan.plan
        else:
            inputs = build_optimization_input(response_initial)
            plan = plan_response(inputs, method=options.method)
        return history.save_comparison(
            baseline,
            plan,
            optimization_run_id=options.optimization_run_id,
        )
    except (InterventionError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(
            status_code=503, detail="Unable to record comparison run"
        ) from exc


@router.get(
    "/{scenario_id}/counterfactual/comparisons/{comparison_id}",
    response_model=ComparisonRunRecord,
)
def get_comparison(
    scenario_id: str,
    comparison_id: str,
    store: Annotated[ScenarioStore, Depends(scenario_store)],
    history: Annotated[BaselineRunStore, Depends(baseline_store)],
) -> ComparisonRunRecord:
    require_scenario(store, scenario_id)
    try:
        record = history.get_comparison(scenario_id, comparison_id)
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise HTTPException(
            status_code=503, detail="Unable to read comparison run"
        ) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Comparison run not found")
    return record
