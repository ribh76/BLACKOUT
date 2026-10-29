"""Build and retain a full no-intervention scenario replay."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.models.counterfactual import BaselineRunRecord
from app.models.scenario import Scenario
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
