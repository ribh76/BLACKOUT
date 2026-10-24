export type NodeStatus = "OPERATIONAL" | "DEGRADED" | "CRITICAL" | "FAILED";
export type InfrastructureType =
  | "SUBSTATION"
  | "HOSPITAL"
  | "INTERSECTION"
  | "PHARMACY"
  | "SHELTER"
  | "COOLING_CENTER"
  | "WAREHOUSE"
  | "NEIGHBORHOOD"
  | "EMERGENCY_ROUTE";
export type InfrastructureNode = {
  id: string;
  name: string;
  type: InfrastructureType;
  status: NodeStatus;
  coordinates: { latitude: number; longitude: number };
  criticality: number;
  population_served: number;
  backup_remaining: number;
  backup_capacity: number;
  current_load: number;
};
export type InfrastructureSnapshot = {
  city: string;
  data_notice: string;
  capacity_units: Record<InfrastructureType, string>;
  count: number;
  nodes: InfrastructureNode[];
};
export type SimulationEvent = {
  elapsed_minutes: number;
  time: string;
  kind:
    | "STATUS_TRANSITION"
    | "BACKUP_ACTIVATED"
    | "BACKUP_DEACTIVATED"
    | "BACKUP_DEPLETED"
    | "INTERVENTION_SCHEDULED"
    | "INTERVENTION_STARTED"
    | "INTERVENTION_COMPLETED"
    | "INTERVENTION_FAILED";
  node_id: string;
  old_status: NodeStatus;
  new_status: NodeStatus;
  cause: string;
  source_node_id?: string | null;
  intervention_id?: string | null;
  intervention_type?: string | null;
  receiving_node_id?: string | null;
  population_relocated?: number;
  dependency_causes?: DependencyCause[];
  explanation: string;
};
export type DependencyCause = {
  provider_id: string;
  provider_status: NodeStatus;
  dependency_type: "POWER" | "ACCESS" | "SUPPLY";
  weight: number;
  contribution: number;
};

export function recordedSources(event: SimulationEvent): string[] {
  return [
    ...new Set([
      ...(event.dependency_causes ?? [])
        .filter((cause) => cause.contribution > 0)
        .map((cause) => cause.provider_id),
      ...(event.source_node_id ? [event.source_node_id] : []),
    ]),
  ];
}
export type SimulationState = {
  elapsed_minutes: number;
  city_state: { nodes: InfrastructureNode[] };
};
export type SimulationResult = {
  scenario_id: string;
  states: SimulationState[];
  events: SimulationEvent[];
  final_metrics: { system_risk_score: number | null };
  risk_rankings: Record<string, RiskRanking>;
};
export type NodeRisk = {
  node_id: string;
  name: string;
  type: InfrastructureType;
  status: NodeStatus;
  impact_score: number;
  failure_probability: number;
  risk_score: number;
  operational_priority: number;
  time_to_failure_minutes: number | null;
  direct_dependents: number;
  downstream_dependents: number;
  downstream_node_ids: string[];
  primary_drivers: string[];
  quality_indicators: string[];
};
export type RiskRanking = {
  scenario_id: string;
  simulation_time: string;
  count: number;
  nodes: NodeRisk[];
};
export type PlaybackStep =
  | {
      kind: "event";
      elapsed_minutes: number;
      event: SimulationEvent;
      node_state?: InfrastructureNode;
    }
  | { kind: "tick"; elapsed_minutes: number; nodes: InfrastructureNode[] };

/** Keep API event order; event assets get same-tick values before the full snapshot. */
export function buildPlaybackSteps(result: SimulationResult): PlaybackStep[] {
  const steps: PlaybackStep[] = [];
  const sortedEvents = result.events
    .map((event, order) => ({ event, order }))
    .sort(
      (a, b) =>
        a.event.elapsed_minutes - b.event.elapsed_minutes || a.order - b.order,
    );
  const sortedStates = [...result.states].sort(
    (a, b) => a.elapsed_minutes - b.elapsed_minutes,
  );
  let eventIndex = 0;
  for (const state of sortedStates) {
    while (
      eventIndex < sortedEvents.length &&
      sortedEvents[eventIndex].event.elapsed_minutes <= state.elapsed_minutes
    ) {
      const event = sortedEvents[eventIndex].event;
      steps.push({
        kind: "event",
        elapsed_minutes: event.elapsed_minutes,
        event,
        node_state:
          state.elapsed_minutes === event.elapsed_minutes
            ? state.city_state.nodes.find((node) => node.id === event.node_id)
            : undefined,
      });
      eventIndex += 1;
    }
    steps.push({
      kind: "tick",
      elapsed_minutes: state.elapsed_minutes,
      nodes: state.city_state.nodes,
    });
  }
  if (eventIndex !== sortedEvents.length)
    throw new Error("Simulation events extend beyond the final state");
  return steps;
}

export function applyPlaybackStep(
  nodes: InfrastructureNode[],
  step: PlaybackStep,
): InfrastructureNode[] {
  if (step.kind === "tick") return step.nodes;
  const changesStatus =
    step.event.kind === "STATUS_TRANSITION" ||
    step.event.kind === "INTERVENTION_COMPLETED";
  if (!changesStatus && !step.node_state) return nodes;
  return nodes.map((node) =>
    node.id === step.event.node_id
      ? {
          ...node,
          ...step.node_state,
          status:
            changesStatus
              ? step.event.new_status
              : node.status,
        }
      : node,
  );
}

/** Follow recorded source IDs backward through visible status transitions. */
export function traceCausalSequence(
  events: SimulationEvent[],
  nodeId: string | null,
): SimulationEvent[] {
  if (!nodeId) return [];
  let index = -1;
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const event = events[i];
    if (
      event.kind === "STATUS_TRANSITION" &&
      event.node_id === nodeId &&
      (event.new_status === "CRITICAL" || event.new_status === "FAILED")
    ) {
      index = i;
      break;
    }
  }
  if (index < 0) return [];

  const visited = new Set<number>();
  const pending = [index];
  while (pending.length) {
    const current = pending.pop()!;
    if (visited.has(current)) continue;
    visited.add(current);
    for (const sourceId of recordedSources(events[current])) {
      for (let i = current - 1; i >= 0; i -= 1) {
        const candidate = events[i];
        if (
          candidate.kind !== "STATUS_TRANSITION" ||
          candidate.node_id !== sourceId ||
          candidate.elapsed_minutes >= events[current].elapsed_minutes
        )
          continue;
        if (candidate.new_status !== "OPERATIONAL") pending.push(i);
        break;
      }
    }
  }
  return [...visited].sort((a, b) => a - b).map((i) => events[i]);
}

const criticalFacilityTypes = new Set<InfrastructureType>([
  "SUBSTATION",
  "HOSPITAL",
  "PHARMACY",
  "SHELTER",
  "COOLING_CENTER",
]);

/** Match the backend's population and facility counting rules for the visible state. */
export function currentMetrics(nodes: InfrastructureNode[]) {
  return {
    affectedPopulation: nodes
      .filter(
        (node) => node.type === "NEIGHBORHOOD" && node.status !== "OPERATIONAL",
      )
      .reduce((sum, node) => sum + node.population_served, 0),
    criticalFacilities: nodes.filter(
      (node) =>
        criticalFacilityTypes.has(node.type) &&
        (node.status === "CRITICAL" || node.status === "FAILED"),
    ).length,
    failedInfrastructure: nodes.filter((node) => node.status === "FAILED")
      .length,
  };
}
