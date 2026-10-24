"""Risk scoring behavior across graph, status, and scenario inputs."""

from fastapi.testclient import TestClient

from app.main import app
from app.models.infrastructure import NodeStatus
from app.models.risk import NodeRisk, RiskRanking
from app.services.city_data import load_city
from app.services.dependency_data import load_dependencies
from app.services.risk import BASE_CRITICALITY, rank_risk
from app.services.scenarios import ScenarioStore, load_scenario


def snapshot():
    city = load_city()
    store = ScenarioStore(load_scenario(city), city, load_dependencies(city).edges)
    return store.start_scenario()


def scored(state, node_id):
    return next(item for item in rank_risk(state).nodes if item.node_id == node_id)


def test_type_weights_and_score_bounds_on_known_scenario() -> None:
    state = snapshot()
    ranking = rank_risk(state)

    assert (
        BASE_CRITICALITY[
            next(n.type for n in state.nodes if n.id == "hospital-downtown")
        ]
        > BASE_CRITICALITY[
            next(n.type for n in state.nodes if n.id == "warehouse-north")
        ]
    )
    assert ranking.count == len(state.nodes)
    assert all(0 <= item.impact_score <= 100 for item in ranking.nodes)
    assert all(0 <= item.failure_probability <= 1 for item in ranking.nodes)
    assert all(0 <= item.risk_score <= 100 for item in ranking.nodes)
    assert ranking.nodes == sorted(
        ranking.nodes, key=lambda n: (-n.risk_score, n.node_id)
    )
    assert (
        scored(state, "substation-03").risk_score
        > scored(state, "warehouse-north").risk_score
    )
    assert ranking == rank_risk(state)


def test_population_has_diminishing_returns_and_no_single_signal_dominates() -> None:
    state = snapshot()
    state.dependency_edges = []
    target = state.nodes[0]
    target.population_served = 100
    low = scored(state, target.id).impact_score
    target.population_served = 10_000
    medium = scored(state, target.id).impact_score
    target.population_served = 1_000_000
    high = scored(state, target.id).impact_score

    assert low < medium < high
    assert high - medium < medium - low
    assert high - low <= 25.01


def test_direct_and_multi_hop_counts_each_increase_impact() -> None:
    state = snapshot()
    edges = state.dependency_edges
    source = "substation-01"
    state.dependency_edges = [e for e in edges if e.provider_id == "substation-03"]
    none = scored(state, source)
    assert none.direct_dependents == none.downstream_dependents == 0
    assert none.downstream_node_ids == []

    direct_edge = next(
        e
        for e in edges
        if e.provider_id == source
        and e.dependent_id == "intersection-alum-rock-capitol"
    )
    state.dependency_edges.append(direct_edge)
    direct = scored(state, source)
    assert direct.direct_dependents == direct.downstream_dependents == 1
    assert direct.impact_score > none.impact_score

    state.dependency_edges.append(
        next(
            e
            for e in edges
            if e.provider_id == "intersection-alum-rock-capitol"
            and e.dependent_id == "emergency-route-east"
        )
    )
    multi = scored(state, source)
    assert multi.direct_dependents == 1
    assert multi.downstream_dependents == 2
    assert multi.impact_score > direct.impact_score


def test_backup_load_and_vulnerability_follow_the_new_components() -> None:
    state = snapshot()
    node = next(n for n in state.nodes if n.id == "hospital-downtown")
    initial = scored(state, node.id)
    node.backup_remaining = 0
    no_backup = scored(state, node.id)
    assert no_backup.impact_score == initial.impact_score
    assert no_backup.backup_resilience == 0
    assert no_backup.failure_probability > initial.failure_probability

    node.current_load = node.capacity
    node.vulnerability = 1
    stressed = scored(state, node.id)
    assert stressed.impact_score > no_backup.impact_score
    assert stressed.failure_probability > no_backup.failure_probability


def test_weighted_provider_failure_state_changes_dependent_likelihood() -> None:
    state = snapshot()
    target = "hospital-downtown"
    incoming = [e for e in state.dependency_edges if e.dependent_id == target]
    source = next(e for e in incoming if e.provider_id == "substation-03")
    hospital = scored(state, target)
    expected = source.weight / sum(e.weight for e in incoming)
    assert abs(hospital.dependency_degradation - expected) < 0.0001

    provider = next(n for n in state.nodes if n.id == source.provider_id)
    provider.status = NodeStatus.DEGRADED
    degraded = scored(state, target)
    assert degraded.dependency_degradation < hospital.dependency_degradation
    assert degraded.failure_probability < hospital.failure_probability


def test_formula_components_and_operational_priority() -> None:
    from math import exp, log1p

    state = snapshot()
    ranking = rank_risk(state)
    item = next(n for n in ranking.nodes if n.node_id == "substation-03")
    source = next(n for n in state.nodes if n.id == item.node_id)
    max_population = max(n.population_served for n in state.nodes)
    exposure = log1p(source.population_served) / log1p(max_population)
    criticality = 0.7 * BASE_CRITICALITY[source.type] + 0.3 * source.criticality
    impact = (
        0.30 * criticality
        + 0.25 * exposure
        + 0.30 * item.systemic_impact
        + 0.15 * source.vulnerability
    )
    logit = (
        -2.5
        + 1.5 * item.load_stress
        + 2.0 * item.dependency_degradation
        + item.environmental_stress
        - 1.5 * item.backup_resilience
    )
    assert abs(item.impact_score - 100 * impact) < 0.02
    assert abs(item.failure_probability - 1 / (1 + exp(-logit))) < 0.0001
    assert abs(item.risk_score - item.impact_score * item.failure_probability) < 0.02
    assert item.time_to_failure_minutes == 0
    assert all(0 <= n.operational_priority <= 100 for n in ranking.nodes)
    assert max(n.operational_priority for n in ranking.nodes) == 100


def test_risk_api_uses_current_scenario_state_and_node_explanation() -> None:
    scenario_id = "extreme-heat-grid-failure"
    with TestClient(app) as client:
        client.post(f"/api/scenarios/{scenario_id}/reset")
        before = RiskRanking.model_validate_json(
            client.get(f"/api/scenarios/{scenario_id}/risk").text
        )
        client.post(f"/api/scenarios/{scenario_id}/start")
        response = client.get(f"/api/scenarios/{scenario_id}/risk")
        detail = client.get(f"/api/scenarios/{scenario_id}/risk/substation-03")
        missing = client.get(f"/api/scenarios/{scenario_id}/risk/not-a-node")
    assert response.status_code == detail.status_code == 200
    after = RiskRanking.model_validate_json(response.text)
    node = NodeRisk.model_validate_json(detail.text)
    assert node == next(item for item in after.nodes if item.node_id == node.node_id)
    assert node.time_to_failure_minutes == 0
    assert (
        next(
            item for item in before.nodes if item.node_id == node.node_id
        ).time_to_failure_minutes
        > 0
    )
    assert missing.status_code == 404
