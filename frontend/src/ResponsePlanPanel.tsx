import React, { useEffect, useRef, useState } from "react";
import { actionLabels, resourceLabels } from "./optimization";
import type {
  PlanningCityState,
  ResourceInventory,
  ResponsePlan,
} from "./optimization";

export function ResponsePlanPanel({
  cityState,
  elapsedMinutes,
  disabled,
  apiUrl,
  onSelect,
}: {
  cityState: PlanningCityState | null;
  elapsedMinutes: number;
  disabled: boolean;
  apiUrl: string;
  onSelect: (nodeId: string) => void;
}) {
  const [plan, setPlan] = useState<ResponsePlan | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    setPlan(null);
    setError(null);
    setPending(false);
    return () => {
      request.current?.abort();
      request.current = null;
    };
  }, [cityState]);

  async function generate() {
    if (!cityState || disabled || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setPending(true);
    setError(null);
    setPlan(null);
    try {
      const response = await fetch(
        `${apiUrl}/api/scenarios/${encodeURIComponent(cityState.scenario_id)}/optimization/plan`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: controller.signal,
          body: JSON.stringify({
            current_city_state: cityState,
            planning_horizon_minutes: Math.min(120, cityState.duration_minutes),
            method: "auto",
          }),
        },
      );
      const payload = await response.json();
      if (!response.ok)
        throw new Error(
          typeof payload.detail === "string"
            ? payload.detail
            : `Plan API returned ${response.status}`,
        );
      if (
        !Array.isArray(payload.selected_candidates) ||
        !payload.run_id ||
        payload.assessment?.optimization_input?.current_city_state
          ?.scenario_id !== cityState.scenario_id
      )
        throw new Error("Invalid response plan");
      if (!controller.signal.aborted) setPlan(payload as ResponsePlan);
    } catch (cause) {
      if (!controller.signal.aborted)
        setError(
          cause instanceof Error
            ? cause.message
            : "Unable to generate response plan",
        );
    } finally {
      if (request.current === controller) {
        request.current = null;
        setPending(false);
      }
    }
  }
  const plannedState = plan?.assessment.optimization_input.current_city_state;
  const name = (nodeId: string) =>
    plannedState?.nodes.find((n) => n.id === nodeId)?.name ?? nodeId;
  const candidates = new Map(
    plan?.assessment.candidates.map((c) => [c.intervention.id, c]),
  );
  return (
    <section
      className="response-plan-panel"
      aria-label="Response plan"
      aria-busy={pending}
    >
      <div className="plan-heading">
        <div>
          <p className="eyebrow">RESOURCE ALLOCATION</p>
          <h2>Response plan</h2>
          <p>
            Protect residents and critical facilities with the resources
            available.
          </p>
        </div>
        <button
          className="simulate-button"
          onClick={generate}
          disabled={disabled || !cityState || pending}
        >
          {pending ? "GENERATING PLAN…" : "GENERATE RESPONSE PLAN"}
        </button>
      </div>
      <p className="plan-context">
        {cityState
          ? `Planning from T+${elapsedMinutes} · ${Math.min(120, cityState.duration_minutes)} minute horizon`
          : "Loading planning state…"}
        {disabled && cityState ? " · Pause playback to generate a plan." : ""}
      </p>
      {pending && (
        <p role="status">Evaluating interventions and available resources…</p>
      )}
      {error && (
        <p className="plan-error" role="alert">
          {error} Try generating the plan again.
        </p>
      )}
      {plan && (
        <>
          <div className="plan-summary">
            <div>
              <strong>
                {plan.plan_benefit.expected_risk_reduction.toFixed(2)}
              </strong>
              <span>risk points reduced</span>
            </div>
            <div>
              <strong>
                {plan.plan_benefit.population_benefit.toLocaleString()}
              </strong>
              <span>residents protected</span>
            </div>
            <div>
              <strong>{plan.plan_benefit.critical_facility_benefit}</strong>
              <span>critical facilities protected</span>
            </div>
          </div>
          <p className="plan-context">
            {plan.method_used === "ortools"
              ? plan.solver_status === "OPTIMAL"
                ? "Optimized allocation"
                : "Feasible allocation"
              : "Heuristic baseline"}{" "}
            · Benefits verified by combined simulation. Actions starting
            together can proceed in parallel.
          </p>
          {plan.fallback_reason && (
            <p className="plan-notice">
              Using the deterministic baseline because the optimization solver
              is unavailable or did not finish.
            </p>
          )}
          {!plan.selected_candidates.length ? (
            <p className="plan-empty">
              No beneficial actions fit the available resources and planning
              horizon.
            </p>
          ) : (
            <ol
              className="plan-actions"
              aria-label="Recommended actions in operational order"
            >
              {plan.selected_candidates.map((candidate) => {
                const action = candidate.intervention;
                const offset = Math.round(
                  (Date.parse(action.start_time) -
                    Date.parse(plannedState!.simulation_time)) /
                    60000,
                );
                return (
                  <li key={action.id} value={candidate.rank}>
                    <div>
                      <button
                        className="plan-target"
                        onClick={() => onSelect(action.target_node_id)}
                      >
                        {actionLabels[action.type] ?? action.type} →{" "}
                        {name(action.target_node_id)}
                      </button>
                      <p>
                        Start T+{elapsedMinutes + offset} · Effect T+
                        {elapsedMinutes + candidate.time_to_effect_minutes} min
                      </p>
                      <small>
                        {Object.entries(candidate.resource_cost)
                          .filter(([, cost]) => cost > 0)
                          .map(
                            ([resource, cost]) =>
                              `${cost} ${resourceLabels[resource as keyof ResourceInventory].toLowerCase()}`,
                          )
                          .join(" · ")}
                      </small>
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
          <div className="plan-resources">
            <table>
              <caption>Resource utilization</caption>
              <thead>
                <tr>
                  <th scope="col">Resource</th>
                  <th scope="col">Used</th>
                  <th scope="col">Available</th>
                  <th scope="col">Remaining</th>
                </tr>
              </thead>
              <tbody>
                {(
                  Object.keys(resourceLabels) as (keyof ResourceInventory)[]
                ).map((resource) => (
                  <tr key={resource}>
                    <th scope="row">{resourceLabels[resource]}</th>
                    <td>{plan.resource_utilization[resource]}</td>
                    <td>
                      {
                        plan.assessment.optimization_input.resource_inventory[
                          resource
                        ]
                      }
                    </td>
                    <td>{plan.remaining_resources[resource]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <details className="plan-details">
            <summary>
              Rejected alternatives ({plan.rejected_candidates.length})
            </summary>
            <ul>
              {plan.rejected_candidates.map((rejected) => {
                const candidate = candidates.get(rejected.candidate_id);
                return (
                  <li key={rejected.candidate_id}>
                    <strong>
                      {candidate
                        ? `${actionLabels[candidate.intervention.type] ?? candidate.intervention.type} → ${name(candidate.intervention.target_node_id)}`
                        : rejected.candidate_id}
                    </strong>
                    <p>{rejected.reason}</p>
                  </li>
                );
              })}
            </ul>
          </details>
          <details className="plan-details">
            <summary>Assumptions and estimates</summary>
            <ul>
              {plan.assumptions.map((assumption) => (
                <li key={assumption}>{assumption}</li>
              ))}
            </ul>
          </details>
          <p className="plan-context">
            Simulated recommendation ·{" "}
            <a
              href={`${apiUrl}/api/scenarios/${encodeURIComponent(cityState!.scenario_id)}/optimization/runs/${encodeURIComponent(plan.run_id)}`}
              target="_blank"
              rel="noreferrer"
            >
              View saved inputs and results
            </a>
          </p>
        </>
      )}
    </section>
  );
}
