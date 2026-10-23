"""Build the directed graph of infrastructure dependencies.

An edge A -> B means B depends on A. If A degrades or fails, B may be
affected; the reverse direction does not follow from that edge.
"""

from collections.abc import Iterable

import networkx as nx

from app.models.city import CityData


class DependencyGraphError(ValueError):
    """A dependency references an invalid asset or itself."""


def add_dependency(graph: nx.DiGraph, provider_id: str, dependent_id: str) -> None:
    """Add provider -> dependent without creating undeclared assets."""

    if provider_id not in graph:
        raise DependencyGraphError(f"Unknown provider node ID: {provider_id!r}")
    if dependent_id not in graph:
        raise DependencyGraphError(f"Unknown dependent node ID: {dependent_id!r}")
    if provider_id == dependent_id:
        raise DependencyGraphError(f"Node {provider_id!r} cannot depend on itself")

    graph.add_edge(provider_id, dependent_id)


def build_dependency_graph(
    city: CityData, dependencies: Iterable[tuple[str, str]] = ()
) -> nx.DiGraph:
    """Represent every city asset by ID, then add provider -> dependent edges."""

    graph = nx.DiGraph()
    graph.graph["edge_semantics"] = "provider -> dependent"
    graph.add_nodes_from(node.id for node in city.nodes)

    for provider_id, dependent_id in dependencies:
        add_dependency(graph, provider_id, dependent_id)

    return graph
