"""Discover, start, and reset reproducible disaster scenarios."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.models.intervention import Intervention, ManualInterventionRequest
from app.models.scenario import CityState, Scenario
from app.models.simulation import SimulationResult
from app.services.interventions import (
    InterventionError,
    propose_intervention,
    validate_intervention_plan,
)
from app.services.risk import rank_risk
from app.services.scenarios import ScenarioStore
from app.services.simulation import run_simulation

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


def scenario_store(request: Request) -> ScenarioStore:
    return request.app.state.scenario_store


def require_scenario(store: ScenarioStore, scenario_id: str) -> None:
    if scenario_id != store.scenario.id:
        raise HTTPException(
            status_code=404, detail=f"Scenario {scenario_id!r} not found"
        )


@router.get("", response_model=list[Scenario])
def list_scenarios(
    store: Annotated[ScenarioStore, Depends(scenario_store)],
) -> list[Scenario]:
    return [store.scenario]


@router.get("/{scenario_id}", response_model=Scenario)
def get_scenario(
    scenario_id: str, store: Annotated[ScenarioStore, Depends(scenario_store)]
) -> Scenario:
    require_scenario(store, scenario_id)
    return store.scenario


@router.get("/{scenario_id}/state", response_model=CityState)
def get_scenario_state(
    scenario_id: str, store: Annotated[ScenarioStore, Depends(scenario_store)]
) -> CityState:
    require_scenario(store, scenario_id)
    return store.get_scenario_state()


@router.post("/{scenario_id}/start", response_model=CityState)
def start_scenario(
    scenario_id: str, store: Annotated[ScenarioStore, Depends(scenario_store)]
) -> CityState:
    require_scenario(store, scenario_id)
    return store.start_scenario()


@router.post("/{scenario_id}/reset", response_model=CityState)
def reset_scenario(
    scenario_id: str, store: Annotated[ScenarioStore, Depends(scenario_store)]
) -> CityState:
    require_scenario(store, scenario_id)
    return store.reset_scenario()


@router.post("/{scenario_id}/simulate", response_model=SimulationResult)
def simulate_scenario(
    scenario_id: str, store: Annotated[ScenarioStore, Depends(scenario_store)]
) -> SimulationResult:
    """Run the fixed timeline from a fresh copy of the scenario's T+0 state."""

    require_scenario(store, scenario_id)
    result = run_simulation(store.start_scenario())
    result.risk_rankings = {
        state.elapsed_minutes: rank_risk(state.city_state) for state in result.states
    }
    return result


def _manual_plan(
    state: CityState, requests: list[ManualInterventionRequest]
) -> list[Intervention]:
    try:
        actions = [
            propose_intervention(
                state,
                request.id,
                request.type,
                request.target_node_id,
                request.start_time,
            )
            for request in requests
        ]
        return validate_intervention_plan(state, actions)
    except InterventionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{scenario_id}/interventions/validate", response_model=list[Intervention])
def validate_manual_interventions(
    scenario_id: str,
    requests: list[ManualInterventionRequest],
    store: Annotated[ScenarioStore, Depends(scenario_store)],
) -> list[Intervention]:
    require_scenario(store, scenario_id)
    return _manual_plan(store.initial_scenario_state(), requests)


@router.post("/{scenario_id}/interventions/simulate", response_model=SimulationResult)
def simulate_manual_interventions(
    scenario_id: str,
    requests: list[ManualInterventionRequest],
    store: Annotated[ScenarioStore, Depends(scenario_store)],
) -> SimulationResult:
    require_scenario(store, scenario_id)
    state = store.initial_scenario_state()
    plan = _manual_plan(state, requests)
    result = run_simulation(state, plan)
    result.risk_rankings = {
        tick.elapsed_minutes: rank_risk(tick.city_state) for tick in result.states
    }
    return result
