"""Public infrastructure responses."""

from typing import Literal

from pydantic import BaseModel, Field

from app.models.dependency import DependencyEdge
from app.models.infrastructure import InfrastructureNode


class InfrastructureSnapshotResponse(BaseModel):
    schema_version: Literal[1]
    city: str
    capacity_units: dict[str, str]
    data_notice: str
    count: int = Field(ge=0)
    nodes: list[InfrastructureNode]


class InfrastructureDependenciesResponse(BaseModel):
    """Direct and transitive relationships for one asset.

    Every edge points from provider to dependent. ``dependencies`` are direct
    providers, while ``dependents`` are direct consumers. The matching edge
    lists expose the metadata for those direct relationships.
    """

    node_id: str
    dependencies: list[str]
    dependents: list[str]
    upstream_nodes: list[str]
    downstream_nodes: list[str]
    dependency_edges: list[DependencyEdge]
    dependent_edges: list[DependencyEdge]
