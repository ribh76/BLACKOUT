import type { InfrastructureNode } from "./playback";

export type ResourceInventory = {
  mobile_generators: number;
  fuel_gallons: number;
  electrical_crews: number;
  traffic_crews: number;
  emergency_vehicles: number;
  response_personnel: number;
};
export type PlanningCityState = {
  scenario_id: string;
  simulation_time: string;
  duration_minutes: number;
  nodes: InfrastructureNode[];
  resource_inventory: ResourceInventory;
  [key: string]: unknown;
};
export function isPlanningState(value: unknown): value is PlanningCityState {
  if (!value || typeof value !== "object") return false;
  const state = value as Partial<PlanningCityState>;
  return (
    typeof state.scenario_id === "string" &&
    typeof state.simulation_time === "string" &&
    typeof state.duration_minutes === "number" &&
    Array.isArray(state.nodes) &&
    !!state.resource_inventory
  );
}
export type PlanBenefit = {
  expected_risk_reduction: number;
  population_benefit: number;
  critical_facility_benefit: number;
};
export type AssessedAction = PlanBenefit & {
  intervention: {
    id: string;
    type: string;
    target_node_id: string;
    start_time: string;
  };
  time_to_effect_minutes: number;
  resource_cost: ResourceInventory;
};
export type ResponsePlan = {
  run_id: string;
  recorded_at: string;
  method_used: "heuristic" | "ortools";
  solver_status: string;
  fallback_reason: string | null;
  selected_candidates: (AssessedAction & {
    rank: number;
    priority_rank: number;
  })[];
  rejected_candidates: { candidate_id: string; reason: string }[];
  resource_utilization: ResourceInventory;
  remaining_resources: ResourceInventory;
  plan_benefit: PlanBenefit;
  assumptions: string[];
  assessment: {
    optimization_input: {
      current_city_state: PlanningCityState;
      planning_horizon_minutes: number;
      resource_inventory: ResourceInventory;
    };
    candidates: AssessedAction[];
  };
};
export const resourceLabels: Record<keyof ResourceInventory, string> = {
  mobile_generators: "Generators",
  fuel_gallons: "Fuel (gallons)",
  electrical_crews: "Repair crews",
  traffic_crews: "Traffic crews",
  emergency_vehicles: "Vehicles",
  response_personnel: "Response personnel",
};
export const actionLabels: Record<string, string> = {
  DEPLOY_GENERATOR: "Deploy generator",
  SEND_FUEL: "Deliver fuel",
  REPAIR_SUBSTATION: "Repair substation",
  RESTORE_INTERSECTION: "Restore intersection",
  RELOCATE_POPULATION: "Relocate residents",
};
