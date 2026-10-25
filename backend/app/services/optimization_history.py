"""Atomic, durable optimizer records with integrity and source fingerprints."""

import hashlib
import json
import platform
import sqlite3
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from uuid import uuid4

from app.models.optimization import (
    OptimizationPlan,
    OptimizationRunRecord,
    OptimizationRunSummary,
)

DEFAULT_HISTORY_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "optimization_runs.sqlite3"
)


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def engine_fingerprint() -> str:
    root = Path(__file__).resolve().parents[1]
    hashes = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*.py"))
    }
    return digest(hashes)


def runtime_versions() -> dict[str, str]:
    result = {"python": platform.python_version()}
    for package in ("ortools", "pydantic", "networkx"):
        try:
            result[package] = version(package)
        except PackageNotFoundError:
            result[package] = "not-installed"
    return result


def replay_payload(plan: OptimizationPlan) -> dict:
    """Audit identities change on replay; the recommendation must not."""
    return plan.model_dump(mode="json", exclude={"run_id", "recorded_at"})


class OptimizationRunStore:
    def __init__(self, path: Path):
        self.path = path
        self.engine_fingerprint = engine_fingerprint()
        self.runtime_versions = runtime_versions()
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS optimization_runs "
                "(run_id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL, "
                "recorded_at TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS optimization_runs_scenario_time "
                "ON optimization_runs(scenario_id, recorded_at)"
            )

    def save(
        self, plan: OptimizationPlan, replay_of: str | None = None
    ) -> OptimizationRunRecord:
        saved = plan.model_copy(deep=True)
        saved.run_id = str(uuid4())
        saved.recorded_at = datetime.now(UTC)
        optimization_input = saved.assessment.optimization_input.model_dump(mode="json")
        record = OptimizationRunRecord(
            run_id=saved.run_id,
            recorded_at=saved.recorded_at,
            replay_of=replay_of,
            engine_fingerprint=self.engine_fingerprint,
            runtime_versions=self.runtime_versions.copy(),
            input_sha256=digest(
                {
                    "optimization_input": optimization_input,
                    "method": saved.method_requested,
                }
            ),
            output_sha256=digest(saved.model_dump(mode="json")),
            plan=saved,
        )
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT INTO optimization_runs VALUES (?, ?, ?, ?)",
                (
                    record.run_id,
                    saved.assessment.optimization_input.current_city_state.scenario_id,
                    record.recorded_at.isoformat(),
                    record.model_dump_json(),
                ),
            )
        return record

    def get(self, scenario_id: str, run_id: str) -> OptimizationRunRecord | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute(
                "SELECT payload FROM optimization_runs "
                "WHERE scenario_id = ? AND run_id = ?",
                (scenario_id, run_id),
            ).fetchone()
        if row is None:
            return None
        record = OptimizationRunRecord.model_validate_json(row[0])
        optimization_input = record.plan.assessment.optimization_input.model_dump(
            mode="json"
        )
        expected_input = digest(
            {
                "optimization_input": optimization_input,
                "method": record.plan.method_requested,
            }
        )
        if record.input_sha256 != expected_input or record.output_sha256 != digest(
            record.plan.model_dump(mode="json")
        ):
            raise ValueError("Optimizer record integrity check failed")
        return record

    def list(self, scenario_id: str, limit: int = 20) -> list[OptimizationRunSummary]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute(
                "SELECT payload FROM optimization_runs WHERE scenario_id = ? "
                "ORDER BY recorded_at DESC, run_id DESC LIMIT ?",
                (scenario_id, limit),
            ).fetchall()
        records = [OptimizationRunRecord.model_validate_json(row[0]) for row in rows]
        return [
            OptimizationRunSummary(
                run_id=r.run_id,
                recorded_at=r.recorded_at,
                method_used=r.plan.method_used,
                selected_action_count=len(r.plan.selected_candidates),
            )
            for r in records
        ]
