"""Contract checks for the versioned simulated San Jose seed data."""

import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.infrastructure import InfrastructureType, NodeStatus
from app.services.city_data import CityDataError, load_city

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "san_jose_v1.json"


def test_seed_city_is_valid_and_covers_every_infrastructure_type() -> None:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert set(payload["capacity_units"]) == {kind.value for kind in InfrastructureType}

    nodes = load_city().nodes
    assert 30 <= len(nodes) <= 40
    assert len({node.id for node in nodes}) == len(nodes)
    assert all(node.status is NodeStatus.OPERATIONAL for node in nodes)

    counts = Counter(node.type for node in nodes)
    assert set(counts) == set(InfrastructureType)
    minimum_counts = {
        InfrastructureType.SUBSTATION: 4,
        InfrastructureType.HOSPITAL: 3,
        InfrastructureType.INTERSECTION: 7,
        InfrastructureType.PHARMACY: 4,
        InfrastructureType.SHELTER: 3,
        InfrastructureType.COOLING_CENTER: 3,
        InfrastructureType.WAREHOUSE: 2,
        InfrastructureType.NEIGHBORHOOD: 7,
        InfrastructureType.EMERGENCY_ROUTE: 3,
    }
    assert all(counts[kind] >= minimum for kind, minimum in minimum_counts.items())

    # Keep the seed in the San Jose area; the model itself accepts global coordinates.
    assert all(37.20 <= node.coordinates.latitude <= 37.43 for node in nodes)
    assert all(-122.0 <= node.coordinates.longitude <= -121.78 for node in nodes)
    assert all(node.current_load <= node.capacity for node in nodes)

    # These IDs are referenced by the planned extreme heat and grid failure scenario.
    assert {"substation-03", "substation-07"} <= {node.id for node in nodes}


def test_seed_profiles_distinguish_hospital_neighborhood_and_signal() -> None:
    city = load_city()
    by_id = {node.id: node for node in city.nodes}
    hospital = by_id["hospital-downtown"]
    neighborhood = by_id["neighborhood-downtown"]
    signal = by_id["intersection-santa-clara-market"]

    assert city.capacity_units[hospital.type.value] == "occupied beds"
    assert hospital.backup_remaining > 0
    assert hospital.recovery_time_minutes > signal.recovery_time_minutes

    assert city.capacity_units[neighborhood.type.value] == "residents"
    assert neighborhood.capacity == neighborhood.population_served
    assert neighborhood.backup_capacity == 0

    assert city.capacity_units[signal.type.value] == "vehicles per hour"
    assert signal.backup_capacity / signal.capacity < (
        hospital.backup_capacity / hospital.capacity
    )


def test_city_is_loaded_during_application_startup() -> None:
    with TestClient(app):
        assert len(app.state.city_data.nodes) == 36


def test_invalid_seed_stops_application_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "invalid-city.json"
    path.write_text('{"schema_version": 2}', encoding="utf-8")
    monkeypatch.setattr("app.main.load_city", lambda: load_city(path))

    with pytest.raises(CityDataError, match="schema_version"):
        with TestClient(app):
            pass


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (
            lambda data: data["nodes"][1].update(id="substation-01"),
            "duplicate node ID 'substation-01'",
        ),
        (lambda data: data["nodes"][0].update(type="POWER_PLANT"), "nodes.0.type"),
        (
            lambda data: data["nodes"][0]["coordinates"].update(latitude=95),
            "nodes.0.coordinates.latitude",
        ),
        (
            lambda data: data["nodes"][0]["coordinates"].update(latitude=35),
            "outside the simulated San Jose area",
        ),
        (lambda data: data["nodes"][0].pop("name"), "nodes.0.name: Field required"),
        (lambda data: data.update(schema_version=2), "schema_version"),
        (lambda data: data.update(nodes=[]), "nodes: List should have at least 1 item"),
        (
            lambda data: data["nodes"][4].update(backup_remaining=0),
            "HOSPITAL requires initial backup_remaining",
        ),
        (
            lambda data: data["nodes"][26].update(backup_capacity=10),
            "NEIGHBORHOOD must have zero baseline backup_capacity",
        ),
        (
            lambda data: data["nodes"][0].update(current_load=150),
            "initial current_load exceeds capacity",
        ),
        (
            lambda data: data["capacity_units"].update(HOSPITAL="vehicles per hour"),
            "capacity_units must match",
        ),
    ],
)
def test_loader_explains_invalid_city_records(
    tmp_path: Path, change: Callable[[dict[str, Any]], object], expected: str
) -> None:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    change(payload)
    path = tmp_path / "city.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CityDataError, match="Invalid city data") as error:
        load_city(path)
    assert expected in str(error.value)
    assert str(path) in str(error.value)


def test_loader_explains_malformed_or_duplicated_json(tmp_path: Path) -> None:
    path = tmp_path / "city.json"
    path.write_text('{"schema_version": 1, "schema_version": 1}', encoding="utf-8")
    with pytest.raises(CityDataError, match="duplicate JSON key 'schema_version'"):
        load_city(path)

    path.write_text("{", encoding="utf-8")
    with pytest.raises(CityDataError, match="Invalid JSON"):
        load_city(path)


def test_loader_explains_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CityDataError, match="Cannot read city data"):
        load_city(tmp_path / "missing.json")


def test_node_statuses_and_types_have_only_declared_values() -> None:
    assert {status.value for status in NodeStatus} == {
        "OPERATIONAL",
        "DEGRADED",
        "CRITICAL",
        "FAILED",
    }
    assert {kind.value for kind in InfrastructureType} == {
        "SUBSTATION",
        "HOSPITAL",
        "INTERSECTION",
        "PHARMACY",
        "SHELTER",
        "COOLING_CENTER",
        "WAREHOUSE",
        "NEIGHBORHOOD",
        "EMERGENCY_ROUTE",
    }
