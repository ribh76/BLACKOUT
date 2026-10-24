"""Reproducibility and validation contracts for the demo scenario."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.infrastructure import NodeStatus
from app.services.city_data import load_city
from app.services.dependency_data import load_dependencies
from app.services.scenarios import (
    DEFAULT_SCENARIO_PATH,
    ScenarioDataError,
    ScenarioStore,
    load_scenario,
)

SCENARIO_ID = "extreme-heat-grid-failure"


def test_scenario_seed_contains_fixed_disaster_conditions() -> None:
    scenario = load_scenario(load_city())

    assert scenario.id == SCENARIO_ID
    assert scenario.name == "Extreme Heat + Grid Failure"
    assert scenario.temperature_f == 105
    assert scenario.grid_load == 0.97
    assert scenario.initial_failures == ["substation-03"]
    assert scenario.initial_degradations == ["substation-07"]
    assert scenario.start_time.isoformat() == "2026-07-15T14:00:00-07:00"
    assert scenario.duration_minutes == 240


def test_start_and_reset_replay_identical_snapshots_and_events() -> None:
    city = load_city()
    edges = load_dependencies(city).edges
    store = ScenarioStore(load_scenario(city), city, edges)

    pristine = store.get_scenario_state()
    first = store.start_scenario()
    first_json = first.model_dump(mode="json")
    reset = store.reset_scenario()
    second = store.start_scenario()

    assert reset == pristine
    assert second.model_dump(mode="json") == first_json
    assert first.simulation_time == pristine.simulation_time
    assert [
        (event.sequence, event.node_id, event.status, event.time)
        for event in first.event_history
    ] == [
        (0, "substation-03", NodeStatus.FAILED, pristine.simulation_time),
        (1, "substation-07", NodeStatus.DEGRADED, pristine.simulation_time),
    ]
    assert {
        node.id: node.status
        for node in first.nodes
        if node.id in {"substation-03", "substation-07"}
    } == {
        "substation-03": NodeStatus.FAILED,
        "substation-07": NodeStatus.DEGRADED,
    }
    assert all(node.status is NodeStatus.OPERATIONAL for node in reset.nodes)
    assert len(first.nodes) == len(city.nodes)
    assert len(first.dependency_edges) == len(edges)

    # Edits to a returned run cannot contaminate the store, source city, or graph.
    first.nodes[0].status = NodeStatus.CRITICAL
    first.resource_inventory.mobile_generators = 0
    first.dependency_edges[0].weight = 0.01
    assert store.get_scenario_state() == second
    assert city.nodes[0].status is NodeStatus.OPERATIONAL
    assert edges[0].weight != 0.01


def test_scenario_api_lists_starts_and_resets_same_disaster() -> None:
    with TestClient(app) as client:
        listed = client.get("/api/scenarios")
        detail = client.get(f"/api/scenarios/{SCENARIO_ID}")
        started = client.post(f"/api/scenarios/{SCENARIO_ID}/start")
        reset = client.post(f"/api/scenarios/{SCENARIO_ID}/reset")
        replay = client.post(f"/api/scenarios/{SCENARIO_ID}/start")
        missing = client.get("/api/scenarios/unknown")

    assert listed.status_code == detail.status_code == 200
    assert listed.json() == [detail.json()]
    assert started.status_code == reset.status_code == replay.status_code == 200
    assert started.json() == replay.json()
    assert reset.json()["event_history"] == []
    assert missing.status_code == 404


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        (
            lambda data: data.update(initial_failures=["unknown"]),
            "unknown initial event node",
        ),
        (
            lambda data: data.update(initial_degradations=["unknown"]),
            "unknown initial event node",
        ),
        (
            lambda data: data["resource_inventory"].update(fuel_gallons=-1),
            "fuel_gallons",
        ),
        (
            lambda data: data.update(initial_degradations=["substation-03"]),
            "unique node IDs",
        ),
        (lambda data: data.update(start_time="2026-07-15T14:00:00"), "timezone"),
    ],
)
def test_invalid_scenario_is_rejected(
    tmp_path: Path, change: Callable[[dict[str, Any]], object], expected: str
) -> None:
    payload = json.loads(DEFAULT_SCENARIO_PATH.read_text(encoding="utf-8"))
    change(payload)
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ScenarioDataError, match=expected):
        load_scenario(load_city(), path)
