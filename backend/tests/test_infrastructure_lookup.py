"""Service and HTTP contracts for infrastructure lookup."""

from fastapi.testclient import TestClient

from app.main import app
from app.models.infrastructure import InfrastructureType, NodeStatus
from app.schemas.infrastructure import InfrastructureSnapshotResponse
from app.services.city_data import load_city
from app.services.infrastructure import get_city_snapshot, get_node, list_nodes


def test_service_lookups_return_nodes_and_independent_snapshot() -> None:
    city = load_city()

    assert get_node(city, "substation-03").name == "Downtown Grid Hub"
    assert get_node(city, "unknown-id") is None
    hospitals = list_nodes(city, node_type=InfrastructureType.HOSPITAL)
    assert len(hospitals) == 3
    assert {node.type for node in hospitals} == {InfrastructureType.HOSPITAL}

    snapshot = get_city_snapshot(city)
    assert len(snapshot.nodes) == 36
    snapshot.nodes[0].name = "Changed outside the city"
    assert city.nodes[0].name != snapshot.nodes[0].name


def test_service_filters_by_status_and_combines_filters() -> None:
    city = load_city()
    city.nodes[4].status = NodeStatus.DEGRADED

    assert [node.id for node in list_nodes(city, status=NodeStatus.DEGRADED)] == [
        "hospital-downtown"
    ]
    assert [
        node.id
        for node in list_nodes(
            city, node_type=InfrastructureType.HOSPITAL, status=NodeStatus.DEGRADED
        )
    ] == ["hospital-downtown"]
    assert (
        list_nodes(
            city,
            node_type=InfrastructureType.SUBSTATION,
            status=NodeStatus.FAILED,
        )
        == []
    )

    node = get_node(city, "hospital-downtown")
    node.status = NodeStatus.FAILED
    assert city.nodes[4].status is NodeStatus.DEGRADED


def test_collection_endpoint_returns_serializable_full_snapshot() -> None:
    with TestClient(app) as client:
        response = client.get("/api/infrastructure")

    assert response.status_code == 200
    data = response.json()
    assert data["schema_version"] == 1
    assert data["city"] == "San Jose, CA (simulated)"
    assert data["count"] == 36
    assert len(data["nodes"]) == data["count"]
    assert data["capacity_units"]["HOSPITAL"] == "occupied beds"
    assert data["nodes"][0]["coordinates"] == {
        "latitude": 37.3738,
        "longitude": -121.8716,
    }
    assert InfrastructureSnapshotResponse.model_validate_json(response.text).count == 36


def test_collection_endpoint_filters_type_and_status() -> None:
    with TestClient(app) as client:
        hospitals = client.get("/api/infrastructure", params={"type": "HOSPITAL"})
        operational = client.get(
            "/api/infrastructure",
            params={"type": "HOSPITAL", "status": "OPERATIONAL"},
        )
        failed = client.get("/api/infrastructure", params={"status": "FAILED"})
        invalid = client.get("/api/infrastructure", params={"type": "POWER_PLANT"})
        invalid_status = client.get("/api/infrastructure", params={"status": "DOWN"})

    assert hospitals.status_code == 200
    assert hospitals.json()["count"] == 3
    assert {node["type"] for node in hospitals.json()["nodes"]} == {"HOSPITAL"}
    assert operational.json()["nodes"] == hospitals.json()["nodes"]
    assert failed.json()["count"] == 0
    assert failed.json()["nodes"] == []
    assert invalid.status_code == 422
    assert invalid_status.status_code == 422


def test_node_endpoint_returns_node_or_404() -> None:
    with TestClient(app) as client:
        found = client.get("/api/infrastructure/node/substation-03")
        missing = client.get("/api/infrastructure/node/no-such-node")

    assert found.status_code == 200
    assert found.json()["id"] == "substation-03"
    assert found.json()["status"] == "OPERATIONAL"
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Infrastructure node 'no-such-node' not found"}
