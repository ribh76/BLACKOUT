import assert from "node:assert/strict";
import { Buffer } from "node:buffer";
import { readFileSync } from "node:fs";
import test from "node:test";
import { URL } from "node:url";
import ts from "typescript";

const source = readFileSync(
  new URL("../src/playback.ts", import.meta.url),
  "utf8",
);
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const {
  applyPlaybackStep,
  buildPlaybackSteps,
  currentMetrics,
  traceCausalSequence,
} = await import(
  `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`
);

test("traces recorded multi-hop causes without using later events", () => {
  const transitions = [
    {
      ...event(0, "STATUS_TRANSITION", "FAILED", "initial outage"),
      node_id: "grid",
      source_node_id: null,
    },
    {
      ...event(30, "STATUS_TRANSITION", "DEGRADED", "grid pressure"),
      node_id: "road",
      source_node_id: "grid",
    },
    {
      ...event(60, "STATUS_TRANSITION", "CRITICAL", "access lost"),
      node_id: "hospital",
      source_node_id: "road",
    },
    {
      ...event(90, "STATUS_TRANSITION", "FAILED", "later grid event"),
      node_id: "grid",
      source_node_id: null,
    },
  ];
  assert.deepEqual(
    traceCausalSequence(transitions, "hospital").map((item) => item.node_id),
    ["grid", "road", "hospital"],
  );
  assert.deepEqual(traceCausalSequence(transitions, "missing"), []);
});

const baseNode = {
  id: "hub",
  name: "Grid hub",
  type: "SUBSTATION",
  status: "OPERATIONAL",
  coordinates: { latitude: 37.33, longitude: -121.89 },
  criticality: 0.9,
  population_served: 1000,
  backup_remaining: 10,
  current_load: 80,
};
const event = (elapsed_minutes, kind, new_status, cause) => ({
  elapsed_minutes,
  time: "2026-07-15T14:00:00-07:00",
  kind,
  node_id: "hub",
  old_status: "OPERATIONAL",
  new_status,
  cause,
  explanation: cause,
});

test("plays initial failure, later events, then tick snapshots in clock order", () => {
  const result = {
    scenario_id: "example",
    states: [
      {
        elapsed_minutes: 30,
        city_state: {
          nodes: [{ ...baseNode, status: "DEGRADED", backup_remaining: 4 }],
        },
      },
      {
        elapsed_minutes: 0,
        city_state: { nodes: [{ ...baseNode, status: "FAILED" }] },
      },
    ],
    events: [
      event(30, "BACKUP_ACTIVATED", "OPERATIONAL", "backup came online"),
      event(0, "STATUS_TRANSITION", "FAILED", "initial outage"),
      event(30, "STATUS_TRANSITION", "DEGRADED", "grid pressure"),
    ],
  };
  const steps = buildPlaybackSteps(result);
  assert.deepEqual(
    steps.map(
      (step) =>
        `${step.elapsed_minutes}:${step.kind === "event" ? step.event.cause : "snapshot"}`,
    ),
    [
      "0:initial outage",
      "0:snapshot",
      "30:backup came online",
      "30:grid pressure",
      "30:snapshot",
    ],
  );
  let nodes = [baseNode];
  nodes = applyPlaybackStep(nodes, steps[0]);
  assert.equal(nodes[0].status, "FAILED");
  nodes = applyPlaybackStep(nodes, steps[1]);
  nodes = applyPlaybackStep(nodes, steps[2]);
  assert.equal(nodes[0].status, "FAILED");
  nodes = applyPlaybackStep(nodes, steps[3]);
  assert.equal(nodes[0].status, "DEGRADED");
  assert.equal(nodes[0].backup_remaining, 4);
  nodes = applyPlaybackStep(nodes, steps[4]);
  assert.equal(nodes[0].backup_remaining, 4);
});

test("rejects events that cannot be placed before the final snapshot", () => {
  assert.throws(
    () =>
      buildPlaybackSteps({
        scenario_id: "example",
        states: [{ elapsed_minutes: 0, city_state: { nodes: [baseNode] } }],
        events: [event(30, "STATUS_TRANSITION", "FAILED", "late event")],
      }),
    /beyond the final state/,
  );
});

test("plays intervention restoration at the recorded event", () => {
  const step = {
    kind: "event",
    elapsed_minutes: 60,
    event: {
      ...event(60, "INTERVENTION_COMPLETED", "OPERATIONAL", "repair"),
      old_status: "FAILED",
      intervention_id: "repair-1",
    },
    node_state: { ...baseNode, status: "OPERATIONAL" },
  };
  const updated = applyPlaybackStep([{ ...baseNode, status: "FAILED" }], step);
  assert.equal(updated[0].status, "OPERATIONAL");
});

test("current metrics follow the backend neighborhood and facility rules", () => {
  const nodes = [
    { ...baseNode, status: "FAILED", type: "SUBSTATION" },
    {
      ...baseNode,
      id: "east",
      status: "DEGRADED",
      type: "NEIGHBORHOOD",
      population_served: 1200,
    },
    {
      ...baseNode,
      id: "west",
      status: "OPERATIONAL",
      type: "NEIGHBORHOOD",
      population_served: 3000,
    },
    { ...baseNode, id: "route", status: "CRITICAL", type: "EMERGENCY_ROUTE" },
  ];
  assert.deepEqual(currentMetrics(nodes), {
    affectedPopulation: 1200,
    criticalFacilities: 1,
    failedInfrastructure: 1,
  });
});
