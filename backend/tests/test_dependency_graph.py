"""Graph membership, direction, and edge validation."""

import networkx as nx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.city_data import load_city
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


def test_edges_point_from_provider_to_dependent() -> None:
    city = load_city()
    graph = build_dependency_graph(
        city,
        [
            ("substation-03", "hospital-downtown"),
            ("substation-03", "intersection-santa-clara-market"),
        ],
    )

    assert set(graph.successors("substation-03")) == {
        "hospital-downtown",
        "intersection-santa-clara-market",
    }
    assert set(graph.predecessors("hospital-downtown")) == {"substation-03"}
    assert not graph.has_edge("hospital-downtown", "substation-03")


@pytest.mark.parametrize(
    ("provider_id", "dependent_id", "error"),
    [
        ("missing", "hospital-downtown", "Unknown provider node ID"),
        ("substation-03", "missing", "Unknown dependent node ID"),
        ("substation-03", "substation-03", "cannot depend on itself"),
    ],
)
def test_rejects_unknown_or_self_referential_edges(
    provider_id: str, dependent_id: str, error: str
) -> None:
    graph = build_dependency_graph(load_city())

    with pytest.raises(DependencyGraphError, match=error):
        add_dependency(graph, provider_id, dependent_id)

    assert graph.number_of_nodes() == 36
    assert graph.number_of_edges() == 0
