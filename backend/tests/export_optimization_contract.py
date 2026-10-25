"""Export fresh API plans for frontend integration and rendering tests."""

import json
import os
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from app.main import app

with TemporaryDirectory() as directory:
    os.environ["BLACKOUT_OPTIMIZATION_DB"] = f"{directory}/runs.sqlite3"
    with TestClient(app) as client:
        root = "/api/scenarios/extreme-heat-grid-failure"
        state = client.post(f"{root}/start").json()
        plan = client.post(f"{root}/optimization/plan", json={}).json()
        empty_state = {
            **state,
            "resource_inventory": {key: 0 for key in state["resource_inventory"]},
        }
        empty = client.post(
            f"{root}/optimization/plan", json={"current_city_state": empty_state}
        ).json()
        print(json.dumps({"state": state, "plan": plan, "empty_plan": empty}))
