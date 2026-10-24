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
| `resource_inventory` | `ResourceInventory` object | Nonnegative counts for mobile generators, fuel gallons, electrical crews, traffic crews, and emergency vehicles. |
| `event_history` | array of `ScenarioEvent` | Ordered `{sequence, time, node_id, status}` transitions. Empty before start; initial events occur at T+0. |

Arrays retain the versioned city and dependency seed order. Initial failures
are recorded before initial degradations, in their declared order. Replaying
starts from a private deep copy of the pristine snapshot, so edits to a
returned snapshot or to the original seed objects cannot change another run.
`CityState.model_validate_json(snapshot.model_dump_json())` round-trips the
format for storage or comparison.
