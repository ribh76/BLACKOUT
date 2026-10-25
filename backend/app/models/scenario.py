"""Versioned disaster inputs and replayable city snapshots."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.dependency import DependencyEdge
from app.models.infrastructure import InfrastructureNode, NodeStatus


class ResourceInventory(BaseModel):
    """Available intervention resources at the start of a run."""

    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)

    mobile_generators: int = Field(ge=0)
    fuel_gallons: int = Field(ge=0)
    electrical_crews: int = Field(ge=0)
    traffic_crews: int = Field(ge=0)
    emergency_vehicles: int = Field(ge=0)
    response_personnel: int = Field(default=0, ge=0)


class Scenario(BaseModel):
    """Fixed external conditions; grid_load is a fraction of rated capacity."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    id: str = Field(min_length=1, pattern=r"\S")
    name: str = Field(min_length=1, pattern=r"\S")
    description: str = Field(min_length=1, pattern=r"\S")
    start_time: datetime = Field(strict=False)
    duration_minutes: int = Field(gt=0)
    temperature_f: float = Field(allow_inf_nan=False)
    grid_load: float = Field(ge=0, le=1, allow_inf_nan=False)
    initial_failures: list[str]
    initial_degradations: list[str]
    resource_inventory: ResourceInventory

    @model_validator(mode="after")
    def validate_events(self) -> "Scenario":
        if self.start_time.tzinfo is None or self.start_time.utcoffset() is None:
            raise ValueError("start_time must include a timezone")
        affected = self.initial_failures + self.initial_degradations
        if len(affected) != len(set(affected)):
            raise ValueError(
                "initial failures and degradations must have unique node IDs"
            )
        if any(not node_id.strip() for node_id in affected):
            raise ValueError("initial event node IDs cannot be blank")
        return self


class ScenarioEvent(BaseModel):
    """An initial status transition at a fixed simulation time."""

    model_config = ConfigDict(extra="forbid", strict=True)

    sequence: int = Field(ge=0)
    time: datetime = Field(strict=False)
    node_id: str
    status: NodeStatus = Field(strict=False)

    @model_validator(mode="after")
    def validate_time(self) -> "ScenarioEvent":
        if self.time.tzinfo is None or self.time.utcoffset() is None:
            raise ValueError("event time must include a timezone")
        return self


class CityState(BaseModel):
    """Versioned replay snapshot with full nodes, graph edges, and event order.

    All timestamps are timezone-aware ISO 8601 values when serialized as JSON.
    ``grid_load`` is a fraction; ``temperature_f`` is degrees Fahrenheit.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    scenario_id: str
    city: str
    city_schema_version: Literal[1]
    capacity_units: dict[str, str]
    data_notice: str
    simulation_time: datetime = Field(strict=False)
    duration_minutes: int = Field(gt=0)
    temperature_f: float = Field(allow_inf_nan=False)
    grid_load: float = Field(ge=0, le=1, allow_inf_nan=False)
    nodes: list[InfrastructureNode]
    dependency_edges: list[DependencyEdge]
    resource_inventory: ResourceInventory
    event_history: list[ScenarioEvent]

    @model_validator(mode="after")
    def validate_time(self) -> "CityState":
        if (
            self.simulation_time.tzinfo is None
            or self.simulation_time.utcoffset() is None
        ):
            raise ValueError("simulation_time must include a timezone")
        return self
