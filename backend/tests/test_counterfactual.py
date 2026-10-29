"""The recorded baseline begins from pristine inputs and is replayable."""

import json
import sqlite3

from fastapi.testclient import TestClient

from app.main import app
from app.models.counterfactual import BaselineRunRecord
from app.services.risk import rank_risk
from app.services.scenarios import apply_initial_events
from app.services.simulation import run_simulation

PATH = "/api/scenarios/extreme-heat-grid-failure/counterfactual/baseline"


def test_baseline_records_pristine_initial_and_complete_no_action_run(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("BLACKOUT_COUNTERFACTUAL_DB", str(tmp_path / "baseline.sqlite3"))
    with TestClient(app) as client:
        client.post("/api/scenarios/extreme-heat-grid-failure/start")
        response = client.post(PATH)
        assert response.status_code == 200
        record = BaselineRunRecord.model_validate_json(response.text)
        assert record.pristine_state.event_history == []
        assert all(
            node.status.value == "OPERATIONAL" for node in record.pristine_state.nodes
        )
        assert record.initial_state == apply_initial_events(
            record.pristine_state, record.scenario
        )
        assert record.result.states[0].city_state == record.initial_state
        expected = run_simulation(record.initial_state, interventions=[])
        expected.risk_rankings = {
            state.elapsed_minutes: rank_risk(state.city_state)
            for state in expected.states
        }
        assert record.result == expected
        assert [state.elapsed_minutes for state in record.result.states] == [
            0,
            30,
            60,
            90,
            120,
        ]
        assert (
            record.result.final_node_states == record.result.states[-1].city_state.nodes
        )
        assert record.result.final_metrics.failed_infrastructure_count >= 1
        assert all(not state.interventions for state in record.result.states)
        assert client.get(f"{PATH}/{record.run_id}").json() == response.json()
    with TestClient(app) as client:
        assert client.get(f"{PATH}/{record.run_id}").json() == response.json()
        assert client.get(f"{PATH}/missing").status_code == 404


def test_baselines_repeat_from_same_pristine_state_without_mutating_live_scenario():
    with TestClient(app) as client:
        before = client.get("/api/scenarios/extreme-heat-grid-failure/state").json()
        first = client.post(PATH).json()
        second = client.post(PATH).json()
        after = client.get("/api/scenarios/extreme-heat-grid-failure/state").json()
    assert before == after
    assert first["pristine_state"] == second["pristine_state"]
    assert first["initial_state"] == second["initial_state"]
    assert first["result"] == second["result"]
    assert first["run_id"] != second["run_id"]


def test_baseline_storage_failure_does_not_return_unrecorded_result(monkeypatch):
    from app.services.counterfactual import BaselineRunStore

    def fail_save(self, store):
        raise sqlite3.OperationalError("disk unavailable")

    monkeypatch.setattr(BaselineRunStore, "save_baseline", fail_save)
    with TestClient(app) as client:
        assert client.post(PATH).status_code == 503


def test_modified_baseline_record_is_rejected(tmp_path, monkeypatch):
    path = tmp_path / "baseline.sqlite3"
    monkeypatch.setenv("BLACKOUT_COUNTERFACTUAL_DB", str(path))
    with TestClient(app) as client:
        run_id = client.post(PATH).json()["run_id"]
        with sqlite3.connect(path) as connection:
            payload = json.loads(
                connection.execute(
                    "SELECT payload FROM baseline_runs WHERE run_id = ?", (run_id,)
                ).fetchone()[0]
            )
            payload["result"]["final_metrics"]["affected_population"] += 1
            connection.execute(
                "UPDATE baseline_runs SET payload = ? WHERE run_id = ?",
                (json.dumps(payload), run_id),
            )
        assert client.get(f"{PATH}/{run_id}").status_code == 503
