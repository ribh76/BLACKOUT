"""Risk ranking for the current scenario snapshot."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.scenarios import require_scenario, scenario_store
from app.models.risk import NodeRisk, RiskRanking
from app.services.risk import rank_risk
from app.services.scenarios import ScenarioStore

router = APIRouter(prefix="/scenarios", tags=["risk"])


@router.get("/{scenario_id}/risk", response_model=RiskRanking)
def risk_ranking(
    scenario_id: str, store: Annotated[ScenarioStore, Depends(scenario_store)]
) -> RiskRanking:
    require_scenario(store, scenario_id)
    return rank_risk(store.get_scenario_state())


@router.get("/{scenario_id}/risk/{node_id}", response_model=NodeRisk)
def node_risk(
    scenario_id: str,
    node_id: str,
    store: Annotated[ScenarioStore, Depends(scenario_store)],
) -> NodeRisk:
    require_scenario(store, scenario_id)
    ranking = rank_risk(store.get_scenario_state())
    for node in ranking.nodes:
        if node.node_id == node_id:
            return node
    raise HTTPException(
        status_code=404, detail=f"Infrastructure node {node_id!r} not found"
    )
