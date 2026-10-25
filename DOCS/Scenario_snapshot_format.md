# City-state snapshot format (version 1)

`CityState` in `backend/app/models/scenario.py` is the authoritative JSON schema
for a replay snapshot. Its `schema_version` is `1`. The snapshot includes:

| Field | Format | Meaning |
| --- | --- | --- |
| `scenario_id` | string | ID of the fixed scenario inputs. |
| `city`, `city_schema_version`, `capacity_units`, `data_notice` | string, integer, string map, string | Identity, version, units, and simulated-data notice for the city seed. |
| `simulation_time` | ISO 8601 timestamp with offset | Current simulation clock; the pristine and T+0 snapshots use the scenario's fixed start time. |
| `duration_minutes` | positive integer | Scenario horizon. |
| `temperature_f` | finite number | External heat in degrees Fahrenheit. |
| `grid_load` | number from 0 to 1 | Fraction of rated grid capacity. |
| `nodes` | array of `InfrastructureNode` | Full per-node identity, coordinates, status, load, backup, thresholds, and other graph-relevant attributes. |
| `dependency_edges` | array of `DependencyEdge` | Directed provider-to-dependent edges and their weights, delays, requirements, and restoration rules. |
| `resource_inventory` | `ResourceInventory` object | Nonnegative counts for mobile generators, fuel gallons, electrical crews, traffic crews, emergency vehicles, and response personnel. |
| `event_history` | array of `ScenarioEvent` | Ordered `{sequence, time, node_id, status}` transitions. Empty before start; initial events occur at T+0. |

Arrays retain the versioned city and dependency seed order. Initial failures
are recorded before initial degradations, in their declared order. Replaying
starts from a private deep copy of the pristine snapshot, so edits to a
returned snapshot or to the original seed objects cannot change another run.
`CityState.model_validate_json(snapshot.model_dump_json())` round-trips the
format for storage or comparison.

Manual actions use the `Intervention` contract in
`backend/app/models/intervention.py`: ID, type, target node ID, timezone-aware
start time, positive duration in minutes, prerequisites, resource costs,
expected effects, failure conditions, and execution status. `propose_intervention`
uses the five action definitions to check target type, timing, current state,
and inventory without consuming resources or changing a snapshot.

`POST /api/scenarios/{id}/interventions/validate` accepts an array of
`{id, type, target_node_id, start_time}` requests and returns the canonical
intervention plans. `POST /api/scenarios/{id}/interventions/simulate` accepts the
same array and runs those plans on an independent started scenario snapshot.
`POST /api/scenarios/{id}/interventions/apply` exposes the same execution flow.
These endpoints reject invalid actions with a descriptive HTTP 422 response.
The stored scenario state is unchanged. The 120-minute simulator horizon is
the latest possible completion time even though scenario metadata lasts longer.

Candidate actions and their structured completion estimates are available from
`GET /api/scenarios/{id}/nodes/{node_id}/interventions`. Estimates use the same
effect handler as execution. Completion events include `node_effects` with full
before/after nodes and numeric pressure, backup-duration, and exposure changes,
including side effects on receiving facilities and reopened emergency routes.
