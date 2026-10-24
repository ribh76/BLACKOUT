"""Export fresh API topology and simulator states for the frontend contract test."""

import json

from fastapi.testclient import TestClient

from app.main import app
from app.models.scenario import CityState
from app.services.simulation import run_simulation


def main() -> None:
    with TestClient(app) as client:
        response = client.post("/api/scenarios/extreme-heat-grid-failure/start")
        response.raise_for_status()
        snapshot = CityState.model_validate_json(response.text)
        simulation = run_simulation(snapshot)
        cascades = {}
        for node in snapshot.nodes:
            response = client.get(f"/api/infrastructure/{node.id}/cascade")
            response.raise_for_status()
            cascades[node.id] = response.json()
        print(
            json.dumps(
                {
                    "edges": [
                        edge.model_dump(mode="json")
                        for edge in snapshot.dependency_edges
                    ],
                    "cascades": cascades,
                    "states": [
                        {
                            "nodes": [
                                node.model_dump(mode="json")
                                for node in state.city_state.nodes
                            ],
                            "events": [
                                event.model_dump(mode="json")
                                for event in simulation.events
                                if event.elapsed_minutes <= state.elapsed_minutes
                            ],
                        }
                        for state in simulation.states
                    ],
                }
            )
        )


if __name__ == "__main__":
    main()
