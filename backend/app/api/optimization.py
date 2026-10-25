"""Build optimization inputs without changing or applying a response plan."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.scenarios import require_scenario, scenario_store
from app.models.optimization import OptimizationInput, OptimizationInputRequest
from app.services.optimization import build_optimization_input
from app.services.scenarios import ScenarioStore

router = APIRouter(prefix="/scenarios", tags=["optimization"])


@router.post("/{scenario_id}/optimization/input", response_model=OptimizationInput)
def optimization_input(
    scenario_id: str,
    options: OptimizationInputRequest,
    store: Annotated[ScenarioStore, Depends(scenario_store)],
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
