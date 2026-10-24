"""Manual action validation and simulator-owned execution."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.infrastructure import NodeStatus
from app.models.intervention import ExecutionStatus, InterventionType
from app.models.simulation import SimulationEventKind
from app.services.city_data import load_city
from app.services.dependency_data import load_dependencies
from app.services.interventions import (
    INTERVENTION_DEFINITIONS,
    InterventionError,
    propose_intervention,
    validate_intervention_plan,
)
from app.services.scenarios import apply_initial_events, load_scenario, reset_scenario
from app.services.simulation import run_simulation


@pytest.fixture
def snapshot():
    city = load_city()
    scenario = load_scenario(city)
    return apply_initial_events(
        reset_scenario(scenario, city, load_dependencies(city).edges), scenario
    )


def node(state, node_id):
    return next(item for item in state.city_state.nodes if item.id == node_id)


@pytest.mark.parametrize(
    ("action_type", "target_id", "delay", "duration"),
    [
        (InterventionType.DEPLOY_GENERATOR, "hospital-downtown", 0, 30),
        (InterventionType.SEND_FUEL, "hospital-downtown", 0, 30),
        (InterventionType.REPAIR_SUBSTATION, "substation-03", 0, 60),
        (
            InterventionType.RESTORE_INTERSECTION,
            "intersection-santa-clara-market",
            0,
            30,
        ),
        (InterventionType.RELOCATE_POPULATION, "neighborhood-downtown", 30, 60),
    ],
)
def test_action_catalog_timing_and_failure_conditions(
    action_type, target_id, delay, duration
):
    definition = INTERVENTION_DEFINITIONS[action_type]
    assert definition.execution_delay_minutes == delay
    assert definition.duration_minutes == duration
    assert definition.failure_conditions


def test_generator_and_fuel_apply_at_completion_and_reserve_resources(snapshot):
    before = snapshot.model_dump(mode="json")
    generator = propose_intervention(
        snapshot,
        "gen",
        InterventionType.DEPLOY_GENERATOR,
        "hospital-downtown",
        snapshot.simulation_time,
    )
    result = run_simulation(snapshot, [generator])
    hospital_before = node(result.states[0], "hospital-downtown")
    hospital_after = node(result.states[1], "hospital-downtown")
    assert hospital_after.backup_capacity > hospital_before.backup_capacity
    assert result.states[0].city_state.resource_inventory.mobile_generators == 2
    assert (
        result.states[0].interventions[0].execution_status
        is ExecutionStatus.IN_PROGRESS
    )
    assert (
        result.states[1].interventions[0].execution_status is ExecutionStatus.COMPLETED
    )
    assert [
        (event.elapsed_minutes, event.kind)
        for event in result.events
        if event.intervention_id == "gen"
    ] == [
        (0, SimulationEventKind.INTERVENTION_SCHEDULED),
        (0, SimulationEventKind.INTERVENTION_STARTED),
        (30, SimulationEventKind.INTERVENTION_COMPLETED),
    ]
    assert snapshot.model_dump(mode="json") == before

    fuel = propose_intervention(
        snapshot,
        "fuel",
        InterventionType.SEND_FUEL,
        "hospital-downtown",
        snapshot.simulation_time,
    )
    fueled = run_simulation(snapshot, [fuel])
    assert (
        node(fueled.states[1], "hospital-downtown").backup_remaining
        > node(run_simulation(snapshot).states[1], "hospital-downtown").backup_remaining
    )
    assert fueled.states[0].city_state.resource_inventory.fuel_gallons == 1100


def test_repair_and_intersection_restore_record_status_and_change_cascade(snapshot):
    repair = propose_intervention(
        snapshot,
        "repair",
        InterventionType.REPAIR_SUBSTATION,
        "substation-03",
        snapshot.simulation_time,
    )
    baseline = run_simulation(snapshot)
    restored = run_simulation(snapshot, [repair])
    assert node(restored.states[2], "substation-03").status is NodeStatus.OPERATIONAL
    assert node(baseline.states[2], "substation-03").status is NodeStatus.FAILED
    assert any(
        event.kind is SimulationEventKind.INTERVENTION_COMPLETED
        and event.old_status is NodeStatus.FAILED
        and event.new_status is NodeStatus.OPERATIONAL
        for event in restored.events
    )
    assert (
        node(restored.states[3], "hospital-downtown").status
        != node(baseline.states[3], "hospital-downtown").status
    )

    isolated = snapshot.model_copy(deep=True)
    isolated.dependency_edges = []
    intersection = next(
        node for node in isolated.nodes if node.id == "intersection-santa-clara-market"
    )
    intersection.status = NodeStatus.FAILED
    action = propose_intervention(
        isolated,
        "restore",
        InterventionType.RESTORE_INTERSECTION,
        intersection.id,
        isolated.simulation_time,
    )
    result = run_simulation(isolated, [action])
    assert node(result.states[1], intersection.id).status is NodeStatus.OPERATIONAL
    assert result.states[1].signal_unpowered_minutes[intersection.id] == 0


def test_relocation_moves_bounded_population_after_dispatch(snapshot):
    isolated = snapshot.model_copy(deep=True)
    isolated.dependency_edges = []
    neighborhood = next(
        node for node in isolated.nodes if node.id == "neighborhood-downtown"
    )
    neighborhood.status = NodeStatus.DEGRADED
    action = propose_intervention(
        isolated,
        "move",
        InterventionType.RELOCATE_POPULATION,
        neighborhood.id,
        isolated.simulation_time,
    )
    result = run_simulation(isolated, [action])
    assert (
        result.states[0].interventions[0].execution_status is ExecutionStatus.SCHEDULED
    )
    assert (
        result.states[1].interventions[0].execution_status
        is ExecutionStatus.IN_PROGRESS
    )
    assert node(result.states[2], neighborhood.id).population_served == 17200
    assert node(result.states[3], neighborhood.id).population_served == 17100
    completed = next(
        event
        for event in result.events
        if event.kind is SimulationEventKind.INTERVENTION_COMPLETED
    )
    assert completed.elapsed_minutes == 90
    assert completed.population_relocated == 100
    assert completed.receiving_node_id is not None


def test_validation_rejects_duplicate_ids_targets_costs_and_tampering(snapshot):
    start = snapshot.simulation_time
    one = propose_intervention(
        snapshot, "one", InterventionType.REPAIR_SUBSTATION, "substation-03", start
    )
    two = propose_intervention(
        snapshot, "two", InterventionType.REPAIR_SUBSTATION, "substation-07", start
    )
    with pytest.raises(InterventionError, match="Duplicate intervention ID"):
        validate_intervention_plan(snapshot, [one, one])
    duplicate_target = one.model_copy(update={"id": "other"})
    with pytest.raises(InterventionError, match="Duplicate REPAIR_SUBSTATION"):
        validate_intervention_plan(snapshot, [one, duplicate_target])
    third = one.model_copy(update={"id": "three", "target_node_id": "substation-01"})
    with pytest.raises(InterventionError, match="already operational"):
        validate_intervention_plan(snapshot, [one, third])
    snapshot.resource_inventory.electrical_crews = 1
    with pytest.raises(InterventionError, match="Insufficient electrical_crews"):
        validate_intervention_plan(snapshot, [one, two])
    forged = one.model_copy(deep=True)
    forged.resource_costs.electrical_crews = 0
    with pytest.raises(InterventionError, match="differs from the action definition"):
        validate_intervention_plan(snapshot, [forged])


def test_validation_rejects_off_tick_and_late_completion(snapshot):
    with pytest.raises(InterventionError, match="30-minute tick"):
        propose_intervention(
            snapshot,
            "late",
            InterventionType.SEND_FUEL,
            "hospital-downtown",
            snapshot.simulation_time + timedelta(minutes=5),
        )
    with pytest.raises(InterventionError, match="horizon"):
        propose_intervention(
            snapshot,
            "late",
            InterventionType.RELOCATE_POPULATION,
            "neighborhood-downtown",
            snapshot.simulation_time + timedelta(minutes=60),
        )


def test_validation_rejects_actions_with_no_possible_effect(snapshot):
    hospital = next(node for node in snapshot.nodes if node.id == "hospital-downtown")
    hospital.current_load = 0
    with pytest.raises(InterventionError, match="no active load"):
        propose_intervention(
            snapshot,
            "gen",
            InterventionType.DEPLOY_GENERATOR,
            hospital.id,
            snapshot.simulation_time,
        )
    neighborhood = next(
        node for node in snapshot.nodes if node.id == "neighborhood-downtown"
    )
    neighborhood.population_served = 0
    with pytest.raises(InterventionError, match="no residents"):
        propose_intervention(
            snapshot,
            "move",
            InterventionType.RELOCATE_POPULATION,
            neighborhood.id,
            snapshot.simulation_time,
        )


def test_runtime_failure_is_event_with_status_and_no_effect(snapshot):
    action = propose_intervention(
        snapshot,
        "repair",
        InterventionType.REPAIR_SUBSTATION,
        "substation-03",
        snapshot.simulation_time,
    )
    # A different intervention or external repair could restore the node first.
    state = run_simulation(snapshot, [action]).states[1].model_copy(deep=True)
    target = node(state, "substation-03")
    target.status = NodeStatus.OPERATIONAL
    from app.services.interventions import execute_intervention

    event = execute_intervention(state, state.interventions[0])
    assert event.kind is SimulationEventKind.INTERVENTION_FAILED
    assert "already operational" in event.explanation
    assert state.interventions[0].execution_status is ExecutionStatus.FAILED


def test_relocation_fails_if_receiving_capacity_disappears(snapshot):
    neighborhood = next(
        node for node in snapshot.nodes if node.id == "neighborhood-downtown"
    )
    neighborhood.status = NodeStatus.DEGRADED
    action = propose_intervention(
        snapshot,
        "move",
        InterventionType.RELOCATE_POPULATION,
        neighborhood.id,
        snapshot.simulation_time,
    )
    state = run_simulation(snapshot, [action]).states[2].model_copy(deep=True)
    for site in state.city_state.nodes:
        if site.type.value in {"SHELTER", "COOLING_CENTER"}:
            site.status = NodeStatus.FAILED
    from app.services.interventions import execute_intervention

    event = execute_intervention(state, state.interventions[0])
    assert event.kind is SimulationEventKind.INTERVENTION_FAILED
    assert "no operational receiving site" in event.explanation
    assert event.population_relocated == 0
    assert node(state, neighborhood.id).population_served == 17200


def test_manual_api_validates_and_simulates_clone_without_changing_store():
    path = "/api/scenarios/extreme-heat-grid-failure"
    with TestClient(app) as client:
        original = client.get(f"{path}/state").json()
        payload = [
            {
                "id": "repair-1",
                "type": "REPAIR_SUBSTATION",
                "target_node_id": "substation-03",
                "start_time": original["simulation_time"],
            }
        ]
        valid = client.post(f"{path}/interventions/validate", json=payload)
        simulated = client.post(f"{path}/interventions/simulate", json=payload)
        move = client.post(
            f"{path}/interventions/simulate",
            json=[
                {
                    "id": "move-1",
                    "type": "RELOCATE_POPULATION",
                    "target_node_id": "neighborhood-downtown",
                    "start_time": original["simulation_time"],
                }
            ],
        )
        invalid = client.post(
            f"{path}/interventions/validate",
            json=[{**payload[0], "target_node_id": "hospital-downtown"}],
        )
        after = client.get(f"{path}/state").json()
    assert valid.status_code == 200
    assert valid.json()[0]["resource_costs"]["electrical_crews"] == 1
    assert simulated.status_code == 200
    assert any(
        event["kind"] == "INTERVENTION_COMPLETED"
        for event in simulated.json()["events"]
    )
    assert invalid.status_code == 422
    assert "cannot target" in invalid.json()["detail"]
    assert move.status_code == 200
    assert any(event["population_relocated"] == 100 for event in move.json()["events"])
    assert after == original
