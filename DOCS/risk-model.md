# Risk model

The risk engine scores a versioned `CityState` snapshot. Edges point from a
provider to a dependent. Scores are deterministic simulation outputs for the
synthetic city. **Failure likelihood is simulated; its coefficients are not
empirically validated real-world infrastructure probabilities.**

## Impact

All components are normalized to [0, 1]. Criticality is 70% infrastructure
type base and 30% the node's validated `criticality`. Type bases are hospital
1.00, substation 0.95, shelter 0.80, cooling center 0.78, pharmacy 0.72,
emergency route 0.65, neighborhood 0.60, intersection 0.42, warehouse 0.38.

`HumanExposure_i = log(1 + PopulationServed_i) / log(1 + MaxPopulationServed)`.
If all populations are zero, exposure is zero. The maximum is taken over the
current snapshot, so a single large population cannot contribute more than
0.25 to impact.

`RawSystemicImpact_i = Σ_j Criticality_j × 0.70 ^ Distance_ij`, summing each
reachable downstream node once. Distance is the shortest directed hop count.
The source is excluded, including in a cycle. `SystemicImpact_i` divides this
sum by the maximum raw systemic impact across the snapshot. When all sums are
zero, systemic impact is zero.

`PopulationVulnerability_i` uses the node's validated `vulnerability` field.
The data currently supplies one vulnerability value per asset; it does not
contain a separate population-specific measure.

`Impact_i = 0.30 × Criticality_i + 0.25 × HumanExposure_i + 0.30 ×
SystemicImpact_i + 0.15 × PopulationVulnerability_i`.
The displayed impact score is `100 × Impact_i`.

## Simulated failure likelihood

`DependencyDegradation_i` is the weighted mean of direct providers' failure
states: `Σ(weight_ji × state_j) / Σ(weight_ji)`. An asset with no providers has
zero dependency degradation. States are operational 0.00, degraded 0.33,
critical 0.67, and failed 1.00.

`LoadStress_i = clamp(CurrentLoad_i / Capacity_i, 0, 1)`.
`TemperatureStress_i = clamp((TemperatureF - 100) / 20, 0, 1)`.
`GridStress_i = clamp(GridLoad, 0, 1)`.
`EnvironmentalStress_i = 0.50 × TemperatureStress_i + 0.50 × GridStress_i`.
These temperature and grid weights are explicit simulation parameters.

`BackupAvailability_i` is 1 when backup capacity is positive, otherwise 0.
`BackupRemaining_i = clamp(backup_remaining / backup_capacity, 0, 1)` when
capacity is positive, otherwise 0. `BackupResilience_i` is their product.

`FailureLikelihood_i = sigmoid(-2.5 + 1.5 × LoadStress_i + 2.0 ×
DependencyDegradation_i + EnvironmentalStress_i - 1.5 ×
BackupResilience_i)`, where `sigmoid(x) = 1 / (1 + exp(-x))`.
This formula deliberately does not force a currently failed asset's likelihood
to 1. Its status appears separately and influences its direct dependents.

`Risk_i = FailureLikelihood_i × Impact_i`. The displayed risk score is
`100 × Risk_i`. Ranking sorts by displayed risk, then node ID.

## Operational priority

Time to failure is the first simulator tick when an asset reaches CRITICAL or
FAILED. It is 0 for an asset already in either state. If the event is not
observed during the 120-minute simulation horizon, the API returns `null` and
applies no urgency uplift to that asset.

`RawUrgency_i = Risk_i × (1 + 30 / (TimeToFailure_i + 5))`, with time in minutes.
The 30-minute strength and 5-minute epsilon are configurable model constants.
`OperationalPriority_i` divides raw urgency by the maximum raw urgency in the
snapshot and multiplies by 100. A zero maximum produces priority 0.
Recovery time affects this forecast through the simulator's recovery rules;
it is not an additional term in the specified impact or likelihood equations.

The ranking and each node's components are available at
`GET /api/scenarios/{scenario_id}/risk` and
`GET /api/scenarios/{scenario_id}/risk/{node_id}`. Starting or resetting the
scenario changes the snapshot being scored. The simulation API also returns
`risk_rankings` keyed by elapsed minute for playback. Every node includes
quality indicators for synthetic inputs and uncalibrated likelihood; nodes
without an observed critical or failed state within 120 minutes also carry a
forecast-horizon indicator.
