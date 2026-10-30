"""Response replay shares the baseline input and respects finite inventory."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.counterfactual import ComparisonRunRecord
from app.models.intervention import InterventionType
from app.models.optimization import RankedAction
from app.services.interventions import (
    InterventionError,
    propose_intervention,
    validate_intervention_plan,
)
from app.services.optimization import build_optimization_input
from app.services.optimization_history import digest
from app.services.optimization_planner import plan_response
from app.services.simulation import run_simulation

ROOT = "/api/scenarios/extreme-heat-grid-failure"
COMPARISONS = f"{ROOT}/counterfactual/comparisons"


def test_generated_comparison_persists_both_full_runs_and_versions():
    with TestClient(app) as client:
        live_before = client.get(f"{ROOT}/state").json()
        response = client.post(COMPARISONS, json={"method": "heuristic"})
        assert response.status_code == 200, response.text
        record = ComparisonRunRecord.model_validate_json(response.text)
        assert record.baseline.scenario.id == record.scenario_id
        assert record.scenario_schema_version == 1
        assert record.city_schema_version == 1
        assert record.scenario_fingerprint == digest(
            record.baseline.scenario.model_dump(mode="json")
        )
        assert record.baseline_engine_fingerprint == record.response_engine_fingerprint
        assert record.snapshot_equivalent is True
        assert record.response_initial_state == record.baseline.initial_state
        assert (
            record.baseline.result.states[0].city_state == record.response_initial_state
        )
        assert (
            record.plan.assessment.optimization_input.current_city_state
            == record.response_initial_state
        )
        actions = [item.intervention for item in record.plan.selected_candidates]
        validated = validate_intervention_plan(record.response_initial_state, actions)
        assert validated == actions
        assert record.response_result == _with_risk(
            run_simulation(record.response_initial_state, actions)
        )
        assert (
            record.response_result.states[0].city_state.resource_inventory
            == record.plan.remaining_resources
        )
        assert (
            record.summary.baseline.people_affected
            == record.baseline.result.final_metrics.affected_population
        )
        assert (
            record.summary.response.people_affected
            == record.response_result.final_metrics.affected_population
        )
        assert (
            record.summary.improvement.additional_resources_used
            == record.plan.resource_utilization
        )
        assert (
            record.response_result.tick_minutes == record.baseline.result.tick_minutes
        )
        assert record.response_result.states[-1].city_state.simulation_time == (
            record.baseline.result.states[-1].city_state.simulation_time
        )
        assert client.get(f"{ROOT}/state").json() == live_before
        saved = client.get(f"{COMPARISONS}/{record.comparison_id}")
        assert saved.json() == response.json()
    with TestClient(app) as client:
        assert (
            client.get(f"{COMPARISONS}/{record.comparison_id}").json()
            == response.json()
        )


def _with_risk(result):
    from app.services.risk import rank_risk

    result.risk_rankings = {
        state.elapsed_minutes: rank_risk(state.city_state) for state in result.states
    }
    return result


def test_load_existing_baseline_and_optimization_plan():
    with TestClient(app) as client:
        baseline = client.post(f"{ROOT}/counterfactual/baseline").json()
        client.post(f"{ROOT}/start")
        plan = client.post(
            f"{ROOT}/optimization/plan", json={"method": "heuristic"}
        ).json()
        response = client.post(
            COMPARISONS,
            json={
                "baseline_run_id": baseline["run_id"],
                "optimization_run_id": plan["run_id"],
            },
        )
        assert response.status_code == 200, response.text
        record = response.json()
        assert record["baseline_run_id"] == baseline["run_id"]
        assert record["optimization_run_id"] == plan["run_id"]
        assert record["plan_source"] == "stored"
        assert record["plan"] == plan
        assert record["baseline"] == baseline


def test_reject_plan_from_different_snapshot_and_missing_artifacts():
    with TestClient(app) as client:
        plan = client.post(
            f"{ROOT}/optimization/plan", json={"method": "heuristic"}
        ).json()
        baseline = client.post(f"{ROOT}/counterfactual/baseline").json()
        response = client.post(
            COMPARISONS,
            json={
                "baseline_run_id": baseline["run_id"],
                "optimization_run_id": plan["run_id"],
            },
        )
        assert response.status_code == 422
        assert "different initial snapshot" in response.json()["detail"]
        assert client.get(f"{COMPARISONS}/missing").status_code == 404
        assert (
            client.post(COMPARISONS, json={"baseline_run_id": "missing"}).status_code
            == 404
        )
        assert (
            client.post(
                COMPARISONS, json={"optimization_run_id": "missing"}
            ).status_code
            == 404
        )


def test_over_budget_plan_is_rejected_before_response_run():
    with TestClient(app):
        history = app.state.baseline_runs
        baseline = history.save_baseline(app.state.scenario_store)
        initial = baseline.initial_state
        plan = plan_response(build_optimization_input(initial), method="heuristic")
        template = plan.assessment.candidates[0]
        actions = []
        for node in initial.nodes:
            try:
                action = propose_intervention(
                    initial,
                    f"extra:{node.id}",
                    InterventionType.DEPLOY_GENERATOR,
                    node.id,
                    initial.simulation_time,
                )
            except InterventionError:
                continue
            actions.append(action)
            if len(actions) > initial.resource_inventory.mobile_generators:
                break
        assert len(actions) == initial.resource_inventory.mobile_generators + 1
        plan.selected_candidates = [
            RankedAction(
                **template.model_dump(exclude={"intervention"}),
                intervention=action,
                rank=index,
                priority_rank=index,
            )
            for index, action in enumerate(actions, 1)
        ]
        assert len(actions) > initial.resource_inventory.electrical_crews
        with pytest.raises(InterventionError, match="Insufficient electrical_crews"):
            history.save_comparison(baseline, plan)


def test_mismatched_initial_snapshot_is_rejected_before_replay():
    with TestClient(app):
        history = app.state.baseline_runs
        baseline = history.save_baseline(app.state.scenario_store)
        baseline.initial_state.nodes[0].current_load += 1
        with pytest.raises(ValueError, match="initial snapshot differs"):
            history.verified_response_initial_state(baseline)


def test_comparison_record_detects_tampering(tmp_path, monkeypatch):
    path = tmp_path / "comparison.sqlite3"
    monkeypatch.setenv("BLACKOUT_COUNTERFACTUAL_DB", str(path))
    with TestClient(app) as client:
        comparison_id = client.post(COMPARISONS, json={"method": "heuristic"}).json()[
            "comparison_id"
        ]
        with sqlite3.connect(path) as connection:
            payload = json.loads(
                connection.execute(
                    "SELECT payload FROM comparison_runs WHERE comparison_id = ?",
                    (comparison_id,),
                ).fetchone()[0]
            )
            payload["scenario_schema_version"] = 2
            connection.execute(
                "UPDATE comparison_runs SET payload = ? WHERE comparison_id = ?",
                (json.dumps(payload), comparison_id),
            )
        assert client.get(f"{COMPARISONS}/{comparison_id}").status_code == 503


def test_previous_comparison_record_gains_a_saved_summary(tmp_path, monkeypatch):
    path = tmp_path / "comparison.sqlite3"
    monkeypatch.setenv("BLACKOUT_COUNTERFACTUAL_DB", str(path))
    with TestClient(app) as client:
        original = client.post(COMPARISONS, json={"method": "heuristic"}).json()
        comparison_id = original["comparison_id"]
        with sqlite3.connect(path) as connection:
            old = original.copy()
            old.pop("summary")
            old["output_sha256"] = digest(
                {
                    "baseline_result": old["baseline"]["result"],
                    "response_result": old["response_result"],
                }
            )
            old["record_sha256"] = digest(
                {key: value for key, value in old.items() if key != "record_sha256"}
            )
            connection.execute(
                "UPDATE comparison_runs SET payload = ? WHERE comparison_id = ?",
                (json.dumps(old), comparison_id),
            )
        upgraded = client.get(f"{COMPARISONS}/{comparison_id}")
        assert upgraded.status_code == 200, upgraded.text
        assert upgraded.json()["summary"] == original["summary"]
        assert client.get(f"{COMPARISONS}/{comparison_id}").json() == upgraded.json()
        with sqlite3.connect(path) as connection:
            stored = json.loads(
                connection.execute(
                    "SELECT payload FROM comparison_runs WHERE comparison_id = ?",
                    (comparison_id,),
                ).fetchone()[0]
            )
        assert stored["summary"] == original["summary"]
