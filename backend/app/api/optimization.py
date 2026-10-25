"""Build optimization inputs without changing or applying a response plan."""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.scenarios import require_scenario, scenario_store
from app.models.optimization import (
    CandidateAssessments,
    OptimizationInput,
    OptimizationInputRequest,
    OptimizationPlan,
    OptimizationPlanRequest,
    OptimizationReplay,
    OptimizationRunRecord,
    OptimizationRunSummary,
)
from app.services.optimization import build_optimization_input
from app.services.optimization_history import (
    OptimizationRunStore,
    replay_payload,
)
from app.services.optimization_planner import plan_response
from app.services.optimization_scoring import assess_candidates
from app.services.scenarios import ScenarioStore

router = APIRouter(prefix="/scenarios", tags=["optimization"])


def optimization_run_store(request: Request) -> OptimizationRunStore:
    return request.app.state.optimization_runs


def _save_plan(
    history: OptimizationRunStore, plan: OptimizationPlan, replay_of: str | None = None
) -> OptimizationRunRecord:
    try:
        return history.save(plan, replay_of=replay_of)
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(
            status_code=503, detail="Unable to record optimization run"
        ) from exc


def _get_run(
    history: OptimizationRunStore, scenario_id: str, run_id: str
) -> OptimizationRunRecord:
    try:
        record = history.get(scenario_id, run_id)
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise HTTPException(
            status_code=503, detail="Unable to read optimization run"
        ) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Optimization run not found")
    return record


def _build_input(
    scenario_id: str,
    options: OptimizationInputRequest,
    store: ScenarioStore,
) -> OptimizationInput:
    require_scenario(store, scenario_id)
    state = options.current_city_state or store.get_scenario_state()
    if state.scenario_id != scenario_id:
        raise HTTPException(
            status_code=422, detail="Snapshot scenario does not match URL"
        )
    try:
        return build_optimization_input(
            state,
            planning_horizon_minutes=options.planning_horizon_minutes,
            objective_weights=options.objective_weights,
            high_risk_threshold=options.high_risk_threshold,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{scenario_id}/optimization/input", response_model=OptimizationInput)
def optimization_input(
    scenario_id: str,
    options: OptimizationInputRequest,
    store: Annotated[ScenarioStore, Depends(scenario_store)],
) -> OptimizationInput:
    return _build_input(scenario_id, options, store)


@router.post(
    "/{scenario_id}/optimization/candidates", response_model=CandidateAssessments
)
def optimization_candidates(
    scenario_id: str,
    options: OptimizationInputRequest,
    store: Annotated[ScenarioStore, Depends(scenario_store)],
) -> CandidateAssessments:
    inputs = _build_input(scenario_id, options, store)
    try:
        return assess_candidates(inputs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{scenario_id}/optimization/plan", response_model=OptimizationPlan)
def optimization_plan(
    scenario_id: str,
    options: OptimizationPlanRequest,
    store: Annotated[ScenarioStore, Depends(scenario_store)],
    history: Annotated[OptimizationRunStore, Depends(optimization_run_store)],
) -> OptimizationPlan:
    inputs = _build_input(scenario_id, options, store)
    try:
        plan = plan_response(inputs, method=options.method)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return _save_plan(history, plan).plan


@router.get(
    "/{scenario_id}/optimization/runs", response_model=list[OptimizationRunSummary]
)
def list_optimization_runs(
    scenario_id: str,
    store: Annotated[ScenarioStore, Depends(scenario_store)],
    history: Annotated[OptimizationRunStore, Depends(optimization_run_store)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> list[OptimizationRunSummary]:
    require_scenario(store, scenario_id)
    try:
        return history.list(scenario_id, limit)
    except (OSError, sqlite3.Error, ValueError) as exc:
        raise HTTPException(
            status_code=503, detail="Unable to list optimization runs"
        ) from exc


@router.get(
    "/{scenario_id}/optimization/runs/{run_id}", response_model=OptimizationRunRecord
)
def get_optimization_run(
    scenario_id: str,
    run_id: str,
    store: Annotated[ScenarioStore, Depends(scenario_store)],
    history: Annotated[OptimizationRunStore, Depends(optimization_run_store)],
) -> OptimizationRunRecord:
    require_scenario(store, scenario_id)
    return _get_run(history, scenario_id, run_id)


@router.post(
    "/{scenario_id}/optimization/runs/{run_id}/replay",
    response_model=OptimizationReplay,
)
def replay_optimization_run(
    scenario_id: str,
    run_id: str,
    store: Annotated[ScenarioStore, Depends(scenario_store)],
    history: Annotated[OptimizationRunStore, Depends(optimization_run_store)],
) -> OptimizationReplay:
    require_scenario(store, scenario_id)
    original = _get_run(history, scenario_id, run_id)
    try:
        replayed = plan_response(
            original.plan.assessment.optimization_input,
            method=original.plan.method_requested,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    saved = _save_plan(history, replayed, replay_of=run_id)
    return OptimizationReplay(
        original_run_id=run_id,
        matches_original=replay_payload(original.plan) == replay_payload(saved.plan),
        engine_matches_original=original.engine_fingerprint == saved.engine_fingerprint,
        runtime_matches_original=original.runtime_versions == saved.runtime_versions,
        plan=saved.plan,
    )
