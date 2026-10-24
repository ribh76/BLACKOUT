import type { InfrastructureNode, SimulationEvent } from "./playback";

export type DependencyEdge = {
  provider_id: string;
  dependent_id: string;
  dependency_type: "POWER" | "ACCESS" | "SUPPLY";
  weight: number;
  failure_delay_minutes: number;
};
export type CascadeTreeNode = {
  node_id: string;
  parent_id: string;
  depth: number;
  edge: DependencyEdge;
};
export type CascadeResponse = {
  node_id: string;
  provider_edges: DependencyEdge[];
  dependent_edges: DependencyEdge[];
  downstream_tree: CascadeTreeNode[];
  impact: { affected_population: number; critical_facility_count: number };
};

/** Depth-first display order, with unique nodes and no recursive stack limit. */
export function flattenCascadeTree(
  cascade: CascadeResponse,
): CascadeTreeNode[] {
  const children = new Map<string, CascadeTreeNode[]>();
  for (const item of cascade.downstream_tree) {
    const group = children.get(item.parent_id) ?? [];
    group.push(item);
    children.set(item.parent_id, group);
  }
  const visited = new Set([cascade.node_id]);
  const pending = [...(children.get(cascade.node_id) ?? [])].reverse();
  const rows: CascadeTreeNode[] = [];
  while (pending.length) {
    const item = pending.pop()!;
    if (visited.has(item.node_id)) continue;
    visited.add(item.node_id);
    rows.push(item);
    pending.push(...[...(children.get(item.node_id) ?? [])].reverse());
  }
  return rows;
}

export function explainAsset(
  node: InfrastructureNode,
  nodes: InfrastructureNode[],
  events: SimulationEvent[],
): string {
  const latest = [...events]
    .reverse()
    .find(
      (event) =>
        event.kind === "STATUS_TRANSITION" && event.node_id === node.id,
    );
  let explanation = `${node.name} is currently ${node.status.toLowerCase()}.`;
  if (latest?.new_status === node.status) {
    const causes = (latest.dependency_causes ?? []).filter(
      (cause) =>
        cause.contribution > 0 || cause.provider_id === latest.source_node_id,
    );
    if (causes.length && node.status !== "OPERATIONAL") {
      const details = causes.map((cause) => {
        const name =
          nodes.find((provider) => provider.id === cause.provider_id)?.name ??
          cause.provider_id;
        const pressure =
          cause.contribution === 0
            ? "power impairment"
            : `${cause.dependency_type.toLowerCase()} pressure`;
        const protection =
          cause.contribution === 0
            ? "; backup offset the pressure at that transition"
            : "";
        return `${pressure} from ${name} (was ${cause.provider_status.toLowerCase()}, ${Math.round(cause.weight * 100)}% dependency weight${protection})`;
      });
      explanation += ` At T+${latest.elapsed_minutes}, the simulator recorded ${details.join("; ")}.`;
    } else {
      explanation += ` Recorded at T+${latest.elapsed_minutes}: ${latest.explanation}`;
    }
  } else {
    explanation +=
      " No matching transition is available in the visible event history.";
  }
  if (node.backup_capacity === 0) {
    return `${explanation} No backup capacity is available.`;
  }
  if (node.backup_remaining === 0) {
    return `${explanation} Backup reserve is exhausted.`;
  }
  if (node.current_load === 0) {
    return `${explanation} Backup reserve remains; runtime cannot be estimated at zero load.`;
  }
  explanation += ` Remaining backup reserve equals approximately ${(node.backup_remaining / node.current_load).toFixed(1)} hours at current load.`;
  if (node.backup_capacity < node.current_load) {
    explanation += ` Backup capacity covers ${Math.round((node.backup_capacity / node.current_load) * 100)}% of current demand.`;
  }
  return explanation;
}
