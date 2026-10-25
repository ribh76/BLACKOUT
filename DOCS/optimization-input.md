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
may exceed the inventory when combined. This phase defines inputs and generates
candidates; benefit scoring, aggregate resource constraints, selection, and ranked
response plans are subsequent work. The existing manual candidate endpoint retains
its independent timing search and behavior.
