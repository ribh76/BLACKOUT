import pytest
from pydantic import ValidationError

from app.models.infrastructure import InfrastructureNode


@pytest.fixture
def node_data() -> dict[str, object]:
    return {
        "id": "substation-03",
        "name": "Substation 03",
        "type": "SUBSTATION",
        "coordinates": {"latitude": 37.3382, "longitude": -121.8863},
        "status": "OPERATIONAL",
        "criticality": 0.9,
        "population_served": 8200,
        "capacity": 100.0,
        "current_load": 97.0,
        "backup_capacity": 20.0,
        "backup_remaining": 12.0,
        "failure_threshold": 1.15,
        "recovery_time_minutes": 120,
        "vulnerability": 0.7,
    }


def test_node_round_trips_through_json(node_data: dict[str, object]) -> None:
    node = InfrastructureNode.model_validate(node_data)

    assert InfrastructureNode.model_validate_json(node.model_dump_json()) == node
    assert node.model_dump(mode="json")["type"] == "SUBSTATION"
    assert node.model_dump(mode="json")["coordinates"] == node_data["coordinates"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "   "),
        ("type", "POWER_PLANT"),
        ("status", "UNKNOWN"),
        ("population_served", -1),
        ("capacity", 0),
        ("current_load", -1),
        ("backup_capacity", -1),
        ("backup_remaining", 21),
        ("failure_threshold", 0),
        ("recovery_time_minutes", -1),
        ("criticality", 1.1),
        ("vulnerability", -0.1),
    ],
)
def test_rejects_invalid_node_fields(
    node_data: dict[str, object], field: str, value: object
) -> None:
    node_data[field] = value

    with pytest.raises(ValidationError):
        InfrastructureNode.model_validate(node_data)


@pytest.mark.parametrize(
    "coordinates",
    [{"latitude": 91, "longitude": 0}, {"latitude": 0, "longitude": -181}],
)
def test_rejects_impossible_coordinates(
    node_data: dict[str, object], coordinates: dict[str, int]
) -> None:
    node_data["coordinates"] = coordinates

    with pytest.raises(ValidationError):
        InfrastructureNode.model_validate(node_data)


def test_requires_all_fields_and_rejects_unknown_fields(
    node_data: dict[str, object],
) -> None:
    del node_data["population_served"]
    node_data["unrecognized"] = 1

    with pytest.raises(ValidationError) as error:
        InfrastructureNode.model_validate(node_data)

    assert {item["type"] for item in error.value.errors()} == {
        "missing",
        "extra_forbidden",
    }


def test_load_can_exceed_capacity_during_cascade(node_data: dict[str, object]) -> None:
    node_data["current_load"] = 125.0

    assert InfrastructureNode.model_validate(node_data).current_load == 125.0
