import React, { useEffect, useState } from "react";
import type { InfrastructureNode, SimulationEvent } from "./playback";
import { recordedSources } from "./playback";
import { explainAsset, flattenCascadeTree } from "./cascade";
import type { CascadeResponse, DependencyEdge } from "./cascade";

function edgeLabel(edge: DependencyEdge) {
  return `${edge.dependency_type.toLowerCase()} · ${Math.round(edge.weight * 100)}% weight · ${edge.failure_delay_minutes} min delay`;
}

export function CascadeExplorer({
  selectedNode,
  nodes,
  onSelect,
  apiUrl,
  onCascadeChange,
  causalEvents,
  onClear,
  events,
}: {
  selectedNode: InfrastructureNode | null;
  nodes: InfrastructureNode[];
  onSelect: (id: string) => void;
  apiUrl: string;
  onCascadeChange: (cascade: CascadeResponse | null) => void;
  causalEvents: SimulationEvent[];
  onClear: () => void;
  events: SimulationEvent[];
}) {
  const [cascade, setCascade] = useState<CascadeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selectedId = selectedNode?.id;

  useEffect(() => {
    if (!selectedId) {
      setCascade(null);
      onCascadeChange(null);
      setError(null);
      return;
    }
    const controller = new AbortController();
    setCascade(null);
    onCascadeChange(null);
    setError(null);
    fetch(
      `${apiUrl}/api/infrastructure/${encodeURIComponent(selectedId)}/cascade`,
      {
        signal: controller.signal,
      },
    )
      .then((response) => {
        if (!response.ok)
          throw new Error(`Cascade API returned ${response.status}`);
        return response.json() as Promise<CascadeResponse>;
      })
      .then((data) => {
        if (
          data.node_id !== selectedId ||
          !Array.isArray(data.provider_edges) ||
          !Array.isArray(data.dependent_edges) ||
          !Array.isArray(data.downstream_tree)
        )
          throw new Error("Invalid cascade response");
        if (!controller.signal.aborted) {
          setCascade(data);
          onCascadeChange(data);
        }
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted)
          setError(
            cause instanceof Error ? cause.message : "Unable to load cascade",
          );
      });
    return () => controller.abort();
  }, [selectedId, apiUrl, onCascadeChange]);

  return (
    <CascadeExplorerContent
      selectedNode={selectedNode}
      nodes={nodes}
      onSelect={onSelect}
      causalEvents={causalEvents}
      onClear={onClear}
      events={events}
      cascade={cascade?.node_id === selectedId ? cascade : null}
      error={error}
    />
  );
}

export function CascadeExplorerContent({
  selectedNode,
  nodes,
  onSelect,
  causalEvents,
  onClear,
  events,
  cascade,
  error = null,
}: {
  selectedNode: InfrastructureNode | null;
  nodes: InfrastructureNode[];
  onSelect: (id: string) => void;
  causalEvents: SimulationEvent[];
  onClear: () => void;
  events: SimulationEvent[];
  cascade: CascadeResponse | null;
  error?: string | null;
}) {
  const name = (id: string) => nodes.find((node) => node.id === id)?.name ?? id;
  const status = (id: string) => nodes.find((node) => node.id === id)?.status;
  const downstreamNodes = (cascade?.downstream_tree ?? [])
    .map((item) => nodes.find((node) => node.id === item.node_id))
    .filter((node): node is InfrastructureNode => Boolean(node));
  const affectedPopulation = downstreamNodes
    .filter(
      (node) => node.type === "NEIGHBORHOOD" && node.status !== "OPERATIONAL",
    )
    .reduce((total, node) => total + node.population_served, 0);
  const criticalTypes = new Set([
    "SUBSTATION",
    "HOSPITAL",
    "PHARMACY",
    "SHELTER",
    "COOLING_CENTER",
  ]);
  const affectedFacilities = downstreamNodes.filter(
    (node) => criticalTypes.has(node.type) && node.status !== "OPERATIONAL",
  ).length;
  const rows = cascade ? flattenCascadeTree(cascade) : [];
  const missingSources = [
    ...new Set(
      causalEvents.flatMap((event, index) =>
        recordedSources(event).filter(
          (source) =>
            !causalEvents
              .slice(0, index)
              .some((prior) => prior.node_id === source),
        ),
      ),
    ),
  ];
  return (
    <section className="cascade-panel" aria-label="Cascade Explorer">
      <p className="eyebrow">CAUSE AND EFFECT</p>
      <div className="cascade-title">
        <h2>Cascade Explorer</h2>
        {selectedNode && (
          <button type="button" onClick={onClear}>
            Clear focus
          </button>
        )}
      </div>
      {!selectedNode ? (
        <p className="cascade-help">
          Select an asset on the map, in the event feed, or in the risk ranking
          to trace its dependencies.
        </p>
      ) : error ? (
        <p className="cascade-error" role="alert">
          {error}
        </p>
      ) : !cascade ? (
        <p className="cascade-help">Loading {selectedNode.name}'s cascade…</p>
      ) : (
        <>
          <p className="cascade-source">
            <strong>{selectedNode.name}</strong> ·{" "}
            {selectedNode.status.toLowerCase()}
          </p>
          <p className="cascade-explanation">
            {explainAsset(selectedNode, nodes, events)}
          </p>
          {selectedNode.status !== "FAILED" &&
            selectedNode.status !== "CRITICAL" && (
              <p className="cascade-help">
                Potential chain for an asset that is currently{" "}
                {selectedNode.status.toLowerCase()}.
              </p>
            )}
          <div className="cascade-group">
            <h3>
              Direct providers <span>{cascade.provider_edges.length}</span>
            </h3>
            {cascade.provider_edges.length === 0 ? (
              <p>No direct providers.</p>
            ) : (
              <ul>
                {cascade.provider_edges.map((edge) => (
                  <li key={edge.provider_id}>
                    <strong>{name(edge.provider_id)}</strong>
                    <small>{edgeLabel(edge)}</small>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="cascade-group">
            <h3>
              Direct dependents <span>{cascade.dependent_edges.length}</span>
            </h3>
            {cascade.dependent_edges.length === 0 ? (
              <p>No direct dependents.</p>
            ) : (
              <ul>
                {cascade.dependent_edges.map((edge) => (
                  <li key={edge.dependent_id}>
                    <strong>{name(edge.dependent_id)}</strong>
                    <small>{edgeLabel(edge)}</small>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="cascade-group">
            <h3>
              Potential downstream chain{" "}
              <span>{cascade.downstream_tree.length}</span>
            </h3>
            <p>
              {cascade.dependent_edges.length} direct ·{" "}
              {Math.max(
                0,
                cascade.downstream_tree.length - cascade.dependent_edges.length,
              )}{" "}
              indirect dependencies
            </p>
            {cascade.downstream_tree.length === 0 ? (
              <p>No downstream assets.</p>
            ) : (
              <ol className="cascade-tree">
                {rows.map((item) => (
                  <li
                    key={item.node_id}
                    data-node-id={item.node_id}
                    data-depth={item.depth}
                    style={{ marginLeft: Math.min(item.depth - 1, 4) * 10 }}
                  >
                    <button
                      type="button"
                      onClick={() => onSelect(item.node_id)}
                    >
                      {name(item.node_id)}
                    </button>
                    <small>
                      Hop {item.depth} · from {name(item.parent_id)} ·{" "}
                      {edgeLabel(item.edge)}
                      {status(item.node_id) &&
                        ` · currently ${status(item.node_id)?.toLowerCase()}`}
                    </small>
                  </li>
                ))}
              </ol>
            )}
            {rows.length < cascade.downstream_tree.length && (
              <p>
                Some paths are unavailable. Showing reachable relationships
                only.
              </p>
            )}
            {rows.length > 0 && (
              <p>
                One shortest path per asset is shown; recorded causes below may
                include additional providers.
              </p>
            )}
          </div>
          <p className="cascade-impact">
            Currently impaired downstream: {affectedPopulation.toLocaleString()}{" "}
            residents · {affectedFacilities} critical facilities.
          </p>
          <p className="cascade-impact">
            Potential downstream exposure:{" "}
            {cascade.impact.affected_population.toLocaleString()} residents ·{" "}
            {cascade.impact.critical_facility_count} critical facilities.
          </p>
          <div className="cascade-group cascade-events">
            <h3>
              Recorded event chain <span>{causalEvents.length}</span>
            </h3>
            {causalEvents.length === 0 ? (
              <p>
                No critical or failed transition is recorded for this asset in
                the visible timeline.
              </p>
            ) : (
              <ol>
                {causalEvents.map((event, index) => (
                  <li
                    key={`${event.elapsed_minutes}-${event.node_id}-${index}`}
                  >
                    <strong>
                      T+{event.elapsed_minutes} · {name(event.node_id)} became{" "}
                      {event.new_status.toLowerCase()}
                    </strong>
                    <small>{event.explanation}</small>
                    {recordedSources(event).length > 0 && (
                      <small>
                        Recorded sources:{" "}
                        {recordedSources(event).map(name).join(", ")}
                      </small>
                    )}
                  </li>
                ))}
              </ol>
            )}
            {missingSources.length > 0 && (
              <p>
                Source events unavailable in this timeline:{" "}
                {missingSources.map(name).join(", ")}.
              </p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
