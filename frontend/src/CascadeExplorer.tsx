import React, { useEffect, useState } from "react";
import type { InfrastructureNode } from "./playback";

type DependencyEdge = {
  provider_id: string;
  dependent_id: string;
  dependency_type: "POWER" | "ACCESS" | "SUPPLY";
  weight: number;
  failure_delay_minutes: number;
};

type CascadeTreeNode = {
  node_id: string;
  parent_id: string;
  depth: number;
  edge: DependencyEdge;
};

type CascadeResponse = {
  node_id: string;
  provider_edges: DependencyEdge[];
  dependent_edges: DependencyEdge[];
  downstream_tree: CascadeTreeNode[];
  impact: {
    affected_population: number;
    critical_facility_count: number;
  };
};

function edgeLabel(edge: DependencyEdge) {
  return `${edge.dependency_type.toLowerCase()} · ${Math.round(edge.weight * 100)}% weight · ${edge.failure_delay_minutes} min delay`;
}

export function CascadeExplorer({
  selectedNode,
  nodes,
  onSelect,
  apiUrl,
}: {
  selectedNode: InfrastructureNode | null;
  nodes: InfrastructureNode[];
  onSelect: (id: string) => void;
  apiUrl: string;
}) {
  const [cascade, setCascade] = useState<CascadeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selectedId = selectedNode?.id;

  useEffect(() => {
    if (!selectedId) {
      setCascade(null);
      setError(null);
      return;
    }
    const controller = new AbortController();
    setCascade(null);
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
        if (!controller.signal.aborted) setCascade(data);
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted)
          setError(
            cause instanceof Error ? cause.message : "Unable to load cascade",
          );
      });
    return () => controller.abort();
  }, [selectedId, apiUrl]);

  const name = (id: string) => nodes.find((node) => node.id === id)?.name ?? id;
  const status = (id: string) => nodes.find((node) => node.id === id)?.status;
  const childrenByParent = new Map<string, CascadeTreeNode[]>();
  for (const item of cascade?.downstream_tree ?? []) {
    const siblings = childrenByParent.get(item.parent_id) ?? [];
    siblings.push(item);
    childrenByParent.set(item.parent_id, siblings);
  }
  const renderBranch = (
    parentId: string,
    visited: Set<string>,
    root = false,
  ): React.ReactNode => {
    const children = (childrenByParent.get(parentId) ?? []).filter(
      (item) => !visited.has(item.node_id),
    );
    if (children.length === 0) return null;
    return (
      <ol className={root ? "cascade-tree" : "cascade-branch"}>
        {children.map((item) => (
          <li key={item.node_id}>
            <button type="button" onClick={() => onSelect(item.node_id)}>
              {name(item.node_id)}
            </button>
            <small>
              from {name(item.parent_id)} · {edgeLabel(item.edge)}
              {status(item.node_id) &&
                ` · currently ${status(item.node_id)?.toLowerCase()}`}
            </small>
            {renderBranch(item.node_id, new Set([...visited, item.node_id]))}
          </li>
        ))}
      </ol>
    );
  };
  return (
    <section className="cascade-panel" aria-label="Cascade Explorer">
      <p className="eyebrow">CAUSE AND EFFECT</p>
      <h2>Cascade Explorer</h2>
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
            {cascade.downstream_tree.length === 0 ? (
              <p>No downstream assets.</p>
            ) : (
              renderBranch(cascade.node_id, new Set([cascade.node_id]), true)
            )}
          </div>
          <p className="cascade-impact">
            Potential exposure:{" "}
            {cascade.impact.affected_population.toLocaleString()} residents ·{" "}
            {cascade.impact.critical_facility_count} critical facilities.
          </p>
        </>
      )}
    </section>
  );
}
