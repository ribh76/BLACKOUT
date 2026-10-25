"""Counterfactual benefits and constrained deterministic resource allocation."""

import pytest

from app.models.infrastructure import InfrastructureType, NodeStatus
from app.models.optimization import ObjectiveWeights
from app.services.city_data import load_city
from app.services.dependency_data import load_dependencies
from app.services.optimization import build_optimization_input
from app.services.optimization_planner import plan_response
from app.services.optimization_scoring import assess_candidates
from app.services.scenarios import ScenarioStore, load_scenario


@pytest.fixture
def relocation_input():
    city = load_city()
    state = ScenarioStore(
        load_scenario(city), city, load_dependencies(city).edges
    ).start_scenario()
    neighborhood = next(
        n for n in state.nodes if n.type is InfrastructureType.NEIGHBORHOOD
    )
    receiver = next(n for n in state.nodes if n.type is InfrastructureType.SHELTER)
    state.nodes = [neighborhood, receiver]
    state.dependency_edges = []
    state.event_history = []
    state.temperature_f = 80.0
    state.grid_load = 0.0
    neighborhood.status = NodeStatus.FAILED
    neighborhood.population_served = 1000
    neighborhood.recovery_time_minutes = 1000
    neighborhood.capacity = 1000.0
    neighborhood.current_load = 500.0
    receiver.status = NodeStatus.OPERATIONAL
    receiver.capacity = 1000.0
    receiver.current_load = 100.0
    return build_optimization_input(
        state,
        planning_horizon_minutes=90,
        high_risk_threshold=100.0,
        objective_weights=ObjectiveWeights(
            risk_reduction=0.0,
            population_protection=1.0,
            critical_facility_protection=0.0,
        ),
    )


def test_relocation_has_hand_calculated_benefit_cost_and_completion(relocation_input):
    before = relocation_input.model_dump_json()
    assessment = assess_candidates(relocation_input)
    assert len(assessment.candidates) == 1
    candidate = assessment.candidates[0]
    assert candidate.population_benefit == 100
    assert candidate.critical_facility_benefit == 0
    assert candidate.time_to_effect_minutes == 90
    assert candidate.resource_cost.emergency_vehicles == 2
    assert candidate.resource_cost.response_personnel == 4
    assert candidate.objective_score == pytest.approx(0.1)
    assert candidate.objective_units == 100000
    assert relocation_input.model_dump_json() == before


@pytest.mark.parametrize("method", ["heuristic", "ortools"])
def test_planners_select_beneficial_action_without_mutation(relocation_input, method):
    before = relocation_input.model_dump_json()
    plan = plan_response(relocation_input, method=method)
    assert plan.method_used == method
    assert len(plan.selected_candidates) == 1
    assert plan.plan_benefit.population_benefit == 100
    assert plan.resource_utilization.emergency_vehicles == 2
    assert (
        plan.remaining_resources.emergency_vehicles
        == relocation_input.resource_inventory.emergency_vehicles - 2
    )
    assert plan == plan_response(relocation_input, method=method)
    assert relocation_input.model_dump_json() == before


@pytest.fixture
def city_input():
    city = load_city()
    state = ScenarioStore(
        load_scenario(city), city, load_dependencies(city).edges
    ).start_scenario()
    return build_optimization_input(state, high_risk_threshold=0.0)


@pytest.fixture
def allocation_fixture(city_input):
    """Hand fixture: one 10-point repair vs two 6-point fuel deliveries.

    The repair consumes both personnel, while each fuel delivery consumes one.
    All other inventory is sufficient. Greedy gets 10; the optimum is 6 + 6.
    """
    from app.services.optimization_scoring import assess_candidates

    assessment = assess_candidates(city_input)
    by_id = {c.intervention.id: c for c in assessment.candidates}
    repair = by_id["candidate:substation-03:REPAIR_SUBSTATION:0"]
    first = by_id["candidate:hospital-south:SEND_FUEL:0"]
    second = by_id["candidate:hospital-west:SEND_FUEL:0"]
    assessment.candidates = [repair, first, second]
    for candidate, units in zip(assessment.candidates, [10, 6, 6]):
        candidate.objective_units = units
    assessment.optimization_input.resource_inventory.response_personnel = 2
    return assessment


def test_cp_sat_beats_greedy_on_hand_calculated_fixture(allocation_fixture):
    from app.services.optimization_planner import select_candidates

    heuristic = select_candidates(allocation_fixture, method="heuristic")
    solved = select_candidates(allocation_fixture, method="ortools")
    assert heuristic.selected_ids == ["candidate:substation-03:REPAIR_SUBSTATION:0"]
    assert set(solved.selected_ids) == {
        "candidate:hospital-south:SEND_FUEL:0",
        "candidate:hospital-west:SEND_FUEL:0",
    }
    assert solved.solver_status == "OPTIMAL"
    allocation_fixture.candidates.reverse()
    assert select_candidates(allocation_fixture, method="ortools") == solved


@pytest.mark.parametrize("method", ["heuristic", "ortools"])
def test_target_exclusivity_and_every_inventory_dimension(city_input, method):
    from app.services.optimization_planner import select_candidates

    assessment = assess_candidates(city_input)
    assessment.candidates = [
        c
        for c in assessment.candidates
        if c.intervention.target_node_id == "pharmacy-downtown"
    ]
    assert len(assessment.candidates) == 2
    selected = select_candidates(assessment, method=method)
    assert len(selected.selected_ids) == 1
    for resource in type(city_input.resource_inventory).model_fields:
        restricted = assessment.model_copy(deep=True)
        setattr(restricted.optimization_input.resource_inventory, resource, 0)
        chosen = select_candidates(restricted, method=method)
        costs = sum(
            getattr(c.intervention.resource_costs, resource)
            for c in restricted.candidates
            if c.intervention.id in chosen.selected_ids
        )
        assert costs == 0


def test_solver_matches_exhaustive_small_fixture(city_input):
    from itertools import combinations

    from app.services.optimization_planner import select_candidates

    assessment = assess_candidates(city_input)
    assessment.candidates = [c for c in assessment.candidates if c.objective_units > 0][
        :8
    ]
    inventory = city_input.resource_inventory.model_dump()
    best = 0
    for size in range(len(assessment.candidates) + 1):
        for group in combinations(assessment.candidates, size):
            targets = [c.intervention.target_node_id for c in group]
            if len(targets) != len(set(targets)):
                continue
            if any(
                sum(getattr(c.resource_cost, r) for c in group) > available
                for r, available in inventory.items()
            ):
                continue
            best = max(best, sum(c.objective_units for c in group))
    result = select_candidates(assessment, method="ortools")
    actual = sum(
        c.objective_units
        for c in assessment.candidates
        if c.intervention.id in result.selected_ids
    )
    assert actual == best


def test_missing_native_solver_falls_back_to_baseline(allocation_fixture, monkeypatch):
    import app.services.optimization_planner as planner

    def unavailable():
        raise ImportError("test installation without ortools")

    expected = planner.select_candidates(allocation_fixture, method="heuristic")
    monkeypatch.setattr(planner, "_load_cp_model", unavailable)
    result = planner.select_candidates(allocation_fixture)
    assert result.method_used == "heuristic"
    assert result.selected_ids == expected.selected_ids
    assert result.solver_status == "UNAVAILABLE"
    assert "without ortools" in result.fallback_reason


@pytest.mark.parametrize("method", ["heuristic", "ortools"])
def test_no_benefit_failed_and_empty_pools_select_nothing(allocation_fixture, method):
    from app.services.optimization_planner import select_candidates

    allocation_fixture.candidates[0].objective_units = 0
    allocation_fixture.candidates[1].objective_units = -10
    allocation_fixture.candidates[2].completes_successfully = False
    assert select_candidates(allocation_fixture, method=method).selected_ids == []
    allocation_fixture.candidates = []
    assert select_candidates(allocation_fixture, method=method).selected_ids == []


def test_benefit_preserves_harm_instead_of_clamping(relocation_input):
    from app.models.optimization import OptimizationOutcome
    from app.services.optimization_scoring import estimate_benefit

    baseline = OptimizationOutcome(
        system_risk=5.0, affected_population=10, critical_facilities_at_risk=0
    )
    worse = OptimizationOutcome(
        system_risk=7.0, affected_population=20, critical_facilities_at_risk=1
    )
    benefit = estimate_benefit(relocation_input, baseline, worse)
    assert benefit.expected_risk_reduction == -2.0
    assert benefit.population_benefit == -10
    assert benefit.critical_facility_benefit == -1
    assert benefit.objective_score == pytest.approx(-0.01)


@pytest.mark.parametrize("method", ["heuristic", "ortools"])
def test_selected_plan_reports_actual_combined_benefit_and_resources(
    city_input, method
):
    from app.services.optimization_scoring import horizon_outcome
    from app.services.simulation import run_simulation

    plan = plan_response(city_input, method=method)
    replay = run_simulation(
        city_input.current_city_state,
        [c.intervention for c in plan.selected_candidates],
    )
    assert plan.projected_outcome == horizon_outcome(
        replay, city_input.planning_horizon_minutes
    )
    assert not any(e.kind.value == "INTERVENTION_FAILED" for e in replay.events)
    for resource, available in city_input.resource_inventory.model_dump().items():
        assert (
            getattr(plan.resource_utilization, resource)
            + getattr(plan.remaining_resources, resource)
            == available
        )
    # Two actions can protect the same facility; replay avoids double counting.
    assert plan.plan_benefit.critical_facility_benefit == 1
    if method == "heuristic":
        assert sum(c.critical_facility_benefit for c in plan.selected_candidates) == 2


def test_scores_use_the_requested_horizon_and_actual_risk(city_input):
    from app.services.optimization_scoring import horizon_outcome
    from app.services.simulation import run_simulation

    city_input.planning_horizon_minutes = 60
    city_input.candidate_interventions = [
        c
        for c in city_input.candidate_interventions
        if c.type.value == "REPAIR_SUBSTATION"
    ]
    assessment = assess_candidates(city_input)
    for candidate in assessment.candidates:
        projected = horizon_outcome(
            run_simulation(city_input.current_city_state, [candidate.intervention]), 60
        )
        assert candidate.projected_outcome == projected
        assert candidate.expected_risk_reduction == pytest.approx(
            assessment.baseline_outcome.system_risk - projected.system_risk
        )
        assert candidate.time_to_effect_minutes == 60


def test_scoring_rejects_forged_costs(city_input):
    city_input.candidate_interventions[0].resource_costs.fuel_gallons = 0
    with pytest.raises(ValueError, match="differs from the action definition"):
        assess_candidates(city_input)


def test_search_without_feasible_solution_falls_back(allocation_fixture, monkeypatch):
    from types import SimpleNamespace

    from ortools.sat.python import cp_model

    import app.services.optimization_planner as planner

    class UnfinishedSolver:
        parameters = SimpleNamespace()

        def solve(self, model):
            return cp_model.UNKNOWN

        def status_name(self, status):
            return "UNKNOWN"

    boundary = SimpleNamespace(
        CpModel=cp_model.CpModel,
        CpSolver=UnfinishedSolver,
        MODEL_INVALID=cp_model.MODEL_INVALID,
        OPTIMAL=cp_model.OPTIMAL,
        FEASIBLE=cp_model.FEASIBLE,
    )
    monkeypatch.setattr(planner, "_load_cp_model", lambda: boundary)
    result = planner.select_candidates(allocation_fixture)
    assert result.method_used == "heuristic"
    assert result.solver_status == "UNKNOWN"
    assert (
        result.selected_ids
        == planner.select_candidates(
            allocation_fixture, method="heuristic"
        ).selected_ids
    )
    assert "no feasible selection" in result.fallback_reason


def test_api_exposes_assessments_plans_and_missing_solver_fallback(monkeypatch):
    from fastapi.testclient import TestClient

    import app.services.optimization_planner as planner
    from app.main import app
    from app.models.optimization import OptimizationPlan

    root = "/api/scenarios/extreme-heat-grid-failure"
    with TestClient(app) as client:
        client.post(f"{root}/start")
        before = client.get(f"{root}/state").json()
        scores = client.post(f"{root}/optimization/candidates", json={})
        assert scores.status_code == 200
        assert scores.json()["candidates"]
        for method in ("heuristic", "ortools"):
            response = client.post(f"{root}/optimization/plan", json={"method": method})
            assert response.status_code == 200
            plan = OptimizationPlan.model_validate_json(response.content)
            assert plan.method_used == method
            assert plan.selected_candidates
            assert (
                plan.resource_utilization.electrical_crews
                <= before["resource_inventory"]["electrical_crews"]
            )

        def unavailable():
            raise ImportError("optional solver absent")

        monkeypatch.setattr(planner, "_load_cp_model", unavailable)
        fallback = client.post(f"{root}/optimization/plan", json={})
        assert fallback.status_code == 200
        assert fallback.json()["method_used"] == "heuristic"
        assert fallback.json()["fallback_reason"]
        assert client.get(f"{root}/state").json() == before
        assert (
            client.post(
                f"{root}/optimization/plan", json={"method": "bogus"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                f"{root}/optimization/candidates", json={"planning_horizon_minutes": 45}
            ).status_code
            == 422
        )
        assert (
            client.post("/api/scenarios/missing/optimization/plan", json={}).status_code
            == 404
        )


@pytest.mark.parametrize("method", ["heuristic", "ortools"])
def test_empty_inventory_returns_empty_valid_plan(city_input, method):
    state = city_input.current_city_state
    for resource in type(state.resource_inventory).model_fields:
        setattr(state.resource_inventory, resource, 0)
    inputs = build_optimization_input(state)
    plan = plan_response(inputs, method=method)
    assert plan.selected_candidates == []
    assert plan.plan_benefit.objective_units == 0
    assert all(cost == 0 for cost in plan.resource_utilization.model_dump().values())


def test_time_to_effect_includes_waiting_and_execution(city_input):
    from datetime import timedelta

    from app.services.interventions import propose_intervention

    original = next(
        c
        for c in city_input.candidate_interventions
        if c.target_node_id == "substation-03"
    )
    state = city_input.current_city_state
    city_input.candidate_interventions = [
        propose_intervention(
            state,
            original.id,
            original.type,
            original.target_node_id,
            state.simulation_time + timedelta(minutes=30),
        )
    ]
    assessment = assess_candidates(city_input)
    assert assessment.candidates[0].time_to_effect_minutes == 90


@pytest.mark.parametrize("method", ["heuristic", "ortools"])
def test_combined_relocation_conflicts_are_removed(relocation_input, method):
    state = relocation_input.current_city_state
    second = state.nodes[0].model_copy(deep=True)
    second.id = "neighborhood-second"
    state.nodes.append(second)
    # There is only room for one delivery of 100 residents.
    receiver = state.nodes[1]
    receiver.capacity = receiver.current_load + 100
    inputs = build_optimization_input(
        state,
        planning_horizon_minutes=90,
        high_risk_threshold=100.0,
        objective_weights=relocation_input.objective_weights,
    )
    assert len(inputs.candidate_interventions) == 2
    plan = plan_response(inputs, method=method)
    assert len(plan.selected_candidates) == 1
    assert plan.plan_benefit.population_benefit == 100
    assert plan.selection_adjusted_after_replay
    assert "combined-plan simulation" in plan.rejected_candidates[0].reason
    assert plan.resource_utilization.emergency_vehicles == 2


@pytest.mark.parametrize("method", ["heuristic", "ortools"])
@pytest.mark.parametrize("timing", ["late", "off_tick", "past"])
def test_selection_rejects_invalid_timing_at_its_boundary(
    allocation_fixture, method, timing
):
    from datetime import timedelta

    from app.services.optimization_planner import select_candidates

    candidate = allocation_fixture.candidates[0]
    allocation_fixture.candidates = [candidate]
    minutes = {"late": 90, "off_tick": 5, "past": -30}[timing]
    candidate.intervention.start_time = (
        allocation_fixture.optimization_input.current_city_state.simulation_time
        + timedelta(minutes=minutes)
    )
    assert select_candidates(allocation_fixture, method=method).selected_ids == []


@pytest.mark.parametrize("method", ["heuristic", "ortools"])
def test_randomized_allocations_respect_every_resource_including_traffic(
    city_input, method
):
    import random

    from app.models.intervention import InterventionType
    from app.services.interventions import propose_intervention
    from app.services.optimization_planner import select_candidates

    state = city_input.current_city_state
    intersection = next(
        n for n in state.nodes if n.type is InfrastructureType.INTERSECTION
    )
    intersection.status = NodeStatus.FAILED
    city_input.candidate_interventions.append(
        propose_intervention(
            state,
            "traffic-fixture",
            InterventionType.RESTORE_INTERSECTION,
            intersection.id,
            state.simulation_time,
        )
    )
    assessment = assess_candidates(city_input)
    # Test selection constraints independently of benefit estimation.
    for index, candidate in enumerate(assessment.candidates):
        candidate.objective_units = index + 1
        candidate.completes_successfully = True
    inventory = city_input.resource_inventory.model_dump()
    rng = random.Random(42)
    for _ in range(20):
        restricted = assessment.model_copy(deep=True)
        budget = {
            resource: rng.randint(0, available)
            for resource, available in inventory.items()
        }
        for resource, available in budget.items():
            setattr(
                restricted.optimization_input.resource_inventory, resource, available
            )
        result = select_candidates(restricted, method=method)
        chosen = [
            c for c in restricted.candidates if c.intervention.id in result.selected_ids
        ]
        assert len({c.intervention.target_node_id for c in chosen}) == len(chosen)
        for resource, available in budget.items():
            assert sum(getattr(c.resource_cost, resource) for c in chosen) <= available
    assessment.candidates = [
        c for c in assessment.candidates if c.intervention.id == "traffic-fixture"
    ]
    assert select_candidates(assessment, method=method).selected_ids == [
        "traffic-fixture"
    ]
    assessment.optimization_input.resource_inventory.traffic_crews = 0
    assert select_candidates(assessment, method=method).selected_ids == []


def test_response_ranks_follow_start_time_and_keep_priority_rank(city_input):
    from datetime import timedelta

    from app.services.interventions import propose_intervention

    state = city_input.current_city_state
    repair = next(
        a
        for a in city_input.candidate_interventions
        if a.target_node_id == "substation-03"
    )
    generator = next(
        a
        for a in city_input.candidate_interventions
        if a.target_node_id == "pharmacy-downtown"
        and a.type.value == "DEPLOY_GENERATOR"
    )
    delayed = propose_intervention(
        state,
        repair.id,
        repair.type,
        repair.target_node_id,
        state.simulation_time + timedelta(minutes=30),
    )
    city_input.candidate_interventions = [delayed, generator]
    plan = plan_response(city_input, method="heuristic")
    assert len(plan.selected_candidates) == 2
    assert [c.rank for c in plan.selected_candidates] == [1, 2]
    assert plan.selected_candidates[0].intervention.id == generator.id
    assert sorted(c.priority_rank for c in plan.selected_candidates) == [1, 2]


def test_weighted_objective_matches_hand_calculated_remaining_loss(relocation_input):
    from app.models.optimization import OptimizationOutcome
    from app.services.optimization_scoring import estimate_benefit

    # Two nodes, 1000 neighborhood residents and one critical facility.
    relocation_input.objective_weights = ObjectiveWeights(
        risk_reduction=0.5,
        population_protection=0.3,
        critical_facility_protection=0.2,
    )
    baseline = OptimizationOutcome(
        system_risk=100.0, affected_population=500, critical_facilities_at_risk=1
    )
    restored = OptimizationOutcome(
        system_risk=0.0, affected_population=0, critical_facilities_at_risk=0
    )
    benefit = estimate_benefit(relocation_input, baseline, restored)
    # Remaining loss drops from .5*(100/200) + .3*(500/1000) + .2*(1/1) to 0.
    assert benefit.objective_score == pytest.approx(0.6)
    assert benefit.objective_units == 600000
    relocation_input.objective_weights = ObjectiveWeights(
        risk_reduction=0.0,
        population_protection=1.0,
        critical_facility_protection=0.0,
    )
    assert estimate_benefit(
        relocation_input, baseline, restored
    ).objective_score == pytest.approx(0.5)
