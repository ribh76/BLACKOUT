"""Infrastructure assets and their initial or simulated state."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NodeStatus(StrEnum):
    OPERATIONAL = "OPERATIONAL"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"
    FAILED = "FAILED"


class InfrastructureType(StrEnum):
    SUBSTATION = "SUBSTATION"
    HOSPITAL = "HOSPITAL"
    INTERSECTION = "INTERSECTION"
    PHARMACY = "PHARMACY"
    SHELTER = "SHELTER"
    COOLING_CENTER = "COOLING_CENTER"
    WAREHOUSE = "WAREHOUSE"
    NEIGHBORHOOD = "NEIGHBORHOOD"
    EMERGENCY_ROUTE = "EMERGENCY_ROUTE"


class Coordinates(BaseModel):
    """Geographic WGS84 coordinates in decimal degrees."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)

    latitude: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(ge=-180, le=180, allow_inf_nan=False)


class InfrastructureNode(BaseModel):
    """One asset; capacities and load share units within each asset type.

    Criticality and vulnerability are normalized to [0, 1]. The failure
    threshold is a positive load-to-capacity ratio. Recovery time is minutes.
    """

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)

    id: str = Field(min_length=1, pattern=r"\S")
    name: str = Field(min_length=1, pattern=r"\S")
    type: InfrastructureType = Field(strict=False)
    coordinates: Coordinates
    status: NodeStatus = Field(strict=False)
    criticality: float = Field(ge=0, le=1, allow_inf_nan=False)
    population_served: int = Field(ge=0)
    capacity: float = Field(gt=0, allow_inf_nan=False)
    current_load: float = Field(ge=0, allow_inf_nan=False)
    backup_capacity: float = Field(ge=0, allow_inf_nan=False)
    backup_remaining: float = Field(ge=0, allow_inf_nan=False)
    failure_threshold: float = Field(gt=0, allow_inf_nan=False)
    recovery_time_minutes: int = Field(ge=0)
    vulnerability: float = Field(ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_backup(self) -> "InfrastructureNode":
        if self.backup_remaining > self.backup_capacity:
            raise ValueError("backup_remaining cannot exceed backup_capacity")
        return self
