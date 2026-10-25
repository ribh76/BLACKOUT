"""Candidate discovery and concrete effects returned through the manual API."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.dependency import DependencyEdge, DependencyType
from app.models.infrastructure import NodeStatus
from app.models.intervention import InterventionType
from app.services.city_data import load_city
from app.services.dependency_data import load_dependencies
from app.services.intervention_candidates import candidate_interventions
from app.services.interventions import propose_intervention
from app.services.scenarios import apply_initial_events, load_scenario, reset_scenario
from app.services.simulation import run_simulation

PATH = "/api/scenarios/extreme-heat-grid-failure"


@pytest.mark.parametrize(
    ("node_id", "action_type"),
    [
        ("substation-03", "REPAIR_SUBSTATION"),
        ("hospital-downtown", "DEPLOY_GENERATOR"),
        ("hospital-downtown", "SEND_FUEL"),
        ("intersection-santa-clara-market", "RESTORE_INTERSECTION"),
        ("neighborhood-downtown", "RELOCATE_POPULATION"),
    ],
)
def test_candidate_estimate_matches_apply_on_a_clone(node_id, action_type):
    with TestClient(app) as client:
        original = client.get(f"{PATH}/state").json()
        response = client.get(f"{PATH}/nodes/{node_id}/interventions")
        assert response.status_code == 200
        candidate = next(
            item
            for item in response.json()["candidates"]
            if item["intervention"]["type"] == action_type
        )
        estimate = candidate["estimated_immediate_effects"]
        assert estimate["execution_status"] == "COMPLETED"
        effects = {effect["node_id"]: effect for effect in estimate["node_effects"]}
        if action_type == "REPAIR_SUBSTATION":
            assert effects["substation-03"]["power_restored"] is True
            assert effects["substation-03"]["after"]["status"] == "OPERATIONAL"
            hospital = effects["hospital-downtown"]
            assert hospital["power_pressure_after"] < hospital["power_pressure_before"]
        if action_type in {"DEPLOY_GENERATOR", "SEND_FUEL"}:
            hospital = effects[node_id]
            added = (
                hospital["backup_duration_minutes_after"]
                - hospital["backup_duration_minutes_before"]
            )
            assert added == pytest.approx(
                120 if action_type == "DEPLOY_GENERATOR" else 60
            )
            assert hospital["power_pressure_after"] < hospital["power_pressure_before"]
            assert hospital["power_restored"] is True
        plan = candidate["intervention"]
        request = [
            {key: plan[key] for key in ("id", "type", "target_node_id", "start_time")}
        ]
        valid = client.post(f"{PATH}/interventions/validate", json=request)
        applied = client.post(f"{PATH}/interventions/apply", json=request)
        assert valid.status_code == applied.status_code == 200
        event = next(
            event
            for event in applied.json()["events"]
            if event["kind"] == "INTERVENTION_COMPLETED"
        )
        assert event["node_effects"] == estimate["node_effects"]
        assert event["time"] == estimate["completion_time"]
        if action_type in {"DEPLOY_GENERATOR", "SEND_FUEL"}:
            baseline = client.post(f"{PATH}/interventions/apply", json=[]).json()
            baseline_hospital = next(
                node
                for node in baseline["states"][2]["city_state"]["nodes"]
                if node["id"] == node_id
            )
            protected_hospital = next(
                node
                for node in applied.json()["states"][2]["city_state"]["nodes"]
                if node["id"] == node_id
            )
            assert baseline_hospital["status"] == "CRITICAL"
            assert protected_hospital["status"] == "DEGRADED"
        expected_inventory = {
            resource: available - plan["resource_costs"][resource]
            for resource, available in original["resource_inventory"].items()
        }
        assert (
            applied.json()["states"][0]["city_state"]["resource_inventory"]
            == expected_inventory
        )
        assert (
            applied.json()["states"][-1]["city_state"]["resource_inventory"]
            == expected_inventory
        )
        assert (
            client.post(f"{PATH}/interventions/apply", json=request).json()
            == applied.json()
        )
        assert client.get(f"{PATH}/state").json() == original


def test_candidates_handle_unknown_and_ineligible_nodes():
    with TestClient(app) as client:
        missing = client.get(f"{PATH}/nodes/missing/interventions")
        warehouse = client.get(f"{PATH}/nodes/warehouse-north/interventions")
    assert missing.status_code == 404
    assert warehouse.status_code == 200
    assert warehouse.json()["candidates"] == []


@pytest.fixture
def route_snapshot():
    city = load_city()
    scenario = load_scenario(city)
    snapshot = apply_initial_events(
        reset_scenario(scenario, city, load_dependencies(city).edges), scenario
    )
    snapshot.temperature_f = 95
    snapshot.grid_load = 0.8
    snapshot.dependency_edges = [
        edge
        for edge in snapshot.dependency_edges
        if (
            edge.provider_id == "intersection-north-first-tasman"
            and edge.dependent_id == "emergency-route-north"
        )
        or (
            edge.provider_id == "emergency-route-north"
            and edge.dependent_id == "hospital-downtown"
        )
    ]
    for node in snapshot.nodes:
        if node.id in {"intersection-north-first-tasman", "emergency-route-north"}:
            node.status = NodeStatus.FAILED
    return snapshot


def test_route_candidates_reopen_access_and_reduce_downstream_pressure(route_snapshot):
    original = route_snapshot.model_dump_json()
    response = candidate_interventions(route_snapshot, "emergency-route-north")
    candidate = response.candidates[0]
    assert candidate.intervention.target_node_id == "intersection-north-first-tasman"
    action = candidate.intervention
    result = run_simulation(route_snapshot, [action])
    completion = next(
        event for event in result.events if event.kind.value == "INTERVENTION_COMPLETED"
    )
    effects = {effect.node_id: effect for effect in completion.node_effects}
    assert effects["emergency-route-north"].route_reopened is True
    assert effects["emergency-route-north"].before.status is NodeStatus.FAILED
    assert effects["emergency-route-north"].after.status is NodeStatus.OPERATIONAL
    assert effects["hospital-downtown"].dependency_pressure_before == pytest.approx(
        0.35
    )
    assert effects["hospital-downtown"].dependency_pressure_after == 0
    assert "emergency-route-north" not in result.states[1].impaired_since_minutes
    assert any(
        event.node_id == "emergency-route-north"
        and event.status is NodeStatus.OPERATIONAL
        for event in result.states[1].city_state.event_history
    )
    assert candidate.estimated_immediate_effects.node_effects == completion.node_effects
    assert route_snapshot.model_dump_json() == original
    # Event records retain completion values even as later snapshots evolve.
    route = next(
        node for node in result.final_node_states if node.id == "emergency-route-north"
    )
    route.status = NodeStatus.FAILED
    assert effects["emergency-route-north"].after.status is NodeStatus.OPERATIONAL


@pytest.mark.parametrize("remaining_blocker", [NodeStatus.DEGRADED, NodeStatus.FAILED])
def test_route_stays_closed_until_all_providers_restore(
    route_snapshot, remaining_blocker
):
    blocker = next(
        node for node in route_snapshot.nodes if node.id == "intersection-story-king"
    )
    blocker.status = remaining_blocker
    route_snapshot.dependency_edges.append(
        DependencyEdge(
            provider_id=blocker.id,
            dependent_id="emergency-route-north",
            dependency_type=DependencyType.ACCESS,
            weight=0.8,
            failure_delay_minutes=0,
            restoration_requirement="ROUTE_REOPENED",
            requirement="CRITICAL",
        )
    )
    action = propose_intervention(
        route_snapshot,
        "traffic",
        InterventionType.RESTORE_INTERSECTION,
        "intersection-north-first-tasman",
        route_snapshot.simulation_time,
    )
    result = run_simulation(route_snapshot, [action])
    route = next(
        node
        for node in result.states[1].city_state.nodes
        if node.id == "emergency-route-north"
    )
    assert route.status is NodeStatus.FAILED
    assert not any(
        effect.route_reopened
        for event in result.events
        for effect in event.node_effects
    )


def test_route_does_not_reopen_while_over_capacity(route_snapshot):
    route = next(
        node for node in route_snapshot.nodes if node.id == "emergency-route-north"
    )
    route.current_load = route.capacity + 1
    candidate = candidate_interventions(route_snapshot, route.id).candidates[0]
    estimate = candidate.estimated_immediate_effects
    assert not any(effect.route_reopened for effect in estimate.node_effects)


def test_combined_traffic_actions_reopen_route_when_last_blocker_clears(route_snapshot):
    blocker = next(
        node for node in route_snapshot.nodes if node.id == "intersection-story-king"
    )
    blocker.status = NodeStatus.FAILED
    route_snapshot.dependency_edges.append(
        DependencyEdge(
            provider_id=blocker.id,
            dependent_id="emergency-route-north",
            dependency_type=DependencyType.ACCESS,
            weight=0.8,
            failure_delay_minutes=0,
            restoration_requirement="ROUTE_REOPENED",
            requirement="CRITICAL",
        )
    )
    plan = [
        propose_intervention(
            route_snapshot,
            f"traffic-{index}",
            InterventionType.RESTORE_INTERSECTION,
            intersection,
            route_snapshot.simulation_time,
        )
        for index, intersection in enumerate(
            [
                "intersection-north-first-tasman",
                "intersection-story-king",
            ]
        )
    ]
    result = run_simulation(route_snapshot, plan)
    assert result.states[0].city_state.resource_inventory.traffic_crews == 0
    completions = [
        event for event in result.events if event.kind.value == "INTERVENTION_COMPLETED"
    ]
    assert not any(effect.route_reopened for effect in completions[0].node_effects)
    assert any(effect.route_reopened for effect in completions[1].node_effects)
    assert completions[1].elapsed_minutes == 30


def test_relocation_removes_exposure_and_adds_the_same_receiving_load(route_snapshot):
    snapshot = route_snapshot
    snapshot.dependency_edges = []
    target = next(node for node in snapshot.nodes if node.id == "neighborhood-downtown")
    target.status = NodeStatus.FAILED
    action = propose_intervention(
        snapshot,
        "relocate",
        InterventionType.RELOCATE_POPULATION,
        target.id,
        snapshot.simulation_time,
    )
    baseline = run_simulation(snapshot)
    result = run_simulation(snapshot, [action])
    completed = next(
        event for event in result.events if event.kind.value == "INTERVENTION_COMPLETED"
    )
    effects = {effect.node_id: effect for effect in completed.node_effects}
    exposed = effects[target.id]
    receiver = effects[completed.receiving_node_id]
    assert exposed.exposed_population_before - exposed.exposed_population_after == 100
    assert receiver.after.current_load - receiver.before.current_load == 100
    assert (
        result.final_metrics.affected_population
        == baseline.final_metrics.affected_population - 100
    )
    assert completed.elapsed_minutes == 90
    assert all(
        not event.node_effects for event in result.events if event.elapsed_minutes < 90
    )


def test_candidates_report_unavailable_resources_without_consuming_them(route_snapshot):
    route_snapshot.resource_inventory.traffic_crews = 0
    before = route_snapshot.model_dump_json()
    response = candidate_interventions(route_snapshot, "emergency-route-north")
    assert response.candidates == []
    assert "Insufficient traffic_crews" in response.unavailable_actions[0].reason
    assert route_snapshot.model_dump_json() == before


def test_explicit_candidate_start_and_invalid_query_times():
    with TestClient(app) as client:
        snapshot = client.get(f"{PATH}/state").json()
        path = f"{PATH}/nodes/intersection-santa-clara-market/interventions"
        earliest = client.get(path).json()["candidates"][0]
        assert earliest["intervention"]["start_time"] != snapshot["simulation_time"]
        now = client.get(path, params={"start_time": snapshot["simulation_time"]})
        assert now.status_code == 200
        assert now.json()["candidates"] == []
        invalid = client.get(path, params={"start_time": "2026-07-15T14:05:00-07:00"})
        naive = client.get(path, params={"start_time": "2026-07-15T14:00:00"})
    assert invalid.status_code == naive.status_code == 422
    assert "30-minute tick" in invalid.json()["detail"]
    assert "timezone" in naive.json()["detail"]


def test_candidates_exclude_actions_forecast_to_fail_at_completion():
    with TestClient(app) as client:
        response = client.get(
            f"{PATH}/nodes/hospital-downtown/interventions",
            params={"start_time": "2026-07-15T15:30:00-07:00"},
        )
    assert response.status_code == 200
    assert all(
        candidate["intervention"]["type"] != "DEPLOY_GENERATOR"
        for candidate in response.json()["candidates"]
    )
    rejected = next(
        action
        for action in response.json()["unavailable_actions"]
        if action["type"] == "DEPLOY_GENERATOR"
    )
    assert "failed before generator installation" in rejected["reason"]


@pytest.mark.parametrize(
    "invalid", ["node", "type", "id", "target", "timing", "budget"]
)
def test_apply_rejects_impossible_plans_without_changing_state(invalid):
    with TestClient(app) as client:
        original = client.get(f"{PATH}/state").json()
        payload = [
            {
                "id": "one",
                "type": "REPAIR_SUBSTATION",
                "target_node_id": "substation-03",
                "start_time": original["simulation_time"],
            }
        ]
        if invalid == "node":
            payload[0]["target_node_id"] = "missing"
        elif invalid == "type":
            payload[0]["target_node_id"] = "hospital-downtown"
        elif invalid == "id":
            payload.append(dict(payload[0]))
        elif invalid == "target":
            payload.append({**payload[0], "id": "two"})
        elif invalid == "timing":
            payload[0]["start_time"] = "2026-07-15T15:30:00-07:00"
        else:
            payload.extend(
                [
                    {**payload[0], "id": "two", "target_node_id": "substation-07"},
                    {
                        **payload[0],
                        "id": "three",
                        "type": "DEPLOY_GENERATOR",
                        "target_node_id": "hospital-downtown",
                    },
                ]
            )
        valid = client.post(f"{PATH}/interventions/validate", json=payload)
        applied = client.post(f"{PATH}/interventions/apply", json=payload)
        assert valid.status_code == applied.status_code == 422
        assert valid.json()["detail"] == applied.json()["detail"]
        assert client.get(f"{PATH}/state").json() == original
