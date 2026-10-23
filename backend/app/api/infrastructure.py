"""Infrastructure snapshot and node lookup endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.models.city import CityData
from app.models.infrastructure import InfrastructureNode, InfrastructureType, NodeStatus
from app.schemas.infrastructure import InfrastructureSnapshotResponse
from app.services.infrastructure import get_city_snapshot, get_node, list_nodes

router = APIRouter(prefix="/infrastructure", tags=["infrastructure"])


def city_data(request: Request) -> CityData:
    return request.app.state.city_data


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
