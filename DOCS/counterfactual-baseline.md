# Counterfactual baseline

`POST /api/scenarios/{scenario_id}/counterfactual/baseline` captures the
scenario's pristine city state before initial events, applies those events to a
separate T+0 copy, and runs the fixed simulator with an empty intervention list.
The request does not change the live scenario state. Each call creates a new
durable baseline record and returns its ID.

The record contains the versioned scenario, pristine state, initial state,
complete T+0 through T+120 states and events, final node states, final metrics,
and per-tick risk rankings. Its `mode` is `NO_INTERVENTION`. The engine source
fingerprint and SHA-256 input/output digests support later comparison and
integrity checks. Retrieve an existing record with
`GET /api/scenarios/{scenario_id}/counterfactual/baseline/{run_id}`.

Records use `backend/data/counterfactual_runs.sqlite3` by default. Set
`BLACKOUT_COUNTERFACTUAL_DB` to choose another database path. This captures the
first two steps of Phase 10; response-run replay and before/after comparison
will use the saved baseline in the next step.
