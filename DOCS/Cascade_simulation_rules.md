# Cascade simulation rules (version 1)

The engine in `backend/app/services/simulation.py` runs at T+30, T+60, T+90,
and T+120 minutes. Every tick reads the preceding snapshot. Changes made at a
tick affect other nodes starting with the next tick. Input snapshots are deep
copied, and the same input produces the same timeline and final metrics.

## Pressure and load

- An impaired provider contributes pressure through each directed dependency
  after that edge's `failure_delay_minutes`. A degraded provider contributes
  0.35 of its edge weight, a critical provider 0.70, and a failed provider 1.0.
  Optional edges contribute half as much. Multiple contributions combine as
  `1 - product(1 - contribution)`.
- Local load stress is the amount by which `current_load / capacity` exceeds
  0.90. Substations also receive `max(0, grid_load - 0.90)` stress. Heat above
  100°F adds `(temperature_f - 100) / 100 * vulnerability` stress.
- Effective load ratio is `current_load / capacity * (1 + dependency_pressure)
  + load_stress`. The node's `failure_threshold` gates a failed target state.
  Cooling centers instead increase demand by 2% per degree above 95°F and
  reduce usable capacity by up to 35% as power pressure rises; nonpower
  pressure and load stress still apply.

## Backup and status

- A critical or failed power provider activates a dependent node's backup if
  reserve remains. Coverage is limited by `backup_capacity / current_load`
  and the fraction of reserve still available. Hospitals prioritize essential
  circuits and retain their coverage level until reserve is exhausted. Backup
  reduces power pressure.
- For each 30-minute outage tick, reserve is reduced by half the node's
  `current_load` (one-hour equivalent reserve units), to a floor of zero. The
  tick uses the reserve available at its start. Activation, depletion, and
  deactivation are separate timeline events.
- A node can move only one rung per tick: `OPERATIONAL → DEGRADED → CRITICAL →
  FAILED`. Pressure of at least 0.20 or stress of at least 0.15 calls for
  degradation. Pressure of at least 0.75 or effective load ratio of at least
  1.0 calls for critical status. Crossing `failure_threshold` calls for
  failure, but only a previously critical node can fail on that tick.
- Nonfailed nodes recover one rung only after a continuous healthy period of
  at least `recovery_time_minutes`. Failed nodes require a future repair
  intervention; they do not recover spontaneously.

## Facility behavior

- A hospital with full backup coverage remains degraded during a power outage
  until its reserve is exhausted. Partial coverage can still allow critical
  status if load and pressure are high enough.
- A pharmacy's refrigeration clock advances only during unprotected power
  loss. At 30, 60, and 90 minutes of lost refrigeration, its power-driven
  status progresses to degraded, critical, and potentially failed. Failure
  also requires crossing the pharmacy's `failure_threshold`. Available backup
  holds the refrigeration clock at zero.
- An intersection's signal clock uses the same 30/60/90-minute stages after
  battery backup is exhausted; failure also requires crossing the
  intersection's `failure_threshold`. Signal loss is recorded as the
  transition cause.
- A neighborhood transition reports `population_exposed`, the residents
  served by that neighborhood while it is impaired. Final affected population
  counts each impaired neighborhood once, regardless of its status rung.

`SimulationState` holds the city snapshot and exposure timers,
`SimulationEvent` records changes and causes, and `SimulationResult` holds the
full timeline and final population, failure, and critical-facility counts.

## Manual interventions

An intervention's `start_time` must align to a 30-minute tick. The simulator
reserves its resource costs in the cloned T+0 state and emits a scheduled event.
Execution begins after its delay, then its effect and completion or failure
event occur after its duration. Effects apply after that tick's cascade update,
so other nodes respond on the following tick. Reserved resources remain
committed for this run; no automatic crew or vehicle release is modeled yet.

| Type | Eligible target | Resource cost | Delay + duration | Completion effect | Failure at completion |
| --- | --- | --- | --- | --- | --- |
| `DEPLOY_GENERATOR` | Nonfailed hospital, pharmacy, shelter, or cooling center with a power dependency | 1 generator, 120 gallons, 1 electrical crew, 1 vehicle, 2 personnel | 0 + 30 min | Adds two hours of load-equivalent backup reserve | Target failed or power dependency disappeared |
| `SEND_FUEL` | Hospital, pharmacy, shelter, or cooling center with backup capacity | 100 gallons, 1 vehicle, 1 personnel | 0 + 30 min | Adds one hour of load-equivalent backup reserve | Backup system unavailable |
| `REPAIR_SUBSTATION` | Impaired substation | 1 electrical crew, 1 vehicle, 2 personnel | 0 + 60 min | Sets status to operational and resets impairment timer | Already operational |
| `RESTORE_INTERSECTION` | Impaired intersection, or an at-risk one scheduled for later | 1 traffic crew, 1 vehicle, 2 personnel | 0 + 30 min | Restores status and resets signal-outage timer | Already operational |
| `RELOCATE_POPULATION` | Impaired or at-risk neighborhood with an operational receiving site with 100 free places | 2 vehicles, 4 personnel | 30 + 60 min | Moves up to 100 residents to a shelter or cooling center | Neighborhood recovered or receiving capacity unavailable |

At-risk targets must have a directly impaired provider and a completion time
after T+30. All actions must finish by T+120. Generator and fuel reserves use
the target's current load as their synthetic one-hour equivalent; gallons are
separate inventory units. A failed action keeps its reserved resources and
records the reason. The relocation event records residents moved and the
receiving node ID.

## Simulation API response

`POST /api/scenarios/extreme-heat-grid-failure/simulate` starts from the fixed
T+0 scenario and returns one complete `SimulationResult`:

- `states`: full city snapshots at T+0, T+30, T+60, T+90, and T+120.
- `events`: an ordered timeline of initial status transitions, later status
  transitions, and backup events. Each event includes the simulation timestamp,
  elapsed minutes, node ID, old and new status, cause, source node ID when a
  provider caused it, and a plain-language explanation. Source is `null` for
  external initial events, local load, heat, and recovery.
- `final_node_states`: the full nodes from the T+120 snapshot.
- `final_metrics`: distinct affected neighborhood population, failed asset
  count, critical or failed facility count, and `system_risk_score: null`.
  The risk score remains unset until the risk engine provides it.

The engine uses no randomness. A request reruns the same fixed initial
conditions, so repeat calls and reset followed by a rerun produce identical
JSON results.
