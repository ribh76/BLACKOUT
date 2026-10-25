"""Contracts for manually planned emergency responses."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.infrastructure import InfrastructureNode
from app.models.scenario import ResourceInventory


class InterventionType(StrEnum):
    DEPLOY_GENERATOR = "DEPLOY_GENERATOR"
    SEND_FUEL = "SEND_FUEL"
    REPAIR_SUBSTATION = "REPAIR_SUBSTATION"
    RESTORE_INTERSECTION = "RESTORE_INTERSECTION"
    RELOCATE_POPULATION = "RELOCATE_POPULATION"


class ExecutionStatus(StrEnum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ManualInterventionRequest(BaseModel):
    """User inputs; costs and effects always come from the server catalog."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1, pattern=r"\S")
    type: InterventionType = Field(strict=False)
    target_node_id: str = Field(min_length=1, pattern=r"\S")
    start_time: datetime = Field(strict=False)


class Intervention(BaseModel):
    """One proposed action; costs are expressed in inventory units.

    A planned action records an estimate. Scheduling and execution are separate
    simulator operations and must not be inferred from this model alone.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1, pattern=r"\S")
    type: InterventionType
    target_node_id: str = Field(min_length=1, pattern=r"\S")
    start_time: datetime = Field(strict=False)
    execution_delay_minutes: int = Field(ge=0)
    duration_minutes: int = Field(gt=0)
    prerequisites: list[str] = Field(default_factory=list)
    resource_costs: ResourceInventory
    expected_effects: list[str] = Field(min_length=1)
    failure_conditions: list[str] = Field(min_length=1)
    execution_status: ExecutionStatus = ExecutionStatus.PLANNED

    @model_validator(mode="after")
    def validate_plan(self) -> "Intervention":
        if self.start_time.tzinfo is None or self.start_time.utcoffset() is None:
            raise ValueError("start_time must include a timezone")
        if any(not item.strip() for item in self.prerequisites):
            raise ValueError("prerequisites cannot contain blank entries")
        if any(not item.strip() for item in self.expected_effects):
            raise ValueError("expected_effects cannot contain blank entries")
        if any(not item.strip() for item in self.failure_conditions):
            raise ValueError("failure_conditions cannot contain blank entries")
        return self


class InterventionNodeEffect(BaseModel):
    """Immediate node and next-tick pressure changes caused by one action."""

    node_id: str
    before: InfrastructureNode
    after: InfrastructureNode
    dependency_pressure_before: float = Field(ge=0, le=1)
    dependency_pressure_after: float = Field(ge=0, le=1)
    power_pressure_before: float = Field(ge=0, le=1)
    power_pressure_after: float = Field(ge=0, le=1)
    backup_duration_minutes_before: float | None = Field(ge=0)
    backup_duration_minutes_after: float | None = Field(ge=0)
    exposed_population_before: int = Field(ge=0)
    exposed_population_after: int = Field(ge=0)
    power_restored: bool
    route_reopened: bool


class InterventionEffectEstimate(BaseModel):
    completion_time: datetime
    execution_status: ExecutionStatus
    explanation: str
    node_effects: list[InterventionNodeEffect]
    population_relocated: int = Field(ge=0)
    receiving_node_id: str | None
    assumptions: list[str]


class InterventionCandidate(BaseModel):
    intervention: Intervention
    estimated_immediate_effects: InterventionEffectEstimate


class UnavailableIntervention(BaseModel):
    type: InterventionType
    target_node_id: str
    reason: str


class NodeInterventionCandidates(BaseModel):
    scenario_id: str
    node_id: str
    simulation_time: datetime
    candidates: list[InterventionCandidate]
    unavailable_actions: list[UnavailableIntervention]
