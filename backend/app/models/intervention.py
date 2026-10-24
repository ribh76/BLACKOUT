"""Contracts for manually planned emergency responses."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    duration_minutes: int = Field(gt=0)
    prerequisites: list[str] = Field(default_factory=list)
    resource_costs: ResourceInventory
    expected_effects: list[str] = Field(min_length=1)
    execution_status: ExecutionStatus = ExecutionStatus.PLANNED

    @model_validator(mode="after")
    def validate_plan(self) -> "Intervention":
        if self.start_time.tzinfo is None or self.start_time.utcoffset() is None:
            raise ValueError("start_time must include a timezone")
        if any(not item.strip() for item in self.prerequisites):
            raise ValueError("prerequisites cannot contain blank entries")
        if any(not item.strip() for item in self.expected_effects):
            raise ValueError("expected_effects cannot contain blank entries")
        return self
