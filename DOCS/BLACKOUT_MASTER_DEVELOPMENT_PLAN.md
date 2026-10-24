# BLACKOUT MASTER DEVELOPMENT PLAN
### Version 1.0 — From Empty Repository to Final Hackathon Submission

> Blackout is a deterministic emergency decision-support system that models cascading infrastructure failures, evaluates risk, recommends constrained interventions, and proves their value through counterfactual replay. AI explains and orchestrates the system; it is not the source of truth.

---

## ROADMAP CLASSIFICATION

- **CORE:** Blackout cannot function without this.
- **MUST SHIP:** Required for the portfolio MVP, public demo, or submission.
- **AI LAYER:** Natural-language reasoning and provider-specific intelligence built on the deterministic core.
- **POLISH:** Improves clarity, reliability, and presentation quality.
- **STRETCH:** Do not touch until the submission path is already working.

## DELIVERY PRINCIPLES

1. Build in dependency order. The graph comes before the cascade, the cascade before optimization, and optimization before the agent.
2. Work in vertical slices. Every phase must leave behind something executable and more demoable than before.
3. Keep the simulator as the source of truth. NetworkX models relationships, the simulator models consequences, OR-Tools optimizes choices, and the AI interprets verified state.
4. Prefer a small, coherent simulated San Jose environment over a broad but shallow real-world model.
5. Use deterministic rules for the initial submission. Repeatability is more valuable than fake sophistication.
6. Keep external providers behind interfaces. Anthropic may be used during early development; Nebius/Nemotron becomes the primary competition path when available.
7. Freeze scope at the Core MVP checkpoint. Enhancements cannot be allowed to destabilize the demo.
8. Keep the repository and commit history clean enough to explain what was added during the NVIDIA/Nebius submission period.

## MILESTONES

| Milestone | Phases | Result |
|---|---:|---|
| **Engine** | 0–4 | Blackout can model and simulate cascading infrastructure failure. |
| **Product** | 5–10 | A user can see, understand, mitigate, and replay the failure. |
| **AI / NVIDIA** | 11–14 | An AI provider can investigate, explain, optimize, and communicate using real simulator output. |
| **Ship** | 15–17 | The project is stable, documented, deployed, recorded, and submitted. |

---

# PART I — BUILD THE FOUNDATION

## PHASE 0: PROJECT FOUNDATION AND WORKFLOW
**Classification: CORE**

### Goal

Create a clean, runnable repository that supports parallel backend/frontend work without premature infrastructure complexity.

### Actions

1. Create the repository structure:

   ```text
   blackout/
   ├── backend/
   │   ├── app/
   │   │   ├── api/
   │   │   ├── core/
   │   │   ├── models/
   │   │   ├── schemas/
   │   │   └── services/
   │   ├── simulation/
   │   ├── optimization/
   │   ├── ai/
   │   ├── data/
   │   └── tests/
   ├── frontend/
   ├── docs/
   ├── README.md
   ├── LICENSE
   └── .env.example
   ```

2. Initialize the FastAPI backend and React/TypeScript frontend with a documented local development command. - 
3. Add `GET /api/health` and verify that the frontend can call it and render a successful response. - 
4. Add environment configuration for development mode, CORS, API URL, AI provider selection, Anthropic credentials, and future Nebius credentials. - 
5. Install only the initial dependencies: FastAPI, Pydantic, NetworkX, pytest, HTTPX, React, TypeScript, and the chosen map library. - 
6. Add formatting, linting, type-checking, and test commands for both backend and frontend. - 
7. Add a root-level `Makefile` or equivalent scripts for `dev`, `backend`, `frontend`, `test`, `lint`, and `format`. - 
8. Establish branch and pull-request conventions, including small feature branches, descriptive commits, and a requirement that the application still starts before merging. - 
9. Add an open-source license immediately and explain the project purpose and simulated-data disclaimer in the initial README. - 
10. Add a minimal CI workflow that installs dependencies and runs backend tests, frontend checks, and linting. - 

### Exit condition

```text
Frontend → FastAPI → GET /api/health → 200 OK
```

The repository starts from a clean checkout, and both developers can work without guessing how the project is structured.

---

## PHASE 1: INFRASTRUCTURE DATA MODEL
**Classification: CORE**

### Goal

Define the simulated city as validated, serializable infrastructure data rather than scattered hardcoded dictionaries.

### Actions

1. Define an `InfrastructureNode` model with identifiers, name, type, coordinates, status, criticality, population served, capacity, current load, backup capacity, backup remaining, failure threshold, recovery time, and vulnerability.-
2. Define strict node-status values: `OPERATIONAL`, `DEGRADED`, `CRITICAL`, and `FAILED`.-
3. Define infrastructure types for substations, hospitals, intersections, pharmacies, shelters, cooling centers, warehouses, neighborhoods, and emergency routes.-
4. Create approximately 30–40 simulated San Jose nodes with plausible coordinates and meaningful attributes.-
5. Design node attributes so different infrastructure behaves differently; a hospital should not be treated like a neighborhood or a traffic signal.-
6. Store the initial city in version-controlled JSON or TOML under `backend/data/`, with a schema version so future data changes are explicit.-
7. Implement a city-data loader that validates every record at startup and produces clear errors for duplicate IDs, invalid types, impossible coordinates, or missing required fields.-
8. Implement lookup services for retrieving one node, filtering by type/status, and returning the complete city snapshot.-
9. Add `GET /api/infrastructure` and `GET /api/infrastructure/{node_id}` with stable response schemas.-
10. Write tests covering data loading, validation, lookup behavior, serialization, and the expected minimum number of nodes by type.-

### Exit condition

Blackout has a reproducible, validated simulated city that can be queried through the API and loaded by the simulator without frontend-specific logic.

---

## PHASE 2: INFRASTRUCTURE DEPENDENCY GRAPH
**Classification: CORE**

### Goal

Represent why one failed asset can create consequences elsewhere in the city.

### Actions

1. Build a directed NetworkX graph in which every infrastructure asset is represented by its node ID.-
2. Define dependency direction clearly: an edge from A to B means B depends on A and can be affected when A degrades or fails.-
3. Add dependency metadata including dependency type, weight, failure delay, restoration requirement, and whether the dependency is critical or optional.-
4. Create realistic but intentionally simplified dependency chains connecting substations to hospitals, intersections, pharmacies, cooling centers, warehouses, and neighborhoods.-
5. Include multi-hop relationships so a substation can affect a hospital directly while also affecting hospital access through traffic infrastructure.-
6. Implement `get_dependencies`, `get_dependents`, `get_downstream_nodes`, and `get_upstream_nodes` services.-
7. Implement path tracing that returns the exact dependency path between two nodes, including edge metadata.-
8. Implement downstream impact counts, affected population totals, and affected critical-facility counts.-
9. Add `GET /api/infrastructure/{node_id}/dependencies` and `GET /api/infrastructure/{node_id}/impact`.- 
10. Add tests for direct dependencies, multi-hop traversal, directionality, missing nodes, cycles, and known expected impact totals.- 

### Exit condition

Blackout can answer, with a deterministic graph query:

> If this asset fails, what depends on it, through which path, and how much infrastructure or population is exposed?

---

# PART II — BREAK THE CITY

## PHASE 3: SCENARIO MODEL AND REPRODUCIBLE EVENTS
**Classification: CORE**

### Goal

Introduce an external disaster scenario and guarantee that the same initial conditions can be replayed exactly.

### Actions

1. Define a `Scenario` model with ID, name, description, start time, duration, temperature, grid load, initial failures, initial degradations, and resource inventory.-
2. Implement exactly one polished scenario first: **Extreme Heat + Grid Failure**.-
3. Set scenario parameters such as 105°F temperature, 97% grid load, Substation 03 failure, and Substation 07 degradation.-
4. Define a city-state snapshot format that includes node states, graph-relevant attributes, resource inventory, simulation time, and event history.-
5. Implement deep cloning so a scenario can be run, reset, and compared without shared mutable state contaminating another run.-
6. Implement `load_scenario`, `reset_scenario`, `apply_initial_event`, and `get_scenario_state` services.-
7. Add `GET /api/scenarios` and `GET /api/scenarios/{scenario_id}`.-
8. Add `POST /api/scenarios/{scenario_id}/start` and `POST /api/scenarios/{scenario_id}/reset`.-
9. Validate that every initial failure references a real node and that scenario resource quantities are nonnegative.-
10. Write replay tests proving that two clean runs begin with identical state and identical initial events.-

### Exit condition

Blackout can reproducibly introduce the same disaster into the same city and restore the city to its original state without restarting the server.

---

## PHASE 4: CASCADE SIMULATION ENGINE
**Classification: CORE / MUST SHIP**

### Goal

Model how an initial failure propagates through dependencies over discrete time.

### Actions

1. Define a simulation clock with discrete ticks such as `T+30`, `T+60`, `T+90`, and `T+120` minutes.-
2. Define a `SimulationState`, `SimulationEvent`, and `SimulationResult` model so state, transitions, and final metrics are separate concepts.-
3. Implement deterministic rules for dependency pressure, load stress, backup activation, backup depletion, recovery delay, and status transitions.-
4. Implement the status progression `OPERATIONAL → DEGRADED → CRITICAL → FAILED`; do not collapse every outcome into a binary failure.-
5. Apply dependency delays so a dependent can degrade immediately, become critical later, and fail only after a threshold is crossed.-
6. Model infrastructure-specific behavior, including hospital backup power, pharmacy refrigeration, intersection signal loss, cooling-center capacity, and neighborhood population impact.-
7. Record every state transition with timestamp, node ID, old status, new status, cause, source node, and human-readable explanation.-
8. Return a complete timeline, final node states, affected population, failed infrastructure count, critical-facility count, and system-risk placeholder.-
9. Ensure deterministic reproducibility for the MVP; use a seeded random generator only if stochastic behavior is later introduced.-
10. Write unit and integration tests for direct propagation, delayed failure, multi-hop propagation, reset behavior, and a complete known cascade.-
11. Add a backend endpoint to run a scenario and return either the complete timeline or a safe incremental event stream if the frontend needs animation data.-

### Exit condition

Blackout can produce a timeline similar to:

```text
T+0:00   Substation 03 FAILED
T+0:15   8,200 residents affected
T+0:30   Hospital A switched to backup
T+0:45   9 intersections DEGRADED
T+2:00   Hospital A CRITICAL
T+4:30   Hospital A FAILED
```

The simulator, not the frontend or an LLM, owns these outcomes.

---

# PART III — LET PEOPLE WATCH IT HAPPEN

## PHASE 5: INTERACTIVE CITY DASHBOARD
**Classification: MUST SHIP**

### Goal

Turn the deterministic engine into the first unmistakable Blackout experience: press one button and watch the city progressively fall apart.

### Actions

1. Add a geographic map using Leaflet or Mapbox with a stable San Jose viewport and a clear legend.-
2. Render every infrastructure node at its latitude and longitude.-
3. Use consistent status colors: green operational, yellow degraded, orange critical, and red failed.-
4. Add infrastructure-type icons or visual shapes so the map is readable beyond color alone.-
5. Add a node-detail panel showing type, status, criticality, population served, backup remaining, and current load.-
6. Add the `SIMULATE BLACKOUT` control and connect it to the scenario endpoint.-
7. Animate returned simulation events in timestamp order rather than changing every node instantly.-
8. Add simulation-clock, pause, resume, reset, loading, and error states.-
9. Add an event feed showing timestamp, node, transition, and cause.
10. Add high-level metrics for people affected, critical facilities, failed infrastructure, and current system risk.
11. Prevent duplicate runs, stale responses, and accidental state mixing when the user resets or reruns a scenario.
12. Add a frontend test or manual QA checklist for map rendering, event ordering, reset behavior, and API failures.

### Exit condition

From a fresh browser session, a user can load the city, press `SIMULATE BLACKOUT`, and watch green nodes transition to yellow, orange, and red across the map.

## MVP FALLBACK CHECKPOINT — WOW MOMENT #1

At the end of Phase 5, create a short backup screen recording. If later phases fail, this is still a working project demonstrating a cascading infrastructure simulator.

---

## PHASE 6: RISK AND CRITICALITY ENGINE
**Classification: MUST SHIP**

### Goal

Distinguish a failed asset from an asset whose failure matters most to the city.

### Actions

1. Define base criticality weights by infrastructure type, with hospitals and substations weighted above ordinary intersections or warehouses.
2. Normalize population served so large populations contribute meaningfully without overwhelming every other signal.
3. Incorporate direct and downstream dependency counts into impact scoring.
4. Incorporate vulnerability, backup availability, current load, and recovery time.
5. Calculate impact using a documented formula such as:

   ```text
   Impactᵢ = wc·Cᵢ + wp·Pᵢ + wd·Dᵢ + wv·Vᵢ
   Riskᵢ   = FailureProbabilityᵢ × Impactᵢ
   ```

6. Derive failure probability from current state, scenario stress, dependency pressure, and remaining backup rather than inventing it in the UI.
7. Normalize scores to 0–100 and document the weight choices in `docs/risk-model.md`.
8. Produce a ranked risk list with score, confidence/quality indicators, primary drivers, and downstream impact.
9. Add an API endpoint for the current risk ranking and node-level risk explanation.
10. Add a `Critical Infrastructure` panel with sortable entries and click-to-highlight behavior on the map.
11. Test score bounds, ranking stability, empty downstream sets, degraded versus failed states, and known high-risk nodes.

### Exit condition

Blackout can answer:

> What should we be worried about right now, and why?

---

## PHASE 7: CASCADE EXPLORER AND EXPLAINABILITY
**Classification: MUST SHIP**

### Goal

Make the causal chain visually understandable instead of forcing users to infer it from map colors.

### Actions

1. Allow users to select a failed or critical asset from the map, event feed, or risk ranking.
2. Display immediate dependents and their relationship type, weight, and delay.
3. Display multi-hop downstream consequences as a compact dependency tree or graph.
4. Highlight affected nodes and paths on the map while dimming unrelated infrastructure.
5. Show direct dependencies, indirect dependencies, population affected, and critical facilities affected.
6. Show the event sequence that connects the initiating failure to the selected consequence.
7. Add a clear explanation generated from structured simulator data, such as “Hospital A is critical because it lost Substation 03 power and has 2.1 hours of backup remaining.”
8. Add a reset/clear-explorer action that returns the map to the city-wide view.
9. Ensure the explorer handles isolated nodes, missing paths, long paths, and multiple causes.
10. Test graph traversal results against the backend and verify that frontend labels never contradict simulator state.

### Exit condition

A user can see:

> This one failure is causing all of that.

---

# PART IV — FIGHT BACK

## PHASE 8: INTERVENTION MODEL AND MANUAL RESPONSE
**Classification: CORE / MUST SHIP**

### Goal

Represent actions that emergency responders can take and apply them to the simulated future.

### Actions

1. Define an `Intervention` model with ID, type, target node, start time, duration, prerequisites, resource costs, expected effects, and execution status.
2. Implement initial intervention types: `DEPLOY_GENERATOR`, `SEND_FUEL`, `REPAIR_SUBSTATION`, `RESTORE_INTERSECTION`, and `RELOCATE_POPULATION`.
3. Define a limited resource inventory with mobile generators, fuel, electrical crews, traffic crews, emergency vehicles, and any required personnel.
4. Define resource costs, target eligibility, execution delay, duration, and failure conditions for each intervention type.
5. Implement manual intervention validation so impossible actions are rejected with useful messages.
6. Implement intervention application as a simulator event, not as a direct frontend mutation.
7. Model effects such as restoring power, increasing backup duration, reducing dependency pressure, reopening a route, or moving exposed population.
8. Expose candidate interventions for a selected node and return estimated immediate effects.
9. Add API endpoints for validating and applying an intervention to a cloned scenario state.
10. Add tests for resource consumption, invalid targets, duplicate actions, timing, restoration, and interaction with the cascade engine.

### Exit condition

Humans can change the simulated future, and the simulator can show exactly which state changes resulted from the intervention.

---

## PHASE 9: RESOURCE OPTIMIZATION ENGINE
**Classification: MUST SHIP**

### Goal

Answer the operational question:

> Given limited resources, where should they go first?

### Actions

1. Define the optimization input: current city state, candidate interventions, resource inventory, planning horizon, and objective weights.
2. Generate candidate interventions from currently failed, critical, or high-risk nodes rather than enumerating nonsensical actions.
3. Calculate each candidate’s resource cost, expected risk reduction, population benefit, critical-facility benefit, and time to effect.
4. Implement a simple deterministic heuristic baseline so the system remains usable if OR-Tools integration is delayed.
5. Integrate Google OR-Tools with variables representing whether each candidate intervention is selected.
6. Add constraints for generators, fuel, repair crews, traffic crews, vehicles, target exclusivity, and timing.
7. Optimize a documented objective such as minimizing remaining weighted system risk while protecting critical facilities and population.
8. Return a ranked response plan with selected actions, rejected alternatives, resource utilization, expected risk reduction, and assumptions.
9. Add `GENERATE RESPONSE PLAN` to the dashboard and display the recommended actions in operational order.
10. Add tests comparing the optimizer against small hand-calculated fixtures and verifying that it never violates inventory constraints.
11. Record the optimizer inputs and outputs so the plan can be explained and reproduced later.

### Exit condition

Blackout can produce a defensible plan such as:

```text
1. Repair Substation 03
2. Deploy Generator → Hospital A
3. Traffic Crew → Intersection 14
```

The plan is resource-feasible and accompanied by an estimated impact reduction.

---

## PHASE 10: COUNTERFACTUAL SIMULATION AND REPLAY
**Classification: MUST SHIP — HIGHEST-PRIORITY DEMO FEATURE**

### Goal

Prove that the recommended response changes the outcome instead of merely sounding intelligent.

### Actions

1. Snapshot the pristine scenario before any initial event or intervention is applied.
2. Run a baseline simulation with `NO INTERVENTION` and store its complete timeline, final state, and metrics.
3. Reset to the exact same initial state and verify snapshot equivalence before starting the response run.
4. Generate or load the recommended intervention plan and validate it against the available resources.
5. Apply the intervention plan to the cloned state through the simulator.
6. Run the response simulation with the same scenario parameters and simulation horizon.
7. Store both results under a shared comparison ID with explicit scenario and engine versions.
8. Compare critical failures, people affected, hospital downtime, system risk, recovery time, and resource utilization.
9. Add `APPLY RESPONSE & REPLAY` to the UI and animate the response run using the same event renderer as the baseline.
10. Add a before/after summary with absolute and percentage improvement, including a warning when an intervention produces no improvement.
11. Test that baseline and response runs share identical initial conditions and that results are reproducible across repeated executions.
12. Preserve both timelines for later AI explanations, screenshots, debugging, and demo recording.

### Exit condition

Blackout can demonstrate both:

> Here is what happens without action.

and:

> Here is what happens because we acted.

## CORE MVP FREEZE POINT

At this checkpoint, stop adding features temporarily. Stabilize this end-to-end flow:

```text
LOAD CITY
    ↓
START DISASTER
    ↓
WATCH CASCADE
    ↓
SEE CRITICAL RISKS
    ↓
GENERATE INTERVENTION
    ↓
REPLAY RESPONSE
    ↓
COMPARE OUTCOMES
```

Create a working backup deployment and record a private fallback demo before starting the AI layer.

---

# PART V — ADD INTELLIGENCE

## PHASE 11: AI PROVIDER ABSTRACTION
**Classification: AI LAYER**

### Goal

Make Blackout independent of any one model vendor while keeping all core outcomes deterministic.

### Actions

1. Define an `AIProvider` interface with methods for scenario analysis, cascade explanation, intervention explanation, response-plan explanation, and alert generation.
2. Define provider-neutral input and output schemas; pass compact structured state rather than raw database objects or uncontrolled prompts.
3. Implement an `AnthropicProvider` for early development if the available credits are approved for use.
4. Configure provider selection with an environment variable such as `AI_PROVIDER=anthropic`.
5. Add a stub or interface-compatible `NebiusNemotronProvider` so the competition integration has a clear insertion point.
6. Keep prompts, model names, temperature, timeouts, and token limits in configuration rather than scattered through routes.
7. Add retry, timeout, malformed-output, and provider-unavailable handling with deterministic fallback responses.
8. Log provider name, request purpose, latency, status, and run ID without logging secrets or unnecessary sensitive content.
9. Add tests using a fake provider so the application can be tested without consuming API credits.
10. Verify that disabling AI does not disable simulation, risk scoring, optimization, counterfactual replay, or the public demo.

### Exit condition

Blackout’s core application does not care whether Anthropic, Nemotron, or a fake provider is behind the explanation layer.

---

## PHASE 12: AI RESPONSE ANALYST AND CONTROLLED TOOLS
**Classification: AI LAYER**

### Goal

Allow a model to investigate Blackout through verified tools rather than hallucinating a parallel city.

### Actions

1. Define controlled tools: `get_city_status`, `inspect_node`, `trace_dependencies`, `get_risk_ranking`, `optimize_resources`, `simulate_intervention`, and `compare_scenarios`.
2. Make every tool return structured, schema-validated data with a run ID and source timestamp.
3. Expose only read operations initially, then add simulator-mediated actions after validation and audit logging are complete.
4. Create an analyst prompt that establishes the model’s role, prohibited behavior, available tools, and requirement to cite simulator facts.
5. Implement the investigation flow: inspect city, identify risk, trace dependencies, request optimization, test intervention, compare outcomes, and recommend response.
6. Require the model to distinguish observed facts, calculated metrics, assumptions, and recommendations.
7. Prevent the model from directly mutating city state, resource inventory, or simulation results.
8. Add a conversation panel with loading, tool-call, completion, refusal, and error states.
9. Display the underlying tool activity so users can see that the agent actually investigated the city.
10. Add evaluation fixtures for questions such as “Why is Hospital A at risk?” and “What happens if the generator goes to Shelter B instead?”
11. Test that unsupported questions receive a bounded response instead of invented infrastructure facts.

### Exit condition

The AI reasons about Blackout using Blackout’s tools; it does not pretend to be the simulator.

---

## PHASE 13: NEBIUS TOKEN FACTORY AND NEMOTRON AGENT
**Classification: AI LAYER / NVIDIA MUST SHIP**

### Goal

Turn the provider-neutral analyst into the NVIDIA/Nebius-specific competition feature.

### Actions

1. Confirm the accepted Nebius access path, model availability, endpoint, authentication requirements, rate limits, and submission rules before implementation.
2. Implement `NebiusNemotronProvider` behind the existing provider interface and keep credentials server-side.
3. Configure the appropriate Nemotron model, context limits, timeout, retry policy, and structured-output strategy.
4. Implement tool-calling or the closest supported controlled orchestration pattern through FastAPI functions.
5. Give Nemotron access to the same simulator-backed tools used by the analyst prototype.
6. Log every agent step with action name, target, result status, latency, and run ID for UI display and debugging.
7. Add an agent activity panel showing actions such as inspecting Substation 03, tracing dependencies, evaluating Hospital A, optimizing resources, simulating the response, and comparing outcomes.
8. Make Nemotron produce a final recommendation that includes evidence, selected interventions, expected tradeoffs, and a clear uncertainty statement.
9. Add a deterministic fallback path if Nebius is unavailable during a live demo.
10. Compare Nemotron outputs against the same known fixtures used for the fake and Anthropic providers.
11. Document exactly what was added or materially changed during the NVIDIA/Nebius submission period.
12. Verify the project still runs without Nebius credentials so the repository remains reproducible for judges and reviewers.

### Exit condition

Nemotron can autonomously investigate a scenario, invoke simulator-backed tools, recommend a response, and show its work in the interface.

## NVIDIA MVP CHECKPOINT

At this point, Blackout is no longer merely a simulator or an LLM wrapper:

```text
Nemotron reasons.
OR-Tools optimizes.
NetworkX models dependencies.
Blackout simulates consequences.
```

---

## PHASE 14: EMERGENCY COMMUNICATION ENGINE
**Classification: POLISH / MUST SHIP IF TIME ALLOWS**

### Goal

Translate verified infrastructure intelligence into communications for different audiences.

### Actions

1. Define communication inputs containing the scenario, affected geography, verified metrics, critical nodes, intervention status, and uncertainty.
2. Generate an emergency-manager brief with technical situation summary, key risks, recommended actions, and unresolved issues.
3. Generate a responder brief with locations, priorities, resource assignments, access constraints, and expected timing.
4. Generate a short public SMS that is concise, actionable, and based only on verified output.
5. Generate a readable public advisory with affected areas, expected conditions, protective actions, and update guidance.
6. Add audience selectors and separate formatting rules for each output.
7. Add a “why this message?” view that links each claim to simulator metrics or event records.
8. Add safeguards against unsupported locations, invented casualty counts, false certainty, and unsafe operational instructions.
9. Allow users to copy or export generated communications without exposing API credentials or internal prompts.
10. Test output generation with a fake provider and fixed scenario fixtures.

### Exit condition

Blackout communicates differently to the people making decisions, the responders executing them, and the people affected by them.

---

# PART VI — MAKE IT SUBMITTABLE

## PHASE 15: HACKATHON PRESENTATION MODE
**Classification: MUST SHIP**

### Goal

Convert the working system into a predictable, visually coherent demo that a judge can understand in under three minutes.

### Actions

1. Create a predefined demo scenario with fixed IDs, fixed timing, fixed resources, and a known expected outcome.
2. Add a presentation-mode entry point that loads the scenario and hides development-only controls.
3. Tune animation timing so the cascade is fast enough for a demo but slow enough to understand.
4. Improve node visuals, map contrast, typography, status legend, selected-node styling, and panel hierarchy.
5. Make the primary calls to action obvious: `SIMULATE BLACKOUT`, `GENERATE RESPONSE`, and `APPLY RESPONSE & REPLAY`.
6. Add prominent counters for people affected, critical facilities, failures, system risk, and improvement after intervention.
7. Display AI reasoning and tool activity in a compact, readable sequence rather than a wall of logs.
8. Add polished loading, empty, unavailable-provider, timeout, and recovery states.
9. Prevent double submissions, stale scenario results, accidental destructive actions, and inconsistent reset behavior.
10. Add a “demo reset” action that returns the application to the exact opening state.
11. Capture screenshots and a short fallback recording while the system is stable.
12. Test the presentation flow repeatedly from a fresh browser and from the deployed URL.

### Exit condition

A person unfamiliar with the project can understand the problem, run the disaster, see the cascade, inspect the recommendation, and understand the improvement without verbal rescue from the developer.

---

## PHASE 16: DEPLOYMENT, RELIABILITY, AND FINAL QA
**Classification: MUST SHIP**

### Goal

Make the public demo dependable and ensure the repository works for judges who follow the README.

### Actions

1. Deploy the frontend and backend using the simplest reliable architecture; do not introduce Kubernetes or unnecessary production infrastructure.
2. Configure production environment variables, CORS, API URLs, provider credentials, logging, and safe error responses.
3. Confirm that secrets are absent from Git history, frontend bundles, logs, screenshots, and README examples.
4. Seed or bundle all required simulated data so the demo does not depend on a fragile external database.
5. Add a health check and a small smoke-test script that verifies the deployed frontend, backend, scenario start, risk endpoint, optimization endpoint, and comparison endpoint.
6. Test a complete clean-user journey on the production URL using a fresh browser session.
7. Test provider failure, slow responses, malformed AI output, backend restart, repeated reset, and repeated simulation.
8. Confirm that deterministic endpoints produce the same results after deployment as they do locally.
9. Review performance for map rendering, event animation, API response size, and AI request latency.
10. Tag a release candidate and record the commit SHA used for the deployed version.
11. Write a known-limitations list, including simulated infrastructure, simplified physics, deterministic rules, and non-operational decision-support status.
12. Freeze feature development after release-candidate QA unless a blocker is found.

### Exit condition

The public URL works from a fresh browser, the repository starts from documented instructions, and the same demo can be run repeatedly without manual repair.

---

## PHASE 17: DOCUMENTATION, VIDEO, AND FINAL SUBMISSION
**Classification: MUST SHIP**

### Goal

Package Blackout so the project’s engineering, NVIDIA/Nebius integration, social value, and demo impact are immediately legible to judges.

### Actions

1. Update the README with the problem, target users, project thesis, screenshots, demo URL, repository URL, setup instructions, architecture, technology choices, and simulated-data disclaimer.
2. Add an architecture diagram showing the simulator as the source of truth and the roles of NetworkX, OR-Tools, frontend, Anthropic, and Nemotron.
3. Add a concise explanation of the cascade model, risk formula, intervention model, optimization objective, and counterfactual comparison.
4. Document the AI-provider abstraction and explicitly describe what Nemotron/Nebius contributes to the competition version.
5. Document the exact submission-period updates if the project existed before the competition window.
6. Verify the repository contains the required open-source license and that it is visible from the public repository root.
7. Write a submission narrative focused on the problem, the two wow moments, the NVIDIA/Nebius integration, and the measurable improvement from intervention.
8. Record a polished video no longer than three minutes using this sequence:

   ```text
   0:00  Hook: the outage is not the disaster; what happens next is.
   0:15  Scenario: extreme heat and substation failure.
   0:30  Wow #1: watch the cascade spread.
   1:00  Nemotron investigates the city.
   1:30  Recommended response appears.
   1:50  Wow #2: replay with intervention.
   2:15  Before/after metrics.
   2:30  Public communication output.
   2:45  Architecture and NVIDIA/Nebius contribution.
   2:55  Closing line and project name.
   ```

9. Record backup footage and keep a local copy of the final video, screenshots, and submission text.
10. Run the final submission checklist against the exact deployed commit and public repository state.
11. Submit before the deadline, then verify that the submission page contains the correct links, video, license, description, and contact information.
12. Preserve a final release tag and a short post-submission changelog; do not rewrite history after submission unless required by the competition.

### Exit condition

The project is publicly accessible, reproducible, documented, demonstrated in a sub-three-minute video, and formally submitted with the correct repository, deployment, license, and competition materials.

---

# FINAL DEMO SCRIPT

The finished demo should communicate one coherent argument:

```text
Blackout models a city under stress.
        ↓
An infrastructure failure propagates through dependencies.
        ↓
The system identifies what matters most.
        ↓
Nemotron investigates the verified city state.
        ↓
OR-Tools allocates limited emergency resources.
        ↓
Blackout simulates the recommended intervention.
        ↓
The counterfactual proves whether the response helped.
```

Suggested closing line:

> **Disasters are unpredictable. Their consequences do not have to be.**

---

# DO NOT BUILD BEFORE SUBMISSION

These are intentionally deferred because they create scope risk without improving the core judging story:

- real-time external weather or utility feeds
- multiple cities
- authentication and user accounts
- Kubernetes or elaborate cloud infrastructure
- complex ML training
- real PG&E grid reconstruction
- earthquake physics or realistic traffic simulation
- mobile application
- elaborate RAG pipelines
- multiple simultaneous LLM providers in the live demo
- five disaster types
- production claims or operational emergency-management guarantees

If the core demo is already stable and there is genuine time remaining, consider only one stretch feature at a time: a second scenario, a user-selected initial failure, sensitivity analysis, Monte Carlo runs, or human override of the AI recommendation.

---

# RELEASE CHECKLIST

- [ ] Clean checkout starts successfully.
- [ ] `GET /api/health` returns 200.
- [ ] City data validates and loads.
- [ ] Dependency graph traverses correctly.
- [ ] Scenario starts and resets reproducibly.
- [ ] Cascade timeline is deterministic.
- [ ] Map displays and animates node statuses.
- [ ] Risk ranking is explainable.
- [ ] Cascade explorer shows causal paths.
- [ ] Manual interventions validate and apply.
- [ ] OR-Tools or the documented fallback produces feasible plans.
- [ ] Counterfactual replay demonstrates measurable improvement.
- [ ] AI provider abstraction works with a fake provider.
- [ ] Nemotron/Nebius path works or has a tested fallback.
- [ ] Tool calls are logged and visible.
- [ ] Communications use verified simulator state.
- [ ] Production deployment passes smoke tests.
- [ ] README, architecture diagram, license, and screenshots are complete.
- [ ] Video is at or under three minutes.
- [ ] Final submission links and metadata are correct.

