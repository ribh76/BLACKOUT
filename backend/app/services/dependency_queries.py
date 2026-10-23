"""Deterministic traversal, path tracing, and exposure summaries."""

from collections import deque

import networkx as nx
from pydantic import ValidationError

from app.models.city import CityData
from app.models.dependency import DependencyEdge, DependencyPath, DownstreamImpact
from app.models.infrastructure import InfrastructureType
from app.services.dependency_graph import DependencyGraphError

CRITICAL_FACILITY_TYPES = frozenset(
    {
        InfrastructureType.SUBSTATION,
        InfrastructureType.HOSPITAL,
        InfrastructureType.PHARMACY,
        InfrastructureType.SHELTER,
        InfrastructureType.COOLING_CENTER,
    }
)


def _require_node(graph: nx.DiGraph, node_id: str) -> None:
    if node_id not in graph:
        raise DependencyGraphError(f"Unknown infrastructure node ID: {node_id!r}")


def get_dependencies(graph: nx.DiGraph, node_id: str) -> list[str]:
    """Return direct providers that this node depends on."""

    _require_node(graph, node_id)
    return sorted(graph.predecessors(node_id))


def get_dependents(graph: nx.DiGraph, node_id: str) -> list[str]:
    """Return direct consumers that depend on this node."""

    _require_node(graph, node_id)
    return sorted(graph.successors(node_id))


def get_downstream_nodes(graph: nx.DiGraph, node_id: str) -> list[str]:
    """Return all reachable dependents, excluding the source, even in cycles."""

    _require_node(graph, node_id)
    return sorted(nx.descendants(graph, node_id) - {node_id})


def get_upstream_nodes(graph: nx.DiGraph, node_id: str) -> list[str]:
    """Return all providers reachable against edge direction."""

    _require_node(graph, node_id)
    return sorted(nx.ancestors(graph, node_id) - {node_id})


def trace_dependency_path(
    graph: nx.DiGraph, source_id: str, target_id: str
) -> DependencyPath | None:
    """Return the shortest provider-to-dependent path, with sorted-ID tie breaks."""

    _require_node(graph, source_id)
    _require_node(graph, target_id)

    parents: dict[str, str | None] = {source_id: None}
    queue = deque([source_id])
    while queue and target_id not in parents:
        current = queue.popleft()
        for dependent_id in sorted(graph.successors(current)):
            if dependent_id not in parents:
                parents[dependent_id] = current
                queue.append(dependent_id)

    if target_id not in parents:
        return None

    node_ids = [target_id]
    while node_ids[-1] != source_id:
        parent = parents[node_ids[-1]]
        assert parent is not None
        node_ids.append(parent)
    node_ids.reverse()

    edges: list[DependencyEdge] = []
    for provider_id, dependent_id in zip(node_ids, node_ids[1:]):
        metadata = graph.edges[provider_id, dependent_id]
        try:
            edges.append(
                DependencyEdge.model_validate(
                    {
                        "provider_id": provider_id,
                        "dependent_id": dependent_id,
                        **metadata,
                    }
                )
            )
        except ValidationError as exc:
            raise DependencyGraphError(
                f"Invalid metadata on dependency {provider_id!r} -> "
                f"{dependent_id!r}: {exc}"
            ) from exc

    return DependencyPath(
        source_id=source_id,
        target_id=target_id,
        node_ids=node_ids,
        edges=edges,
    )


def get_downstream_impact(
    graph: nx.DiGraph, city: CityData, source_id: str
) -> DownstreamImpact:
    """Count distinct downstream assets and estimate their exposed population."""

    downstream_ids = get_downstream_nodes(graph, source_id)
    city_nodes = {node.id: node for node in city.nodes}
    if source_id not in city_nodes:
        raise DependencyGraphError(
            f"Source node {source_id!r} is absent from city data"
        )
    missing = set(downstream_ids) - city_nodes.keys()
    if missing:
        raise DependencyGraphError(
            f"Graph contains nodes absent from city data: {', '.join(sorted(missing))}"
        )

    downstream = [city_nodes[node_id] for node_id in downstream_ids]
    critical_ids = sorted(
        node.id for node in downstream if node.type in CRITICAL_FACILITY_TYPES
    )
    return DownstreamImpact(
        source_id=source_id,
        downstream_node_ids=downstream_ids,
        downstream_node_count=len(downstream_ids),
        affected_population=sum(
            node.population_served
            for node in downstream
            if node.type is InfrastructureType.NEIGHBORHOOD
        ),
        service_population_exposure=sum(node.population_served for node in downstream),
        critical_facility_ids=critical_ids,
        critical_facility_count=len(critical_ids),
    )
