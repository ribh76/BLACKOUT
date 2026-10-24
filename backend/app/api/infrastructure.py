"""Infrastructure snapshot and node lookup endpoints."""

from typing import Annotated

import networkx as nx
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.models.city import CityData
from app.models.dependency import DownstreamImpact
from app.models.infrastructure import InfrastructureNode, InfrastructureType, NodeStatus
from app.schemas.infrastructure import (
    InfrastructureCascadeResponse,
    InfrastructureDependenciesResponse,
    InfrastructureSnapshotResponse,
)
from app.services.dependency_queries import (
    get_dependencies,
    get_dependency_edge,
    get_dependents,
    get_downstream_impact,
    get_downstream_nodes,
    get_downstream_tree,
    get_upstream_nodes,
)
from app.services.infrastructure import get_city_snapshot, get_node, list_nodes

router = APIRouter(prefix="/infrastructure", tags=["infrastructure"])


def city_data(request: Request) -> CityData:
    return request.app.state.city_data


def dependency_graph(request: Request) -> nx.DiGraph:
    return request.app.state.dependency_graph


def require_graph_node(graph: nx.DiGraph, node_id: str) -> None:
    if node_id not in graph:
        raise HTTPException(
            status_code=404, detail=f"Infrastructure node {node_id!r} not found"
        )


@router.get("", response_model=InfrastructureSnapshotResponse)
def infrastructure_snapshot(
    city: Annotated[CityData, Depends(city_data)],
    node_type: Annotated[InfrastructureType | None, Query(alias="type")] = None,
    status: NodeStatus | None = None,
) -> InfrastructureSnapshotResponse:
    snapshot = get_city_snapshot(city)
    nodes = list_nodes(snapshot, node_type=node_type, status=status)
    return InfrastructureSnapshotResponse(
        schema_version=snapshot.schema_version,
        city=snapshot.city,
        capacity_units=snapshot.capacity_units,
        data_notice=snapshot.data_notice,
        count=len(nodes),
        nodes=nodes,
    )


@router.get("/node/{node_id}", response_model=InfrastructureNode)
def infrastructure_node(
    node_id: str, city: Annotated[CityData, Depends(city_data)]
) -> InfrastructureNode:
    node = get_node(city, node_id)
    if node is None:
        raise HTTPException(
            status_code=404, detail=f"Infrastructure node {node_id!r} not found"
        )
    return node


@router.get(
    "/{node_id}/dependencies", response_model=InfrastructureDependenciesResponse
)
def infrastructure_dependencies(
    node_id: str, graph: Annotated[nx.DiGraph, Depends(dependency_graph)]
) -> InfrastructureDependenciesResponse:
    require_graph_node(graph, node_id)
    dependencies = get_dependencies(graph, node_id)
    dependents = get_dependents(graph, node_id)
    return InfrastructureDependenciesResponse(
        node_id=node_id,
        dependencies=dependencies,
        dependents=dependents,
        upstream_nodes=get_upstream_nodes(graph, node_id),
        downstream_nodes=get_downstream_nodes(graph, node_id),
        dependency_edges=[
            get_dependency_edge(graph, provider_id, node_id)
            for provider_id in dependencies
        ],
        dependent_edges=[
            get_dependency_edge(graph, node_id, dependent_id)
            for dependent_id in dependents
        ],
    )


@router.get("/{node_id}/impact", response_model=DownstreamImpact)
def infrastructure_impact(
    node_id: str,
    graph: Annotated[nx.DiGraph, Depends(dependency_graph)],
    city: Annotated[CityData, Depends(city_data)],
) -> DownstreamImpact:
    require_graph_node(graph, node_id)
    return get_downstream_impact(graph, city, node_id)


@router.get("/{node_id}/cascade", response_model=InfrastructureCascadeResponse)
def infrastructure_cascade(
    node_id: str,
    graph: Annotated[nx.DiGraph, Depends(dependency_graph)],
    city: Annotated[CityData, Depends(city_data)],
) -> InfrastructureCascadeResponse:
    require_graph_node(graph, node_id)
    return InfrastructureCascadeResponse(
        node_id=node_id,
        provider_edges=[
            get_dependency_edge(graph, provider_id, node_id)
            for provider_id in get_dependencies(graph, node_id)
        ],
        dependent_edges=[
            get_dependency_edge(graph, node_id, dependent_id)
            for dependent_id in get_dependents(graph, node_id)
        ],
        downstream_tree=get_downstream_tree(graph, node_id),
        impact=get_downstream_impact(graph, city, node_id),
    )
