"""Validated, directed relationships between infrastructure assets."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DependencyType(StrEnum):
    POWER = "POWER"
    ACCESS = "ACCESS"
    SUPPLY = "SUPPLY"


class DependencyRequirement(StrEnum):
    CRITICAL = "CRITICAL"
    OPTIONAL = "OPTIONAL"


class RestorationRequirement(StrEnum):
    SOURCE_RESTORED = "SOURCE_RESTORED"
    ROUTE_REOPENED = "ROUTE_REOPENED"
    INVENTORY_REPLENISHED = "INVENTORY_REPLENISHED"


class DependencyEdge(BaseModel):
    """Provider -> dependent; weight is normalized influence in (0, 1].

    The failure delay is the minimum minutes after provider degradation before
    dependency pressure can begin. Restoration requirements describe what must
    recover for the relationship to operate again.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    provider_id: str = Field(min_length=1, pattern=r"\S")
    dependent_id: str = Field(min_length=1, pattern=r"\S")
    dependency_type: DependencyType = Field(strict=False)
    weight: float = Field(gt=0, le=1, allow_inf_nan=False)
    failure_delay_minutes: int = Field(ge=0)
    restoration_requirement: RestorationRequirement = Field(strict=False)
    requirement: DependencyRequirement = Field(strict=False)

    @model_validator(mode="after")
    def validate_direction(self) -> "DependencyEdge":
        if self.provider_id == self.dependent_id:
            raise ValueError("provider_id and dependent_id must differ")
        return self


class DependencyData(BaseModel):
    """A versioned set of dependency edges for city schema version 1."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    city_schema_version: Literal[1]
    edges: list[DependencyEdge] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_edges(self) -> "DependencyData":
        seen: dict[tuple[str, str], int] = {}
        for index, edge in enumerate(self.edges):
            pair = (edge.provider_id, edge.dependent_id)
            if pair in seen:
                raise ValueError(
                    f"duplicate dependency {pair[0]!r} -> {pair[1]!r} "
                    f"at edges[{seen[pair]}] and edges[{index}]"
                )
            seen[pair] = index
        return self


class DependencyPath(BaseModel):
    """A shortest directed path and the exact metadata for each hop."""

    source_id: str
    target_id: str
    node_ids: list[str]
    edges: list[DependencyEdge]


class DownstreamImpact(BaseModel):
    """Potential exposure if the source asset degrades or fails.

    affected_population counts residents in downstream neighborhoods only.
    service_population_exposure sums population_served across every downstream
    asset and can count the same person more than once.
    Critical facilities are substations, hospitals, pharmacies, shelters, and
    cooling centers.
    """

    source_id: str
    downstream_node_ids: list[str]
    downstream_node_count: int = Field(ge=0)
    affected_population: int = Field(ge=0)
    service_population_exposure: int = Field(ge=0)
    critical_facility_ids: list[str]
    critical_facility_count: int = Field(ge=0)
