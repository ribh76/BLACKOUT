"""Discover, start, and reset reproducible disaster scenarios."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.models.scenario import CityState, Scenario
from app.services.scenarios import ScenarioStore

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
