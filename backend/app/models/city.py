"""Schema and baseline rules for the versioned simulated city."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.infrastructure import InfrastructureNode, InfrastructureType, NodeStatus

CAPACITY_UNITS: dict[InfrastructureType, str] = {
    InfrastructureType.SUBSTATION: "MW",
    InfrastructureType.HOSPITAL: "occupied beds",
    InfrastructureType.INTERSECTION: "vehicles per hour",
    InfrastructureType.PHARMACY: "prescriptions per day",
    InfrastructureType.SHELTER: "people",
    InfrastructureType.COOLING_CENTER: "people",
    InfrastructureType.WAREHOUSE: "pallets per day",
    InfrastructureType.NEIGHBORHOOD: "residents",
    InfrastructureType.EMERGENCY_ROUTE: "vehicles per hour",
}

# Backup is measured in each type's capacity units. These are baseline seed
# constraints; later simulation states may deplete backup_remaining to zero.
REQUIRES_INITIAL_BACKUP = frozenset(
    {
        InfrastructureType.HOSPITAL,
        InfrastructureType.PHARMACY,
        InfrastructureType.COOLING_CENTER,
    }
)
NO_BASELINE_BACKUP = frozenset(
    {InfrastructureType.NEIGHBORHOOD, InfrastructureType.EMERGENCY_ROUTE}
)


class CityData(BaseModel):
    """A complete initial city; schema changes require a new version."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal[1]
    city: str = Field(min_length=1, pattern=r"\S")
    capacity_units: dict[str, str]
    data_notice: str = Field(min_length=1, pattern=r"\S")
    nodes: list[InfrastructureNode] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_baseline(self) -> "CityData":
        expected_units = {kind.value: unit for kind, unit in CAPACITY_UNITS.items()}
        if self.capacity_units != expected_units:
            raise ValueError(
                "capacity_units must match the declared units for every "
                "infrastructure type"
            )

        seen: dict[str, int] = {}
        for index, node in enumerate(self.nodes):
            if node.id in seen:
                raise ValueError(
                    f"duplicate node ID {node.id!r} at nodes[{seen[node.id]}] "
                    f"and nodes[{index}]"
                )
            seen[node.id] = index

            if not 37.20 <= node.coordinates.latitude <= 37.43 or not (
                -122.0 <= node.coordinates.longitude <= -121.78
            ):
                raise ValueError(
                    f"nodes[{index}] ({node.id}): coordinates outside the "
                    "simulated San Jose area"
                )
            if node.status is not NodeStatus.OPERATIONAL:
                raise ValueError(
                    f"nodes[{index}] ({node.id}): initial status must be OPERATIONAL"
                )
            if node.current_load > node.capacity:
                raise ValueError(
                    f"nodes[{index}] ({node.id}): initial current_load exceeds capacity"
                )
            if node.type in REQUIRES_INITIAL_BACKUP and node.backup_remaining == 0:
                raise ValueError(
                    f"nodes[{index}] ({node.id}): {node.type.value} requires "
                    "initial backup_remaining above zero"
                )
            if node.type in NO_BASELINE_BACKUP and node.backup_capacity != 0:
                raise ValueError(
                    f"nodes[{index}] ({node.id}): {node.type.value} must have "
                    "zero baseline backup_capacity"
                )
            if (
                node.type is InfrastructureType.NEIGHBORHOOD
                and node.capacity != node.population_served
            ):
                raise ValueError(
                    f"nodes[{index}] ({node.id}): NEIGHBORHOOD capacity must "
                    "equal population_served (residents)"
                )

        return self
