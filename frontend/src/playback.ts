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
    | "BACKUP_DEPLETED";
  node_id: string;
  old_status: NodeStatus;
  new_status: NodeStatus;
  cause: string;
  explanation: string;
};
export type SimulationState = {
  elapsed_minutes: number;
  city_state: { nodes: InfrastructureNode[] };
};
export type SimulationResult = {
  scenario_id: string;
  states: SimulationState[];
  events: SimulationEvent[];
  final_metrics: { system_risk_score: number | null };
};
export type PlaybackStep =
  | { kind: "event"; elapsed_minutes: number; event: SimulationEvent }
  | { kind: "tick"; elapsed_minutes: number; nodes: InfrastructureNode[] };

/** Keep API order for events at the same tick; snapshot fields land after those events. */
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
  if (step.event.kind !== "STATUS_TRANSITION") return nodes;
  return nodes.map((node) =>
    node.id === step.event.node_id
      ? { ...node, status: step.event.new_status }
      : node,
  );
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
