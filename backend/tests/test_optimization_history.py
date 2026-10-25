"""Optimization plans are recorded durably with reproducible inputs and outputs."""

from fastapi.testclient import TestClient

from app.main import app

ROOT = "/api/scenarios/extreme-heat-grid-failure/optimization"


def test_plan_is_saved_and_survives_application_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("BLACKOUT_OPTIMIZATION_DB", str(tmp_path / "runs.sqlite3"))
    with TestClient(app) as client:
        client.post("/api/scenarios/extreme-heat-grid-failure/start")
        response = client.post(f"{ROOT}/plan", json={"method": "heuristic"})
        assert response.status_code == 200
        plan = response.json()
        assert plan["run_id"]
        saved = client.get(f"{ROOT}/runs/{plan['run_id']}")
        assert saved.status_code == 200
        record = saved.json()
        assert record["plan"] == plan
        assert record["input_sha256"]
        assert record["output_sha256"]
        assert record["engine_fingerprint"]
        assert record["runtime_versions"]["python"]
    with TestClient(app) as client:
        assert client.get(f"{ROOT}/runs/{plan['run_id']}").json() == record
        replay = client.post(f"{ROOT}/runs/{plan['run_id']}/replay")
        assert replay.status_code == 200
        assert replay.json()["matches_original"]
        assert replay.json()["plan"]["run_id"] != plan["run_id"]
        assert (
            client.get(f"{ROOT}/runs").json()[0]["run_id"]
            == replay.json()["plan"]["run_id"]
        )
        assert client.get(f"{ROOT}/runs/missing").status_code == 404


def test_history_is_scoped_and_detects_modified_output(tmp_path, monkeypatch):
    import json
    import sqlite3

    path = tmp_path / "runs.sqlite3"
    monkeypatch.setenv("BLACKOUT_OPTIMIZATION_DB", str(path))
    with TestClient(app) as client:
        plan = client.post(f"{ROOT}/plan", json={"method": "heuristic"}).json()
        with sqlite3.connect(path) as connection:
            row = connection.execute(
                "SELECT payload FROM optimization_runs WHERE run_id = ?",
                (plan["run_id"],),
            ).fetchone()
            payload = json.loads(row[0])
            payload["plan"]["plan_benefit"]["population_benefit"] += 1
            connection.execute(
                "UPDATE optimization_runs SET payload = ? WHERE run_id = ?",
                (json.dumps(payload), plan["run_id"]),
            )
        assert client.get(f"{ROOT}/runs/{plan['run_id']}").status_code == 503
        assert client.get(f"{ROOT}/runs?limit=0").status_code == 422
        assert (
            client.get(
                ROOT.replace("extreme-heat-grid-failure", "unknown") + "/runs"
            ).status_code
            == 404
        )


def test_storage_failure_does_not_return_an_unrecorded_plan(monkeypatch):
    import sqlite3

    from app.services.optimization_history import OptimizationRunStore

    def fail_save(self, plan, replay_of=None):
        raise sqlite3.OperationalError("disk unavailable")

    monkeypatch.setattr(OptimizationRunStore, "save", fail_save)
    with TestClient(app) as client:
        response = client.post(f"{ROOT}/plan", json={"method": "heuristic"})
    assert response.status_code == 503
    assert response.json()["detail"] == "Unable to record optimization run"


def test_parallel_records_remain_distinct_and_keep_startup_fingerprint(
    tmp_path, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor

    import app.services.optimization_history as history_module

    path = tmp_path / "concurrent.sqlite3"
    monkeypatch.setenv("BLACKOUT_OPTIMIZATION_DB", str(path))
    with TestClient(app) as client:
        response = client.post(f"{ROOT}/plan", json={"method": "heuristic"})
        history = app.state.optimization_runs
        record = history.get("extreme-heat-grid-failure", response.json()["run_id"])
        # A source edit during a server lifetime must not relabel the running engine.
        monkeypatch.setattr(
            history_module, "engine_fingerprint", lambda: "changed-on-disk"
        )
        with ThreadPoolExecutor(max_workers=4) as workers:
            records = list(workers.map(lambda _: history.save(record.plan), range(4)))
        assert len({r.run_id for r in records}) == 4
        assert all(r.engine_fingerprint == record.engine_fingerprint for r in records)
        assert len(history.list("extreme-heat-grid-failure")) == 5
        assert all(
            history.get("extreme-heat-grid-failure", r.run_id) == r for r in records
        )
