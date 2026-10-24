"""Separate cascade state, recorded events, and final results."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.models.infrastructure import InfrastructureNode, NodeStatus
from app.models.scenario import CityState


class SimulationEventKind(StrEnum):
    STATUS_TRANSITION = "STATUS_TRANSITION"
    BACKUP_ACTIVATED = "BACKUP_ACTIVATED"
    BACKUP_DEACTIVATED = "BACKUP_DEACTIVATED"
    BACKUP_DEPLETED = "BACKUP_DEPLETED"


class SimulationEvent(BaseModel):
    """One observable change, including its source and explanation."""

    model_config = ConfigDict(extra="forbid", strict=True)

    elapsed_minutes: int = Field(ge=0)
    time: datetime
    kind: SimulationEventKind
    node_id: str
    old_status: NodeStatus
    new_status: NodeStatus
    cause: str
    source_node_id: str | None = None
    explanation: str
    population_exposed: int = Field(default=0, ge=0)


class SimulationState(BaseModel):
    """A tick snapshot plus timers needed for deterministic later ticks."""

    model_config = ConfigDict(extra="forbid", strict=True)

    elapsed_minutes: int = Field(ge=0)
    city_state: CityState
    impaired_since_minutes: dict[str, int]
    healthy_minutes: dict[str, int]
    backup_active: set[str]
    refrigeration_unpowered_minutes: dict[str, int]
    signal_unpowered_minutes: dict[str, int]


class SimulationMetrics(BaseModel):
    """Final counts; population counts affected neighborhoods once."""

    affected_population: int = Field(ge=0)
    failed_infrastructure_count: int = Field(ge=0)
    critical_facility_count: int = Field(ge=0)
    system_risk_score: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description="Reserved for the later risk engine; no score is inferred here.",
    )


class SimulationResult(BaseModel):
    """Complete fixed-clock run, distinct from its evolving state."""

    scenario_id: str
    tick_minutes: list[int]
    states: list[SimulationState]
    events: list[SimulationEvent]
    final_node_states: list[InfrastructureNode]
    final_metrics: SimulationMetrics
