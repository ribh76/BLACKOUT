"""HTTP contracts for directed dependency lookup and downstream impact."""

from fastapi.testclient import TestClient

from app.main import app
from app.models.dependency import DependencyEdge, DownstreamImpact
from app.schemas.infrastructure import (
    InfrastructureCascadeResponse,
    InfrastructureDependenciesResponse,
)
from app.services.dependency_graph import add_dependency, build_dependency_graph


def test_dependencies_endpoint_exposes_direct_edges_and_metadata() -> None:
    with TestClient(app) as client:
        response = client.get("/api/infrastructure/hospital-downtown/dependencies")

    assert response.status_code == 200
    data = InfrastructureDependenciesResponse.model_validate_json(response.text)
    assert data.node_id == "hospital-downtown"
    assert data.dependencies == [
        "emergency-route-east",
        "emergency-route-north",
        "intersection-santa-clara-market",
        "substation-03",
        "warehouse-north",
    ]
    assert data.dependents == []
    assert [edge.provider_id for edge in data.dependency_edges] == data.dependencies
    assert data.dependent_edges == []
    power_edge = next(
        edge for edge in data.dependency_edges if edge.provider_id == "substation-03"
    )
    assert power_edge.dependent_id == "hospital-downtown"
    assert power_edge.dependency_type == "POWER"
    assert power_edge.weight == 0.98
    assert power_edge.failure_delay_minutes == 15
    assert power_edge.restoration_requirement == "SOURCE_RESTORED"
    assert power_edge.requirement == "CRITICAL"


def test_dependencies_endpoint_traverses_multi_hop_in_provider_direction() -> None:
    with TestClient(app) as client:
        source = client.get("/api/infrastructure/substation-01/dependencies")
        route = client.get("/api/infrastructure/emergency-route-east/dependencies")
        hospital = client.get("/api/infrastructure/hospital-downtown/dependencies")

    assert source.status_code == route.status_code == hospital.status_code == 200
    source_data = source.json()
    route_data = route.json()
    hospital_data = hospital.json()
    assert "emergency-route-east" not in source_data["dependents"]
    assert "emergency-route-east" in source_data["downstream_nodes"]
    assert "hospital-downtown" in source_data["downstream_nodes"]
    assert "intersection-alum-rock-capitol" in route_data["upstream_nodes"]
    assert "substation-01" in route_data["upstream_nodes"]
    assert "substation-01" in hospital_data["upstream_nodes"]
    assert "substation-01" not in hospital_data["downstream_nodes"]
    assert "hospital-downtown" not in source_data["upstream_nodes"]
    assert [edge["dependent_id"] for edge in source_data["dependent_edges"]] == (
        source_data["dependents"]
    )


def test_impact_endpoint_returns_known_totals_and_empty_leaf() -> None:
    with TestClient(app) as client:
        source = client.get("/api/infrastructure/substation-03/impact")
        leaf = client.get("/api/infrastructure/hospital-west/impact")

    assert source.status_code == leaf.status_code == 200
    data = DownstreamImpact.model_validate_json(source.text)
    assert data.source_id == "substation-03"
    assert data.downstream_node_count == 6
    assert data.affected_population == 17200
    assert data.service_population_exposure == 54900
    assert data.critical_facility_ids == [
        "cooling-center-downtown",
        "hospital-downtown",
        "pharmacy-downtown",
        "shelter-downtown",
    ]
    assert data.critical_facility_count == 4
    assert leaf.json() == {
        "source_id": "hospital-west",
        "downstream_node_ids": [],
        "downstream_node_count": 0,
        "affected_population": 0,
        "service_population_exposure": 0,
        "critical_facility_ids": [],
        "critical_facility_count": 0,
    }


def test_cascade_endpoint_exposes_direct_edges_and_multi_hop_tree() -> None:
    with TestClient(app) as client:
        response = client.get("/api/infrastructure/substation-01/cascade")
        hospital = client.get("/api/infrastructure/hospital-downtown/cascade")
        leaf = client.get("/api/infrastructure/hospital-west/cascade")

    assert response.status_code == leaf.status_code == hospital.status_code == 200
    data = InfrastructureCascadeResponse.model_validate_json(response.text)
    assert data.node_id == "substation-01"
    assert data.provider_edges == []
    assert any(
        edge.dependent_id == "intersection-alum-rock-capitol"
        for edge in data.dependent_edges
    )
    route = next(
        item for item in data.downstream_tree if item.node_id == "emergency-route-east"
    )
    assert route.parent_id == "intersection-alum-rock-capitol"
    assert route.depth == 2
    assert route.edge.dependency_type == "ACCESS"
    assert route.edge.weight == 0.84
    assert route.edge.failure_delay_minutes == 5
    assert len({item.node_id for item in data.downstream_tree}) == len(
        data.downstream_tree
    )
    assert {item.node_id for item in data.downstream_tree} == set(
        data.impact.downstream_node_ids
    )
    assert leaf.json()["downstream_tree"] == []
    assert leaf.json()["dependent_edges"] == []
    power = next(
        edge
        for edge in hospital.json()["provider_edges"]
        if edge["provider_id"] == "substation-03"
    )
    assert power["dependency_type"] == "POWER"
    assert power["weight"] == 0.98
    assert power["failure_delay_minutes"] == 15


def test_graph_endpoints_return_404_for_unknown_node() -> None:
    with TestClient(app) as client:
        dependencies = client.get("/api/infrastructure/does-not-exist/dependencies")
        impact = client.get("/api/infrastructure/does-not-exist/impact")
        cascade = client.get("/api/infrastructure/does-not-exist/cascade")

    for response in [dependencies, impact, cascade]:
        assert response.status_code == 404
        assert response.json() == {
            "detail": "Infrastructure node 'does-not-exist' not found"
        }


def test_cycle_does_not_repeat_source_or_downstream_nodes() -> None:
    with TestClient(app) as client:
        graph = build_dependency_graph(app.state.city_data)
        for provider_id, dependent_id in [
            ("substation-03", "hospital-downtown"),
            ("hospital-downtown", "substation-03"),
        ]:
            add_dependency(
                graph,
                DependencyEdge(
                    provider_id=provider_id,
                    dependent_id=dependent_id,
                    dependency_type="POWER",
                    weight=0.9,
                    failure_delay_minutes=10,
                    restoration_requirement="SOURCE_RESTORED",
                    requirement="CRITICAL",
                ),
            )
        app.state.dependency_graph = graph
        dependencies = client.get("/api/infrastructure/substation-03/dependencies")
        impact = client.get("/api/infrastructure/substation-03/impact")
        cascade = client.get("/api/infrastructure/substation-03/cascade")

    assert dependencies.status_code == impact.status_code == cascade.status_code == 200
    assert dependencies.json()["upstream_nodes"] == ["hospital-downtown"]
    assert dependencies.json()["downstream_nodes"] == ["hospital-downtown"]
    assert impact.json()["downstream_node_ids"] == ["hospital-downtown"]
    assert impact.json()["downstream_node_count"] == 1
    assert impact.json()["critical_facility_count"] == 1
    assert [item["node_id"] for item in cascade.json()["downstream_tree"]] == [
        "hospital-downtown"
    ]
