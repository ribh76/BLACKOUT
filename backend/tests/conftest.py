"""Keep API-created optimization records isolated from developer history."""

import pytest


@pytest.fixture(autouse=True)
def isolate_optimization_history(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "BLACKOUT_OPTIMIZATION_DB", str(tmp_path / "optimization.sqlite3")
    )
