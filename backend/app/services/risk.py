"""Deterministic simulated impact, failure likelihood, and urgency."""

from math import exp, log1p

import networkx as nx

from app.models.infrastructure import InfrastructureType, NodeStatus
from app.models.risk import NodeRisk, RiskRanking
from app.models.scenario import CityState
from app.services.dependency_graph import DependencyGraphError
from app.services.simulation import run_simulation

BASE_CRITICALITY: dict[InfrastructureType, float] = {
    InfrastructureType.HOSPITAL: 1.00,
    InfrastructureType.SUBSTATION: 0.95,
    InfrastructureType.SHELTER: 0.80,
    InfrastructureType.COOLING_CENTER: 0.78,
    InfrastructureType.PHARMACY: 0.72,
    InfrastructureType.EMERGENCY_ROUTE: 0.65,
    InfrastructureType.NEIGHBORHOOD: 0.60,
    InfrastructureType.INTERSECTION: 0.42,
    InfrastructureType.WAREHOUSE: 0.38,
}
FAILURE_STATE = {
    NodeStatus.OPERATIONAL: 0.00,
    NodeStatus.DEGRADED: 0.33,
    NodeStatus.CRITICAL: 0.67,
    NodeStatus.FAILED: 1.00,
}
PROPAGATION_DECAY = 0.70
TEMPERATURE_WEIGHT = 0.50
GRID_WEIGHT = 0.50
URGENCY_STRENGTH_MINUTES = 30.0
URGENCY_EPSILON_MINUTES = 5.0


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _criticality(node) -> float:
    return _clamp(0.7 * BASE_CRITICALITY[node.type] + 0.3 * node.criticality)


def _time_to_failure(snapshot: CityState) -> dict[str, int]:
    """First simulated tick reaching CRITICAL or FAILED within the run horizon."""

    result = run_simulation(snapshot)
    return {
        node.id: state.elapsed_minutes
        for state in reversed(result.states)
        for node in state.city_state.nodes
        if node.status in (NodeStatus.CRITICAL, NodeStatus.FAILED)
    }


def rank_risk(snapshot: CityState) -> RiskRanking:
    """Score a snapshot; return risk order with separately normalized urgency."""

    nodes = {node.id: node for node in snapshot.nodes}
    if len(nodes) != len(snapshot.nodes):
        raise DependencyGraphError("Snapshot contains duplicate node IDs")
    graph = nx.DiGraph()
    graph.add_nodes_from(nodes)
    for edge in snapshot.dependency_edges:
        if edge.provider_id not in nodes or edge.dependent_id not in nodes:
            raise DependencyGraphError("Snapshot dependency references an unknown node")
        graph.add_edge(edge.provider_id, edge.dependent_id)

    criticality = {node.id: _criticality(node) for node in snapshot.nodes}
    max_population = max((node.population_served for node in snapshot.nodes), default=0)
    raw_systemic: dict[str, float] = {}
    downstream_ids: dict[str, list[str]] = {}
    for node in snapshot.nodes:
        distances = nx.single_source_shortest_path_length(graph, node.id)
        distances.pop(node.id, None)
        downstream_ids[node.id] = sorted(distances)
        raw_systemic[node.id] = sum(
            criticality[other_id] * PROPAGATION_DECAY**distance
            for other_id, distance in distances.items()
        )
    max_systemic = max(raw_systemic.values(), default=0.0)
    time_to_failure = _time_to_failure(snapshot)
    raw_rows = []
    for node in snapshot.nodes:
        human_exposure = (
            log1p(node.population_served) / log1p(max_population)
            if max_population
            else 0.0
        )
        systemic = raw_systemic[node.id] / max_systemic if max_systemic else 0.0
        vulnerability = node.vulnerability
        impact_components = {
            "criticality": 0.30 * criticality[node.id],
            "human exposure": 0.25 * human_exposure,
            "systemic impact": 0.30 * systemic,
            "population vulnerability": 0.15 * vulnerability,
        }
        impact = _clamp(sum(impact_components.values()))

        incoming = [e for e in snapshot.dependency_edges if e.dependent_id == node.id]
        total_weight = sum(edge.weight for edge in incoming)
        degradation = (
            sum(
                edge.weight * FAILURE_STATE[nodes[edge.provider_id].status]
                for edge in incoming
            )
            / total_weight
            if total_weight
            else 0.0
        )
        load = _clamp(node.current_load / node.capacity)
        temperature_stress = _clamp((snapshot.temperature_f - 100.0) / 20.0)
        grid_stress = _clamp(snapshot.grid_load)
        environmental = _clamp(
            TEMPERATURE_WEIGHT * temperature_stress + GRID_WEIGHT * grid_stress
        )
        backup_availability = float(node.backup_capacity > 0)
        backup_remaining = (
            _clamp(node.backup_remaining / node.backup_capacity)
            if node.backup_capacity
            else 0.0
        )
        resilience = backup_availability * backup_remaining
        logit = -2.5 + 1.5 * load + 2.0 * degradation + environmental - 1.5 * resilience
        likelihood = 1.0 / (1.0 + exp(-logit))
        risk = likelihood * impact
        failure_minutes = time_to_failure.get(node.id)
        urgency = risk * (
            1.0 + URGENCY_STRENGTH_MINUTES / (failure_minutes + URGENCY_EPSILON_MINUTES)
            if failure_minutes is not None
            else 1.0
        )
        raw_rows.append(
            (
                node,
                impact_components,
                human_exposure,
                systemic,
                degradation,
                load,
                environmental,
                resilience,
                likelihood,
                risk,
                failure_minutes,
                urgency,
            )
        )

    max_urgency = max((row[-1] for row in raw_rows), default=0.0)
    ranking = []
    for (
        node,
        components,
        human_exposure,
        systemic,
        degradation,
        load,
        environmental,
        resilience,
        likelihood,
        risk,
        failure_minutes,
        urgency,
    ) in raw_rows:
        downstream = downstream_ids[node.id]
        ranking.append(
            NodeRisk(
                node_id=node.id,
                name=node.name,
                type=node.type,
                status=node.status,
                impact_score=round(100 * sum(components.values()), 2),
                human_exposure=round(human_exposure, 4),
                systemic_impact=round(systemic, 4),
                population_vulnerability=round(node.vulnerability, 4),
                dependency_degradation=round(degradation, 4),
                load_stress=round(load, 4),
                environmental_stress=round(environmental, 4),
                backup_resilience=round(resilience, 4),
                failure_probability=round(likelihood, 4),
                risk_score=round(100 * risk, 2),
                time_to_failure_minutes=failure_minutes,
                operational_priority=round(100 * urgency / max_urgency, 2)
                if max_urgency
                else 0.0,
                direct_dependents=graph.out_degree(node.id),
                downstream_dependents=len(downstream),
                downstream_node_ids=downstream,
                primary_drivers=[
                    key
                    for key, _ in sorted(
                        components.items(), key=lambda item: (-item[1], item[0])
                    )[:3]
                ],
            )
        )
    ranking.sort(key=lambda item: (-item.risk_score, item.node_id))
    return RiskRanking(
        scenario_id=snapshot.scenario_id,
        simulation_time=snapshot.simulation_time.isoformat(),
        count=len(ranking),
        nodes=ranking,
    )
