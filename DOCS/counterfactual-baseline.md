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
`BLACKOUT_COUNTERFACTUAL_DB` to choose another database path.

`POST /api/scenarios/{scenario_id}/counterfactual/comparisons` creates a shared
comparison record. Send `{}` to generate both the baseline and a recommended
plan, or supply `baseline_run_id` and/or `optimization_run_id` to reuse saved
records. `method` selects `auto`, `heuristic`, or `ortools` when a plan is
generated. A loaded plan must target the baseline's exact T+0 state.

Before response simulation, the server rebuilds T+0 from the saved pristine
state, checks exact snapshot equivalence, and validates every selected action
against its canonical definition and aggregate inventory. It then simulates a
deep copy with those actions. The response and baseline use the same scenario
conditions, fixed horizon, and engine fingerprint. The record stores both
complete results, the plan, scenario and city schema versions, a scenario content
fingerprint, source hashes, and a shared `comparison_id`. Retrieve it with
`GET /api/scenarios/{scenario_id}/counterfactual/comparisons/{comparison_id}`.

The saved `summary` compares six outcomes. Critical failures count FAILED
critical facilities at the final tick; affected people come from the simulator's
final neighborhood count. Hospital downtime is the sum of minutes that each
hospital spends CRITICAL or FAILED over the intervals between ticks. System
risk is the sum of final 0–100 node risk scores, as used by the optimizer.
Recovery time is the first tick when every node is OPERATIONAL and remains so
through the horizon; it is `null` when recovery is not observed. Resource
utilization lists reserved units for each inventory type, zero for the baseline
and the sum of selected action costs for the response. The `improvement` fields
subtract response harm from baseline harm, so a positive number means less harm.
When either run has no observed recovery, recovery-time improvement is `null`.
