"""Graph membership, direction, and edge validation."""

import networkx as nx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.dependency import DependencyEdge
from app.services.city_data import load_city
from app.services.dependency_data import load_dependencies
from app.services.dependency_graph import (
    DependencyGraphError,
    add_dependency,
    build_dependency_graph,
)


def test_graph_contains_every_city_asset_by_id() -> None:
    city = load_city()

    graph = build_dependency_graph(city)

    assert isinstance(graph, nx.DiGraph)
    assert set(graph.nodes) == {node.id for node in city.nodes}
    assert graph.number_of_nodes() == 36
    assert graph.number_of_edges() == 0
    assert graph.graph["edge_semantics"] == "provider -> dependent"


def test_application_builds_graph_at_startup() -> None:
    with TestClient(app):
        assert set(app.state.dependency_graph.nodes) == {
            node.id for node in app.state.city_data.nodes
        }
        assert app.state.dependency_graph.number_of_edges() == 49


def sample_edge(provider_id: str, dependent_id: str) -> DependencyEdge:
    return DependencyEdge(
        provider_id=provider_id,
        dependent_id=dependent_id,
        dependency_type="POWER",
        weight=0.9,
        failure_delay_minutes=15,
        restoration_requirement="SOURCE_RESTORED",
        requirement="CRITICAL",
    )


def test_edges_point_from_provider_to_dependent() -> None:
    city = load_city()
    graph = build_dependency_graph(
        city,
        [
            sample_edge("substation-03", "hospital-downtown"),
            sample_edge("substation-03", "intersection-santa-clara-market"),
        ],
    )

    assert set(graph.successors("substation-03")) == {
        "hospital-downtown",
        "intersection-santa-clara-market",
    }
    assert set(graph.predecessors("hospital-downtown")) == {"substation-03"}
    assert not graph.has_edge("hospital-downtown", "substation-03")
    assert graph.edges["substation-03", "hospital-downtown"] == {
        "dependency_type": "POWER",
        "weight": 0.9,
        "failure_delay_minutes": 15,
        "restoration_requirement": "SOURCE_RESTORED",
        "requirement": "CRITICAL",
    }


@pytest.mark.parametrize(
    ("provider_id", "dependent_id", "error"),
    [
        ("missing", "hospital-downtown", "Unknown provider node ID"),
        ("substation-03", "missing", "Unknown dependent node ID"),
    ],
)
def test_rejects_unknown_edges(provider_id: str, dependent_id: str, error: str) -> None:
    graph = build_dependency_graph(load_city())

    with pytest.raises((DependencyGraphError, ValueError), match=error):
        add_dependency(graph, sample_edge(provider_id, dependent_id))

    assert graph.number_of_nodes() == 36
    assert graph.number_of_edges() == 0


def test_rejects_self_referential_edge() -> None:
    with pytest.raises(ValueError, match="provider_id and dependent_id must differ"):
        sample_edge("substation-03", "substation-03")


def test_seeded_graph_has_direct_and_traffic_mediated_hospital_paths() -> None:
    city = load_city()
    graph = build_dependency_graph(city, load_dependencies(city).edges)

    assert ["substation-03", "hospital-downtown"] in list(
        nx.all_simple_paths(graph, "substation-03", "hospital-downtown")
    )
    assert [
        "substation-03",
        "intersection-santa-clara-market",
        "hospital-downtown",
    ] in list(nx.all_simple_paths(graph, "substation-03", "hospital-downtown"))
    assert [
        "substation-01",
        "intersection-alum-rock-capitol",
        "emergency-route-east",
        "hospital-downtown",
    ] in list(nx.all_simple_paths(graph, "substation-01", "hospital-downtown"))
    assert all(
        graph.in_degree(node.id) > 0
        for node in city.nodes
        if node.type.value != "SUBSTATION"
    )


def test_seeded_graph_connects_power_supply_and_access_dependencies() -> None:
    city = load_city()
    graph = build_dependency_graph(city, load_dependencies(city).edges)

    assert (
        graph.edges["substation-03", "hospital-downtown"]["dependency_type"] == "POWER"
    )
    assert (
        graph.edges["intersection-santa-clara-market", "hospital-downtown"][
            "dependency_type"
        ]
        == "ACCESS"
    )
    assert (
        graph.edges["warehouse-north", "hospital-downtown"]["dependency_type"]
        == "SUPPLY"
    )
    assert graph.edges["substation-03", "shelter-downtown"]["requirement"] == "OPTIONAL"
