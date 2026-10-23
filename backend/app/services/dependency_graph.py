"""Build the directed graph of infrastructure dependencies.

An edge A -> B means B depends on A. If A degrades or fails, B may be
affected; the reverse direction does not follow from that edge.
"""

from collections.abc import Iterable

import networkx as nx

from app.models.city import CityData
from app.models.dependency import DependencyEdge


class DependencyGraphError(ValueError):
    """A dependency references an invalid asset or itself."""


def add_dependency(graph: nx.DiGraph, edge: DependencyEdge) -> None:
    """Add one validated provider -> dependent edge with its metadata."""

    provider_id = edge.provider_id
    dependent_id = edge.dependent_id
    if provider_id not in graph:
        raise DependencyGraphError(f"Unknown provider node ID: {provider_id!r}")
    if dependent_id not in graph:
        raise DependencyGraphError(f"Unknown dependent node ID: {dependent_id!r}")
    if provider_id == dependent_id:
        raise DependencyGraphError(f"Node {provider_id!r} cannot depend on itself")
    if graph.has_edge(provider_id, dependent_id):
        raise DependencyGraphError(
            f"Duplicate dependency: {provider_id!r} -> {dependent_id!r}"
        )

    graph.add_edge(
        provider_id,
        dependent_id,
        **edge.model_dump(mode="json", exclude={"provider_id", "dependent_id"}),
    )


def build_dependency_graph(
    city: CityData, dependencies: Iterable[DependencyEdge] = ()
) -> nx.DiGraph:
    """Represent every city asset by ID, then add provider -> dependent edges."""

    graph = nx.DiGraph()
    graph.graph["edge_semantics"] = "provider -> dependent"
    graph.add_nodes_from(node.id for node in city.nodes)

    for edge in dependencies:
        add_dependency(graph, edge)

    return graph
