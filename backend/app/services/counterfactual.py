"""Build and retain a full no-intervention scenario replay."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.models.counterfactual import BaselineRunRecord, ComparisonRunRecord
from app.models.optimization import OptimizationPlan
from app.models.scenario import CityState, ResourceInventory, Scenario
from app.services.counterfactual_metrics import compare_results
from app.services.interventions import validate_intervention_plan
from app.services.optimization_history import digest, engine_fingerprint
from app.services.risk import rank_risk
from app.services.scenarios import ScenarioStore, apply_initial_events
from app.services.simulation import run_simulation

DEFAULT_BASELINE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "counterfactual_runs.sqlite3"
)


class BaselineRunStore:
    def __init__(self, path: Path):
        self.path = path
        self.engine_fingerprint = engine_fingerprint()
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS baseline_runs "
                "(run_id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, "
                "recorded_at TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS comparison_runs "
                "(comparison_id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, "
                "recorded_at TEXT NOT NULL, payload TEXT NOT NULL)"
            )

    def save_baseline(self, store: ScenarioStore) -> BaselineRunRecord:
        scenario: Scenario = store.scenario
        pristine = store.pristine_scenario_state()
        initial = apply_initial_events(pristine, scenario)
        result = run_simulation(initial, interventions=[])
        result.risk_rankings = {
            state.elapsed_minutes: rank_risk(state.city_state)
            for state in result.states
        }
        record = BaselineRunRecord(
            run_id=str(uuid4()),
            recorded_at=datetime.now(UTC),
            scenario=scenario,
            pristine_state=pristine,
            initial_state=initial,
            result=result,
            engine_fingerprint=self.engine_fingerprint,
            input_sha256=digest(
                {
                    "scenario": scenario.model_dump(mode="json"),
                    "pristine_state": pristine.model_dump(mode="json"),
                    "mode": "NO_INTERVENTION",
                }
            ),
            output_sha256=digest(result.model_dump(mode="json")),
        )
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO baseline_runs VALUES (?, ?, ?, ?)",
                (
                    record.run_id,
                    scenario.id,
                    record.recorded_at.isoformat(),
                    record.model_dump_json(),
                ),
            )
        return record

    def get(self, scenario_id: str, run_id: str) -> BaselineRunRecord | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT payload FROM baseline_runs "
                "WHERE scenario_id = ? AND run_id = ?",
                (scenario_id, run_id),
            ).fetchone()
        if row is None:
            return None
        record = BaselineRunRecord.model_validate_json(row[0])
        expected_input = digest(
            {
                "scenario": record.scenario.model_dump(mode="json"),
                "pristine_state": record.pristine_state.model_dump(mode="json"),
                "mode": record.mode,
            }
        )
        if (
            record.input_sha256 != expected_input
            or record.output_sha256 != digest(record.result.model_dump(mode="json"))
            or record.initial_state
            != apply_initial_events(record.pristine_state, record.scenario)
            or not record.result.states
            or record.result.states[0].city_state != record.initial_state
            or record.scenario.id != scenario_id
        ):
            raise ValueError("Baseline record integrity check failed")
        return record

    def save_comparison(
        self,
        baseline: BaselineRunRecord,
        plan: OptimizationPlan,
        *,
        optimization_run_id: str | None = None,
    ) -> ComparisonRunRecord:
        """Replay only after proving a fresh T+0 clone equals the baseline input."""

        response_initial = self.verified_response_initial_state(baseline)
        if plan.assessment.optimization_input.current_city_state != response_initial:
            raise ValueError("Optimization plan targets a different initial snapshot")
        actions = validate_intervention_plan(
            response_initial,
            [item.intervention for item in plan.selected_candidates],
        )
        resources_used = ResourceInventory(
            **{
                resource: sum(
                    getattr(action.resource_costs, resource) for action in actions
                )
                for resource in response_initial.resource_inventory.model_dump()
            }
        )
        if resources_used != plan.resource_utilization:
            raise ValueError(
                "Plan resource utilization does not match selected actions"
            )
        response = run_simulation(response_initial.model_copy(deep=True), actions)
        response.risk_rankings = {
            state.elapsed_minutes: rank_risk(state.city_state)
            for state in response.states
        }
        summary = compare_results(baseline.result, response, resources_used)
        input_payload = {
            "baseline_run_id": baseline.run_id,
            "baseline_input_sha256": baseline.input_sha256,
            "baseline_output_sha256": baseline.output_sha256,
            "response_initial_state": response_initial.model_dump(mode="json"),
            "plan": plan.model_dump(mode="json"),
        }
        output_payload = {
            "baseline_result": baseline.result.model_dump(mode="json"),
            "response_result": response.model_dump(mode="json"),
            "summary": summary.model_dump(mode="json"),
        }
        record = ComparisonRunRecord(
            comparison_id=str(uuid4()),
            recorded_at=datetime.now(UTC),
            scenario_id=baseline.scenario.id,
            scenario_schema_version=baseline.scenario.schema_version,
            city_schema_version=baseline.pristine_state.city_schema_version,
            scenario_fingerprint=digest(baseline.scenario.model_dump(mode="json")),
            baseline_engine_fingerprint=baseline.engine_fingerprint,
            response_engine_fingerprint=self.engine_fingerprint,
            baseline_run_id=baseline.run_id,
            optimization_run_id=optimization_run_id,
            plan_source="stored" if optimization_run_id else "generated",
            initial_snapshot_sha256=digest(response_initial.model_dump(mode="json")),
            baseline=baseline,
            response_initial_state=response_initial,
            plan=plan,
            response_result=response,
            summary=summary,
            input_sha256=digest(input_payload),
            output_sha256=digest(output_payload),
        )
        record.record_sha256 = digest(
            record.model_dump(mode="json", exclude={"record_sha256"})
        )
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO comparison_runs VALUES (?, ?, ?, ?)",
                (
                    record.comparison_id,
                    record.scenario_id,
                    record.recorded_at.isoformat(),
                    record.model_dump_json(),
                ),
            )
        return record

    def verified_response_initial_state(self, baseline: BaselineRunRecord) -> CityState:
        """Reset from pristine inputs and prove exact T+0 equivalence."""

        if baseline.engine_fingerprint != self.engine_fingerprint:
            raise ValueError("Baseline engine version differs from the running engine")
        if baseline.scenario.id != baseline.pristine_state.scenario_id:
            raise ValueError("Baseline scenario and pristine state do not match")
        response_initial = apply_initial_events(
            baseline.pristine_state.model_copy(deep=True), baseline.scenario
        )
        if (
            response_initial != baseline.initial_state
            or not baseline.result.states
            or baseline.result.states[0].city_state != response_initial
        ):
            raise ValueError("Response initial snapshot differs from baseline")
        return response_initial

    def get_comparison(
        self, scenario_id: str, comparison_id: str
    ) -> ComparisonRunRecord | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT payload FROM comparison_runs "
                "WHERE scenario_id = ? AND comparison_id = ?",
                (scenario_id, comparison_id),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row[0])
        record = ComparisonRunRecord.model_validate_json(row[0])
        if record.record_sha256 != digest(
            {key: value for key, value in payload.items() if key != "record_sha256"}
        ):
            raise ValueError("Comparison record integrity check failed")
        input_payload = {
            "baseline_run_id": record.baseline_run_id,
            "baseline_input_sha256": record.baseline.input_sha256,
            "baseline_output_sha256": record.baseline.output_sha256,
            "response_initial_state": record.response_initial_state.model_dump(
                mode="json"
            ),
            "plan": record.plan.model_dump(mode="json"),
        }
        output_payload = {
            "baseline_result": record.baseline.result.model_dump(mode="json"),
            "response_result": record.response_result.model_dump(mode="json"),
        }
        if "summary" in payload:
            if record.summary is None:
                raise ValueError("Comparison record summary is missing")
            output_payload["summary"] = record.summary.model_dump(mode="json")
        if (
            record.input_sha256 != digest(input_payload)
            or record.output_sha256 != digest(output_payload)
            or record.initial_snapshot_sha256
            != digest(record.response_initial_state.model_dump(mode="json"))
            or record.baseline_run_id != record.baseline.run_id
            or record.scenario_id != scenario_id
        ):
            raise ValueError("Comparison record integrity check failed")
        if "summary" not in payload:
            record.summary = compare_results(
                record.baseline.result,
                record.response_result,
                record.plan.resource_utilization,
            )
            output_payload["summary"] = record.summary.model_dump(mode="json")
            record.output_sha256 = digest(output_payload)
            record.record_sha256 = digest(
                record.model_dump(mode="json", exclude={"record_sha256"})
            )
            with sqlite3.connect(self.path) as connection:
                connection.execute(
                    "UPDATE comparison_runs SET payload = ? "
                    "WHERE scenario_id = ? AND comparison_id = ? AND payload = ?",
                    (record.model_dump_json(), scenario_id, comparison_id, row[0]),
                )
        return record
