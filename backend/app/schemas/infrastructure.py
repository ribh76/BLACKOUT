"""Public infrastructure responses."""

from typing import Literal

from pydantic import BaseModel, Field

from app.models.infrastructure import InfrastructureNode


class InfrastructureSnapshotResponse(BaseModel):
    schema_version: Literal[1]
    city: str
    capacity_units: dict[str, str]
    data_notice: str
    count: int = Field(ge=0)
    nodes: list[InfrastructureNode]
