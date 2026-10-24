"""Load fixed scenario inputs and produce independent replay snapshots."""

import json
from pathlib import Path
from threading import RLock

from pydantic import ValidationError

from app.models.city import CityData
from app.models.dependency import DependencyEdge
from app.models.infrastructure import NodeStatus
from app.models.scenario import CityState, Scenario, ScenarioEvent

DEFAULT_SCENARIO_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "extreme_heat_grid_failure_v1.json"
)


class ScenarioDataError(ValueError):
    """A scenario seed is invalid or cannot be applied to the loaded city."""


def load_scenario(city: CityData, path: Path = DEFAULT_SCENARIO_PATH) -> Scenario:
    """Read the scenario once and validate every initial event against the city."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScenarioDataError(f"Cannot load scenario at {path}: {exc}") from exc
    try:
        scenario = Scenario.model_validate(payload)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc']) or 'scenario'}: "
            f"{error['msg']}"
            for error in exc.errors()
        )
        raise ScenarioDataError(f"Invalid scenario at {path}: {details}") from exc

    node_ids = {node.id for node in city.nodes}
    for node_id in scenario.initial_failures + scenario.initial_degradations:
        if node_id not in node_ids:
            raise ScenarioDataError(
                f"Invalid scenario at {path}: unknown initial event node {node_id!r}"
            )
    return scenario


def reset_scenario(
    scenario: Scenario, city: CityData, dependency_edges: list[DependencyEdge]
) -> CityState:
    """Create a pristine snapshot without mutating city, scenario, or graph data."""

    return CityState(
        scenario_id=scenario.id,
        city=city.city,
        city_schema_version=city.schema_version,
        simulation_time=scenario.start_time,
        duration_minutes=scenario.duration_minutes,
        temperature_f=scenario.temperature_f,
        grid_load=scenario.grid_load,
        nodes=[node.model_copy(deep=True) for node in city.nodes],
        dependency_edges=[edge.model_copy(deep=True) for edge in dependency_edges],
        resource_inventory=scenario.resource_inventory.model_copy(deep=True),
        event_history=[],
    )


def apply_initial_event(state: CityState, node_id: str, status: NodeStatus) -> None:
    """Apply one declared T+0 event to a private state snapshot."""

    node = next((node for node in state.nodes if node.id == node_id), None)
    if node is None:
        raise ScenarioDataError(f"Unknown initial event node {node_id!r}")
    if node.status is not NodeStatus.OPERATIONAL:
        raise ScenarioDataError(f"Initial event already applied to {node_id!r}")
    if status not in (NodeStatus.FAILED, NodeStatus.DEGRADED):
        raise ScenarioDataError(f"Unsupported initial event status {status!r}")
    node.status = status
    state.event_history.append(
        ScenarioEvent(
            sequence=len(state.event_history),
            time=state.simulation_time,
            node_id=node_id,
            status=status,
        )
    )


def get_scenario_state(state: CityState) -> CityState:
    """Return an independent copy safe for callers to inspect or simulate."""

    return state.model_copy(deep=True)


class ScenarioStore:
    """Hold a single demo scenario's state safely across API requests."""

    def __init__(
        self, scenario: Scenario, city: CityData, dependency_edges: list[DependencyEdge]
    ) -> None:
        self.scenario = scenario
        self.city = city
        self.dependency_edges = dependency_edges
        self._lock = RLock()
        self._state = reset_scenario(scenario, city, dependency_edges)

    def get_scenario_state(self) -> CityState:
        with self._lock:
            return get_scenario_state(self._state)

    def reset_scenario(self) -> CityState:
        with self._lock:
            self._state = reset_scenario(
                self.scenario, self.city, self.dependency_edges
            )
            return get_scenario_state(self._state)

    def start_scenario(self) -> CityState:
        with self._lock:
            state = reset_scenario(self.scenario, self.city, self.dependency_edges)
            for node_id in self.scenario.initial_failures:
                apply_initial_event(state, node_id, NodeStatus.FAILED)
            for node_id in self.scenario.initial_degradations:
                apply_initial_event(state, node_id, NodeStatus.DEGRADED)
            self._state = state
            return get_scenario_state(self._state)
