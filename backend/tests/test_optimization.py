"""Optimization inputs use current risk, catalog eligibility, and finite budgets."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.infrastructure import NodeStatus
from app.models.optimization import ObjectiveWeights
from app.services.city_data import load_city
from app.services.dependency_data import load_dependencies
from app.services.optimization import build_optimization_input
from app.services.scenarios import ScenarioStore, load_scenario


@pytest.fixture
def snapshot():
    city = load_city()
    return ScenarioStore(
        load_scenario(city), city, load_dependencies(city).edges
    ).start_scenario()


def test_current_failed_and_critical_targets_only_when_high_risk_disabled(snapshot):
    critical = next(n for n in snapshot.nodes if n.id == "intersection-story-king")
    critical.status = NodeStatus.CRITICAL
    before = snapshot.model_dump_json()
    result = build_optimization_input(snapshot, high_risk_threshold=100.0)
    targets = {a.target_node_id for a in result.candidate_interventions}
    assert "substation-03" in targets
    assert critical.id in targets
    assert "substation-07" not in targets  # merely degraded
    assert all(
        n.status in {NodeStatus.FAILED, NodeStatus.CRITICAL}
        for n in snapshot.nodes
        if n.id in targets
    )
    assert snapshot.model_dump_json() == before
    assert result == build_optimization_input(snapshot, high_risk_threshold=100.0)


def test_high_risk_includes_preventive_actions_and_excludes_invalid_types(snapshot):
    result = build_optimization_input(snapshot, high_risk_threshold=0.0)
    pairs = {(a.type.value, a.target_node_id) for a in result.candidate_interventions}
    assert ("DEPLOY_GENERATOR", "hospital-downtown") in pairs
    assert ("REPAIR_SUBSTATION", "hospital-downtown") not in pairs
    assert ("REPAIR_SUBSTATION", "substation-07") in pairs
    assert ("RESTORE_INTERSECTION", "intersection-santa-clara-market") not in pairs
    assert len(pairs) == len(result.candidate_interventions)


def test_horizon_and_inventory_restrict_candidates_without_consuming(snapshot):
    result = build_optimization_input(snapshot, planning_horizon_minutes=30)
    assert all(
        a.type.value != "REPAIR_SUBSTATION" for a in result.candidate_interventions
    )
    for field in type(snapshot.resource_inventory).model_fields:
        setattr(snapshot.resource_inventory, field, 0)
    empty = build_optimization_input(snapshot)
    assert empty.candidate_interventions == []


@pytest.mark.parametrize("horizon", [0, 45, 150])
def test_invalid_horizon(snapshot, horizon):
    with pytest.raises(ValueError):
        build_optimization_input(snapshot, planning_horizon_minutes=horizon)


@pytest.mark.parametrize(
    "weights",
    [
        {"risk_reduction": -1},
        {"risk_reduction": float("inf")},
        {
            "risk_reduction": 0,
            "population_protection": 0,
            "critical_facility_protection": 0,
        },
    ],
)
def test_invalid_objective_weights(weights):
    with pytest.raises(ValidationError):
        ObjectiveWeights(**weights)


def test_api_uses_current_store_and_accepts_playback_snapshot(snapshot):
    path = "/api/scenarios/extreme-heat-grid-failure/optimization/input"
    with TestClient(app) as client:
        client.post("/api/scenarios/extreme-heat-grid-failure/start")
        before = client.get("/api/scenarios/extreme-heat-grid-failure/state").json()
        response = client.post(path, json={"high_risk_threshold": 100})
        assert response.status_code == 200
        payload = response.json()
        assert payload["current_city_state"] == before
        assert payload["resource_inventory"] == before["resource_inventory"]
        assert (
            payload["candidate_interventions"][0]["target_node_id"] == "substation-03"
        )
        snapshot.nodes = [n for n in snapshot.nodes if n.id == "substation-03"]
        snapshot.dependency_edges = []
        snapshot.event_history = []
        snapshot.nodes[0].status = NodeStatus.OPERATIONAL
        custom = client.post(
            path,
            json={
                "current_city_state": snapshot.model_dump(mode="json"),
                "high_risk_threshold": 100,
            },
        )
        assert custom.status_code == 200
        assert custom.json()["candidate_interventions"] == []
        assert (
            client.get("/api/scenarios/extreme-heat-grid-failure/state").json()
            == before
        )
        assert (
            client.post(path, json={"planning_horizon_minutes": 45}).status_code == 422
        )
        assert (
            client.post(
                path.replace("extreme-heat-grid-failure", "missing"), json={}
            ).status_code
            == 404
        )


def test_risk_cutoff_is_inclusive_and_never_uses_future_status(snapshot):
    from app.services.risk import rank_risk

    cutoff = next(
        row.risk_score
        for row in rank_risk(snapshot).nodes
        if row.node_id == "hospital-downtown"
    )
    included = build_optimization_input(snapshot, high_risk_threshold=cutoff)
    excluded = build_optimization_input(snapshot, high_risk_threshold=cutoff + 0.01)
    assert any(
        a.target_node_id == "hospital-downtown"
        for a in included.candidate_interventions
    )
    assert not any(
        a.target_node_id == "hospital-downtown"
        for a in excluded.candidate_interventions
    )
    # This intersection fails later in the baseline, but cannot be repaired now.
    assert not any(
        a.target_node_id == "intersection-santa-clara-market"
        for a in included.candidate_interventions
    )


def test_candidates_are_feasible_alternatives_and_order_is_stable(snapshot):
    from app.models.optimization import OptimizationInput
    from app.services.simulation import run_simulation

    result = build_optimization_input(snapshot, high_risk_threshold=0.0)
    assert result.candidate_interventions
    for action in result.candidate_interventions:
        simulated = run_simulation(snapshot, [action])
        assert any(
            e.kind.value == "INTERVENTION_COMPLETED" and e.intervention_id == action.id
            for e in simulated.events
        )
        assert action.start_time == snapshot.simulation_time
    snapshot.nodes.reverse()
    assert (
        build_optimization_input(
            snapshot, high_risk_threshold=0.0
        ).candidate_interventions
        == result.candidate_interventions
    )
    assert OptimizationInput.model_validate_json(result.model_dump_json()) == result
    result.current_city_state.nodes[0].population_served = 0
    result.resource_inventory.electrical_crews = 0
    assert snapshot.nodes[-1].population_served != 0
    assert snapshot.resource_inventory.electrical_crews > 0


def test_failed_facilities_do_not_receive_generators_or_fuel(snapshot):
    node = next(n for n in snapshot.nodes if n.id == "hospital-downtown")
    node.status = NodeStatus.FAILED
    result = build_optimization_input(snapshot, high_risk_threshold=0.0)
    assert not any(a.target_node_id == node.id for a in result.candidate_interventions)


def test_short_scenario_rejects_long_horizon(snapshot):
    snapshot.duration_minutes = 30
    with pytest.raises(ValueError, match="duration"):
        build_optimization_input(snapshot)
    assert build_optimization_input(snapshot, planning_horizon_minutes=30)


@pytest.mark.parametrize("invalid", ["nodes", "edges", "events", "scenario"])
def test_api_rejects_invalid_snapshot_context(snapshot, invalid):
    if invalid == "nodes":
        snapshot.nodes.append(snapshot.nodes[0].model_copy(deep=True))
    elif invalid == "edges":
        snapshot.nodes.pop()
    elif invalid == "events":
        snapshot.event_history[0].node_id = "missing"
    else:
        snapshot.scenario_id = "another-scenario"
    with TestClient(app) as client:
        response = client.post(
            "/api/scenarios/extreme-heat-grid-failure/optimization/input",
            json={"current_city_state": snapshot.model_dump(mode="json")},
        )
    assert response.status_code == 422


def test_api_preserves_objective_preferences():
    weights = {
        "risk_reduction": 2.0,
        "population_protection": 0.0,
        "critical_facility_protection": 4.0,
    }
    with TestClient(app) as client:
        path = "/api/scenarios/extreme-heat-grid-failure/optimization/input"
        response = client.post(path, json={"objective_weights": weights})
        assert response.status_code == 200
        assert response.json()["objective_weights"] == weights
        assert client.post(path, json={"high_risk_threshold": 101}).status_code == 422
        assert (
            client.post(
                path, json={"objective_weights": {"risk_reduction": -1}}
            ).status_code
            == 422
        )
