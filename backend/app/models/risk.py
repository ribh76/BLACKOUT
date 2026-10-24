"""Explainable risk estimates for one city snapshot."""

from pydantic import BaseModel, Field

from app.models.infrastructure import InfrastructureType, NodeStatus


class NodeRisk(BaseModel):
    node_id: str
    name: str
    type: InfrastructureType
    status: NodeStatus
    impact_score: float = Field(ge=0, le=100)
    human_exposure: float = Field(ge=0, le=1)
    systemic_impact: float = Field(ge=0, le=1)
    population_vulnerability: float = Field(ge=0, le=1)
    dependency_degradation: float = Field(ge=0, le=1)
    load_stress: float = Field(ge=0, le=1)
    environmental_stress: float = Field(ge=0, le=1)
    backup_resilience: float = Field(ge=0, le=1)
    failure_probability: float = Field(ge=0, le=1)
    risk_score: float = Field(ge=0, le=100)
    time_to_failure_minutes: int | None = Field(default=None, ge=0)
    operational_priority: float = Field(ge=0, le=100)
    direct_dependents: int = Field(ge=0)
    downstream_dependents: int = Field(ge=0)
    downstream_node_ids: list[str]
    primary_drivers: list[str]
    quality_indicators: list[str]


class RiskRanking(BaseModel):
    scenario_id: str
    simulation_time: str
    count: int = Field(ge=0)
    nodes: list[NodeRisk]
