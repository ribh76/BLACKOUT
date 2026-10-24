"""Direct and transitive traversal, exact paths, and impact calculations."""

import pytest

from app.models.dependency import DependencyEdge, DependencyPath, DownstreamImpact
from app.services.city_data import load_city
from app.services.dependency_data import load_dependencies
from app.services.dependency_graph import (
    DependencyGraphError,
    add_dependency,
    build_dependency_graph,
)
from app.services.dependency_queries import (
    get_dependencies,
    get_dependents,
    get_downstream_impact,
    get_downstream_nodes,
    get_downstream_tree,
    get_upstream_nodes,
    trace_dependency_path,
)


@pytest.fixture
def seeded_graph():
    city = load_city()
    return city, build_dependency_graph(city, load_dependencies(city).edges)


def test_direct_and_transitive_lookups_follow_edge_direction(seeded_graph) -> None:
    _, graph = seeded_graph

    assert get_dependencies(graph, "hospital-downtown") == [
        "emergency-route-east",
        "emergency-route-north",
        "intersection-santa-clara-market",
        "substation-03",
        "warehouse-north",
    ]
    assert get_dependents(graph, "substation-03") == [
        "cooling-center-downtown",
        "hospital-downtown",
        "intersection-santa-clara-market",
        "neighborhood-downtown",
        "pharmacy-downtown",
        "shelter-downtown",
    ]
    assert get_downstream_nodes(graph, "substation-03") == get_dependents(
        graph, "substation-03"
    )
    assert "substation-01" in get_upstream_nodes(graph, "hospital-downtown")
    assert "hospital-downtown" not in get_upstream_nodes(graph, "substation-03")


def test_path_tracing_returns_exact_metadata_for_each_hop(seeded_graph) -> None:
    _, graph = seeded_graph

    direct = trace_dependency_path(graph, "substation-03", "hospital-downtown")
    assert isinstance(direct, DependencyPath)
    assert direct.node_ids == ["substation-03", "hospital-downtown"]
    assert len(direct.edges) == 1
    assert direct.edges[0].dependency_type == "POWER"
    assert direct.edges[0].failure_delay_minutes == 15

    via_traffic = trace_dependency_path(
        graph, "intersection-alum-rock-capitol", "hospital-downtown"
    )
    assert via_traffic.node_ids == [
        "intersection-alum-rock-capitol",
        "emergency-route-east",
        "hospital-downtown",
    ]
    assert [edge.dependency_type.value for edge in via_traffic.edges] == [
        "ACCESS",
        "ACCESS",
    ]
    assert [edge.weight for edge in via_traffic.edges] == [0.84, 0.8]
    assert [edge.failure_delay_minutes for edge in via_traffic.edges] == [5, 15]
    assert [edge.restoration_requirement.value for edge in via_traffic.edges] == [
        "ROUTE_REOPENED",
        "ROUTE_REOPENED",
    ]
    assert (
        DependencyPath.model_validate_json(via_traffic.model_dump_json()) == via_traffic
    )


def test_path_tracing_is_deterministic_and_handles_no_path(seeded_graph) -> None:
    _, graph = seeded_graph

    path = trace_dependency_path(graph, "substation-01", "emergency-route-east")
    assert path.node_ids == [
        "substation-01",
        "intersection-alum-rock-capitol",
        "emergency-route-east",
    ]
    assert trace_dependency_path(graph, "hospital-downtown", "substation-03") is None
    self_path = trace_dependency_path(graph, "hospital-downtown", "hospital-downtown")
    assert self_path.node_ids == ["hospital-downtown"]
    assert self_path.edges == []


def test_downstream_impact_counts_each_asset_once(seeded_graph) -> None:
    city, graph = seeded_graph

    impact = get_downstream_impact(graph, city, "substation-03")
    assert isinstance(impact, DownstreamImpact)
    assert impact.downstream_node_count == 6
    assert impact.affected_population == 17200
    assert impact.service_population_exposure == 54900
    assert impact.critical_facility_ids == [
        "cooling-center-downtown",
        "hospital-downtown",
        "pharmacy-downtown",
        "shelter-downtown",
    ]
    assert impact.critical_facility_count == 4
    assert DownstreamImpact.model_validate_json(impact.model_dump_json()) == impact

    signal_impact = get_downstream_impact(
        graph, city, "intersection-santa-clara-market"
    )
    assert signal_impact.downstream_node_count == 1
    assert signal_impact.affected_population == 0
    assert signal_impact.service_population_exposure == 18000
    assert signal_impact.critical_facility_count == 1

    leaf_impact = get_downstream_impact(graph, city, "hospital-west")
    assert leaf_impact.downstream_node_count == 0
    assert leaf_impact.affected_population == 0
    assert leaf_impact.critical_facility_count == 0


def test_cycles_do_not_reinclude_source_or_repeat_nodes() -> None:
    city = load_city()
    graph = build_dependency_graph(city)
    for provider_id, dependent_id in [
        ("substation-03", "hospital-downtown"),
        ("hospital-downtown", "substation-03"),
    ]:
        add_dependency(
            graph,
            DependencyEdge(
                provider_id=provider_id,
                dependent_id=dependent_id,
                dependency_type="POWER",
                weight=0.9,
                failure_delay_minutes=10,
                restoration_requirement="SOURCE_RESTORED",
                requirement="CRITICAL",
            ),
        )

    assert get_downstream_nodes(graph, "substation-03") == ["hospital-downtown"]
    assert get_upstream_nodes(graph, "substation-03") == ["hospital-downtown"]
    assert (
        get_downstream_impact(graph, city, "substation-03").downstream_node_count == 1
    )
    assert (
        trace_dependency_path(graph, "substation-03", "hospital-downtown") is not None
    )


def test_tree_handles_long_paths_isolation_and_multiple_routes() -> None:
    city = load_city()
    graph = build_dependency_graph(city)
    ids = [node.id for node in city.nodes]

    def connect(source, target):
        add_dependency(
            graph,
            DependencyEdge(
                provider_id=source,
                dependent_id=target,
                dependency_type="SUPPLY",
                weight=0.8,
                failure_delay_minutes=15,
                restoration_requirement="INVENTORY_REPLENISHED",
                requirement="CRITICAL",
            ),
        )

    for source, target in zip(ids[:-2], ids[1:-1]):
        connect(source, target)
    tree = get_downstream_tree(graph, ids[0])
    assert len(tree) == len(ids) - 2
    assert tree[-1].depth == len(ids) - 2
    assert get_downstream_tree(graph, ids[-1]) == []
    assert trace_dependency_path(graph, ids[0], ids[-1]) is None

    connect(ids[0], ids[2])
    tree = get_downstream_tree(graph, ids[0])
    assert len({item.node_id for item in tree}) == len(tree)
    assert next(item for item in tree if item.node_id == ids[2]).depth == 1
    assert {item.node_id for item in tree} == set(get_downstream_nodes(graph, ids[0]))
    for item in tree:
        path = trace_dependency_path(graph, ids[0], item.node_id)
        assert item.depth == len(path.edges)
        assert item.edge == path.edges[-1]


def test_trace_rejects_missing_edge_metadata() -> None:
    graph = build_dependency_graph(load_city())
    graph.add_edge("substation-03", "hospital-downtown")

    with pytest.raises(DependencyGraphError, match="Invalid metadata on dependency"):
        trace_dependency_path(graph, "substation-03", "hospital-downtown")


def test_impact_rejects_graph_nodes_missing_from_city() -> None:
    city = load_city()
    graph = build_dependency_graph(city)
    graph.add_edge("substation-03", "unknown")

    with pytest.raises(DependencyGraphError, match="absent from city data"):
        get_downstream_impact(graph, city, "substation-03")


@pytest.mark.parametrize(
    "query",
    [
        lambda graph, city: get_dependencies(graph, "unknown"),
        lambda graph, city: get_dependents(graph, "unknown"),
        lambda graph, city: get_downstream_nodes(graph, "unknown"),
        lambda graph, city: get_upstream_nodes(graph, "unknown"),
        lambda graph, city: trace_dependency_path(
            graph, "unknown", "hospital-downtown"
        ),
        lambda graph, city: trace_dependency_path(graph, "substation-03", "unknown"),
        lambda graph, city: get_downstream_impact(graph, city, "unknown"),
    ],
)
def test_unknown_node_ids_raise_clear_error(seeded_graph, query) -> None:
    city, graph = seeded_graph

    with pytest.raises(DependencyGraphError, match="Unknown infrastructure node ID"):
        query(graph, city)
