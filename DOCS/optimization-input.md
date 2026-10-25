# Resource optimization input

`POST /api/scenarios/{scenario_id}/optimization/input` prepares a reproducible
input for resource allocation. Send `{}` to use the stored **current** city state.
Start the scenario first to include its initial failures. To plan from a displayed
playback snapshot, send that complete `CityState` as `current_city_state`; its
scenario ID must match the URL. This endpoint does not change stored state.

```json
{
  "planning_horizon_minutes": 120,
  "high_risk_threshold": 50,
  "objective_weights": {
    "risk_reduction": 0.5,
    "population_protection": 0.3,
    "critical_facility_protection": 0.2
  }
}
```

The returned `OptimizationInput` contains:

| Field | Meaning |
| --- | --- |
| `current_city_state` | Independent copy of the snapshot used for generation |
| `candidate_interventions` | Catalog actions with costs, timing, prerequisites, and expected effects |
| `resource_inventory` | Available resources from that exact snapshot |
| `planning_horizon_minutes` | Minutes forward from the snapshot's simulation time |
| `objective_weights` | Relative preferences preserved for the future allocator |
| `high_risk_threshold` | Inclusive cutoff on the existing 0–100 risk score |

The horizon must be 30, 60, 90, or 120 minutes and cannot exceed the snapshot's
scenario duration. Weights must be finite and nonnegative, with at least one
positive weight; they need not sum to one. Risk scores are synthetic estimates,
and the default cutoff of 50 is a configurable demo policy, not a calibrated
emergency threshold.

Generation selects targets that are **currently FAILED or CRITICAL**, or whose
current risk score meets the cutoff. Being degraded alone does not qualify a
node. Healthy, low-risk assets are excluded even if the baseline predicts a
later failure. For each selected target, only catalog actions applicable to its
infrastructure type are considered. Every action starts at the current snapshot
time; generation does not search future start times to manufacture eligibility.

Catalog validation rejects invalid prerequisites, incompatible target types,
insufficient resources, and actions that cannot finish in time. A shared baseline
cascade checks completion conditions, rejecting actions predicted to fail or
produce no immediate change. Failed facilities do not receive fuel or generators
as a substitute for restoration. Candidate ordering and IDs are deterministic.
Forecasts use the existing simulator's snapshot initialization and 30-minute ticks.

Each candidate is affordable **individually**. Candidates are alternatives and
may exceed the inventory when combined. Both planners enforce aggregate inventory limits and target exclusivity.
The existing manual candidate endpoint retains its independent timing search and
behavior.


## Benefit estimates

`POST /api/scenarios/{scenario_id}/optimization/candidates` accepts the same body
as the input endpoint. It returns the complete input, the baseline outcome, and
an assessment of each candidate. Each assessment includes its catalog resource
cost, projected outcome, success flag, and time to effect (waiting time plus
execution delay plus duration, measured from the snapshot time).

Run the baseline and each action through the actual cascade simulator, then
compare the states at exactly `planning_horizon_minutes`, even though the
simulator also calculates later ticks. Benefits are **signed** differences:

- **Expected risk reduction:** baseline system risk minus action system risk.
  System risk is the sum of the existing 0–100 node risk scores.
- **Population benefit:** baseline affected residents minus action affected
  residents, counting each impaired neighborhood's remaining residents once.
- **Critical facility benefit:** baseline minus action count of CRITICAL/FAILED
  substations, hospitals, pharmacies, shelters, and cooling centers, consistent
  with the existing cascade metrics.

Negative values report deterioration; they are not clamped away. Risk estimates
retain the existing model's synthetic, uncalibrated semantics. A benefit is a
horizon-end comparison, not an integral of downtime avoided. Time to effect is
reported separately and used to order equal-score candidates.

To combine different units, divide risk reduction by `100 * number_of_nodes`,
population benefit by the snapshot's total neighborhood population, and facility
benefit by the snapshot's critical facility count. Each denominator is at least
one and stays fixed across all alternatives. Normalize the supplied nonnegative
objective weights to sum to one, then sum their weighted normalized benefits.
The exposed `objective_score` is rounded to **1,000,000 integer units** for
selection, with no preference for an action whose rounded benefit is zero.
Changing all weights by the same factor does not change the objective.

## Response plans

`POST /api/scenarios/{scenario_id}/optimization/plan` accepts the same input
options plus `"method": "auto"`, `"heuristic"`, or `"ortools"`. The default
`auto` uses OR-Tools when available. Install backend dependencies with
`python3 -m pip install -r backend/requirements-dev.txt` to include the solver.
If the native solver cannot be imported, or its search budget yields no feasible
solution, the endpoint returns the heuristic plan and an explicit fallback
reason. Selecting `heuristic` never imports OR-Tools.

The **heuristic** sorts candidates by descending integer benefit, then earliest
time to effect, then candidate ID. It accepts each positive, successful candidate
if it fits all remaining resources and its target has not already been assigned.
It is deterministic and provides a feasible baseline; it does not guarantee an
optimal allocation.

The **OR-Tools CP-SAT model** creates one Boolean variable per candidate. It
maximizes the sum of selected candidates' integer benefits and constrains the sum
of costs for **every** inventory field to available stock. At most one action is
selected per target, including generator/fuel alternatives. Failed or nonpositive
candidates are fixed to zero. Input validation enforces completion within the
horizon and canonical catalog costs before allocation.

Search uses one worker, seed zero, stable candidate order, and a deterministic
search budget of five units. If the optimum is proven, a second bounded solve
fixes that objective and prefers higher-ranked candidates to break ties. A
feasible solution is usable when optimality is not proven; `solver_status`
reports the status of the primary additive model. The implementation follows
[Google's CP-SAT model and solver API](https://developers.google.com/optimization/cp/cp_solver).

Both planners reserve resources for the entire plan, consistent with the
simulator: crews and vehicles are not recycled between tasks. Actions predicted
to fail when replayed together are removed and the remaining plan is replayed
again. A combined plan with nonpositive weighted benefit is replaced by the
no-action plan. `selection_adjusted_after_replay` makes this adjustment explicit;
removed candidates are not replaced or reoptimized in this baseline version.

The response includes selected candidates in operational order, rejected candidates
with reasons, used and remaining resources, the entire scored input, and both
the additive estimate and actual combined-plan benefit. Benefits of individual
actions can overlap, so do not sum them to report the combined benefit.
`OPTIMAL` applies to the additive candidate model before replay adjustments,
not to the nonlinear city response. Synthetic outcomes remain conditional on
the snapshot and simulator assumptions. The endpoint never applies the plan or
changes stored city state.

## Constraints and operational order

Every inventory field is enforced by both planners: mobile generators,
`fuel_gallons`, electrical repair crews, traffic crews, emergency vehicles, and
response personnel. Costs come from the server catalog, never from dashboard
inputs. For each resource `r`, `sum(cost[action, r] * selected[action]) <= inventory[r]`.
One action per target is allowed across the whole planning horizon. Resources
are reserved for the plan rather than reassigned between tasks.

Start times must be at or after the planning snapshot, aligned with 30-minute
simulation ticks, and leave enough time for both execution delay and duration
before the horizon ends. These conditions are checked at input validation,
catalog validation, and the selection boundary. No selected action is allowed to
borrow future stock or complete outside the planning window.

The documented objective is equivalent to minimizing estimated remaining loss:

```text
L = w_risk * sum(node_risk) / max(1, 100 * node_count)
  + w_population * affected_residents / max(1, initial_neighborhood_population)
  + w_facilities * critical_or_failed_facilities / max(1, critical_facility_count)
```

Weights are normalized to sum to one. Because baseline loss is fixed, maximizing
weighted loss reduction is equivalent to minimizing remaining weighted loss.
CP-SAT uses additive single-action reductions as its linear estimate; combined
simulation supplies the final reported benefit and does not double count
residents or facilities. Solver optimality applies to this linear estimate.

`selected_candidates` now includes consecutive `rank` values in operational
order: earliest scheduled start first, then weighted benefit, time to effect,
and candidate ID. `priority_rank` retains the order by estimated benefit. Actions
with the same start time are simultaneous assignments rather than a sequential
queue; their resources have already been reserved together.

## Dashboard

Use **GENERATE RESPONSE PLAN** on the City view while playback is paused or
complete, or from the initially loaded city state. During playback the dashboard
keeps complete backend snapshots for each simulation time and submits the full
snapshot for the displayed time, including graph, inventory, and node attributes.
It does not rebuild a city state from map markers or query a stale stored state.
The planning time and horizon appear above the recommendations.

The panel displays operational ranks, target assets, starts and effect times,
resource assignments, used/available/remaining inventory, combined risk reduction,
residents and facilities protected, rejected alternatives, and assumptions.
Selecting an action focuses its asset. Errors support retry. Reset or a change
of planning snapshot aborts pending requests and clears outdated recommendations.
Generating a response plan estimates actions; it does not execute them.

## Saved runs and replay

Every successful HTTP plan request is recorded atomically before its result is
returned. A response includes `run_id` and `recorded_at`. Records survive backend
restarts in `backend/data/optimization_runs.sqlite3`, which is excluded from Git.
Set `BLACKOUT_OPTIMIZATION_DB` to an alternate writable SQLite path for deployment
or tests. Tests use isolated temporary databases.

Each record contains the full optimization input (including candidates, city
state, graph, inventory, horizon and weights), requested and actual method,
selected and rejected actions, outcomes, costs, assumptions, input/output SHA-256
checksums, a startup fingerprint of backend Python sources, and Python, OR-Tools,
Pydantic and NetworkX versions. The input checksum also includes the requested
method. The record's schema version is independent of city schema versions.

- `GET /api/scenarios/{scenario_id}/optimization/runs?limit=20`: recent run summaries.
- `GET /api/scenarios/{scenario_id}/optimization/runs/{run_id}`: complete saved inputs
  and results; available from the dashboard's **View saved inputs and results** link.
- `POST /api/scenarios/{scenario_id}/optimization/runs/{run_id}/replay`: run the exact
  saved candidate input again without regenerating the pool or changing city state.

A replay is saved as a new record with `replay_of` pointing to the original. Its
response reports `matches_original` (ignoring audit ID and timestamp), plus
`engine_matches_original` and `runtime_matches_original`. Matching engine and
runtime versions support reproducibility; changed catalog definitions may reject
an old candidate instead of silently substituting a new action. These records
preserve evidence and detect accidental input/output modification; they are not
cryptographic signatures or a replacement for filesystem access controls.
A storage failure returns 503 rather than presenting an unrecorded successful
plan. Existing records can be read without relying on the current stored city.
