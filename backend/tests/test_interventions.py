"""Intervention contracts and the initial manual-response catalog."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.models.intervention import ExecutionStatus, Intervention, InterventionType
from app.services.city_data import load_city
from app.services.dependency_data import load_dependencies
from app.services.interventions import InterventionError, propose_intervention
from app.services.scenarios import apply_initial_events, load_scenario, reset_scenario


@pytest.fixture
def snapshot():
    city = load_city()
    scenario = load_scenario(city)
    return apply_initial_events(
        reset_scenario(scenario, city, load_dependencies(city).edges), scenario
    )


@pytest.mark.parametrize(
    ("action_type", "target_id", "costs"),
    [
        (InterventionType.DEPLOY_GENERATOR, "hospital-downtown", (1, 120, 1, 0, 1, 2)),
        (InterventionType.SEND_FUEL, "hospital-downtown", (0, 100, 0, 0, 1, 1)),
        (InterventionType.REPAIR_SUBSTATION, "substation-03", (0, 0, 1, 0, 1, 2)),
        (
            InterventionType.RESTORE_INTERSECTION,
            "intersection-santa-clara-market",
            (0, 0, 0, 1, 1, 2),
        ),
        (
            InterventionType.RELOCATE_POPULATION,
            "neighborhood-downtown",
            (0, 0, 0, 0, 2, 4),
        ),
    ],
)
def test_initial_types_have_complete_plans(snapshot, action_type, target_id, costs):
    target = next(node for node in snapshot.nodes if node.id == target_id)
    if action_type in {
        InterventionType.RESTORE_INTERSECTION,
        InterventionType.RELOCATE_POPULATION,
    }:
        target.status = "DEGRADED"
    original = snapshot.model_dump(mode="json")
    planned = propose_intervention(
        snapshot, "manual-1", action_type, target_id, snapshot.simulation_time
    )

    assert planned.type is action_type
    assert planned.target_node_id == target_id
    assert planned.duration_minutes > 0
    assert planned.prerequisites and planned.expected_effects
    assert planned.execution_status is ExecutionStatus.PLANNED
    assert tuple(planned.resource_costs.model_dump().values()) == costs
    assert Intervention.model_validate_json(planned.model_dump_json()) == planned
    assert snapshot.model_dump(mode="json") == original


def test_proposal_rejects_invalid_targets_and_limited_resources(snapshot):
    start = snapshot.simulation_time
    with pytest.raises(InterventionError, match="Unknown target"):
        propose_intervention(
            snapshot, "one", InterventionType.SEND_FUEL, "missing", start
        )
    with pytest.raises(InterventionError, match="cannot target"):
        propose_intervention(
            snapshot,
            "one",
            InterventionType.REPAIR_SUBSTATION,
            "hospital-downtown",
            start,
        )
    with pytest.raises(InterventionError, match="already operational"):
        propose_intervention(
            snapshot,
            "one",
            InterventionType.RESTORE_INTERSECTION,
            "intersection-santa-clara-market",
            start,
        )
    snapshot.resource_inventory.mobile_generators = 0
    with pytest.raises(InterventionError, match="Insufficient mobile_generators"):
        propose_intervention(
            snapshot,
            "one",
            InterventionType.DEPLOY_GENERATOR,
            "hospital-downtown",
            start,
        )


def test_proposal_rejects_invalid_timing_and_model_fields(snapshot):
    start = snapshot.simulation_time
    with pytest.raises(InterventionError, match="timezone"):
        propose_intervention(
            snapshot,
            "one",
            InterventionType.SEND_FUEL,
            "hospital-downtown",
            start.replace(tzinfo=None),
        )
    with pytest.raises(InterventionError, match="precede"):
        propose_intervention(
            snapshot,
            "one",
            InterventionType.SEND_FUEL,
            "hospital-downtown",
            start - timedelta(minutes=1),
        )
    with pytest.raises(InterventionError, match="horizon"):
        propose_intervention(
            snapshot,
            "one",
            InterventionType.SEND_FUEL,
            "hospital-downtown",
            start + timedelta(minutes=240),
        )
    planned = propose_intervention(
        snapshot, "one", InterventionType.SEND_FUEL, "hospital-downtown", start
    )
    with pytest.raises(ValidationError, match="duration_minutes"):
        Intervention.model_validate({**planned.model_dump(), "duration_minutes": 0})
    with pytest.raises(ValidationError, match="start_time"):
        Intervention.model_validate(
            {**planned.model_dump(), "start_time": start.replace(tzinfo=None)}
        )
