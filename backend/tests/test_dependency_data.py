"""Validation of versioned dependency records and city references."""

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from app.services.city_data import load_city
from app.services.dependency_data import (
    DEFAULT_DEPENDENCY_PATH,
    DependencyDataError,
    load_dependencies,
)


def test_seed_edges_are_typed_and_serializable() -> None:
    city = load_city()
    data = load_dependencies(city)

    assert data.schema_version == 1
    assert data.city_schema_version == city.schema_version
    assert len(data.edges) == 49
    assert {edge.dependency_type.value for edge in data.edges} == {
        "POWER",
        "ACCESS",
        "SUPPLY",
    }
    assert {edge.requirement.value for edge in data.edges} == {"CRITICAL", "OPTIONAL"}
    assert type(data).model_validate_json(data.model_dump_json()) == data


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (lambda data: data.update(schema_version=2), "schema_version"),
        (
            lambda data: data["edges"][0].update(dependency_type="UNKNOWN"),
            "edges.0.dependency_type",
        ),
        (lambda data: data["edges"][0].update(weight=0), "edges.0.weight"),
        (
            lambda data: data["edges"][0].update(failure_delay_minutes=-1),
            "edges.0.failure_delay_minutes",
        ),
        (
            lambda data: data["edges"][0].update(requirement="MANDATORY"),
            "edges.0.requirement",
        ),
        (
            lambda data: data["edges"][0].pop("restoration_requirement"),
            "edges.0.restoration_requirement",
        ),
        (
            lambda data: data["edges"].append(data["edges"][0].copy()),
            "duplicate dependency",
        ),
        (
            lambda data: data["edges"][0].update(provider_id="unknown"),
            "unknown provider_id",
        ),
        (
            lambda data: data["edges"][0].update(dependent_id="unknown"),
            "unknown dependent_id",
        ),
    ],
)
def test_rejects_invalid_edges(
    tmp_path: Path, change: Callable[[dict[str, Any]], object], expected: str
) -> None:
    payload = json.loads(DEFAULT_DEPENDENCY_PATH.read_text(encoding="utf-8"))
    change(payload)
    path = tmp_path / "dependencies.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DependencyDataError) as error:
        load_dependencies(load_city(), path)

    assert expected in str(error.value)
    assert str(path) in str(error.value)


def test_rejects_malformed_dependency_json(tmp_path: Path) -> None:
    path = tmp_path / "dependencies.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(DependencyDataError, match="Invalid JSON"):
        load_dependencies(load_city(), path)
