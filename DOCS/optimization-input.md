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

The response includes selected candidates in score order, rejected candidates
with reasons, used and remaining resources, the entire scored input, and both
the additive estimate and actual combined-plan benefit. Benefits of individual
actions can overlap, so do not sum them to report the combined benefit.
`OPTIMAL` applies to the additive candidate model before replay adjustments,
not to the nonlinear city response. Synthetic outcomes remain conditional on
the snapshot and simulator assumptions. The endpoint never applies the plan or
changes stored city state.
