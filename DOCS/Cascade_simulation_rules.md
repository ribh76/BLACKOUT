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

## Backup and status

- A critical or failed power provider activates a dependent node's backup if
  reserve remains. Coverage is limited by `backup_capacity / current_load`
  and the fraction of reserve still available. Backup reduces power pressure.
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

`SimulationState` holds the city snapshot and exposure timers,
`SimulationEvent` records changes and causes, and `SimulationResult` holds the
full timeline and final population, failure, and critical-facility counts.
