"""Read-only lookups over a validated city snapshot."""

from app.models.city import CityData
from app.models.infrastructure import InfrastructureNode, InfrastructureType, NodeStatus


def get_node(city: CityData, node_id: str) -> InfrastructureNode | None:
    """Return one independent node copy, or None when its ID is unknown."""

    for node in city.nodes:
        if node.id == node_id:
            return node.model_copy(deep=True)
    return None


def list_nodes(
    city: CityData,
    *,
    node_type: InfrastructureType | None = None,
    status: NodeStatus | None = None,
) -> list[InfrastructureNode]:
    """Filter nodes by exact type and status; omitted filters match all."""

    return [
        node.model_copy(deep=True)
        for node in city.nodes
        if (node_type is None or node.type is node_type)
        and (status is None or node.status is status)
    ]


def get_city_snapshot(city: CityData) -> CityData:
    """Return the full city as an independent snapshot."""

    return city.model_copy(deep=True)
