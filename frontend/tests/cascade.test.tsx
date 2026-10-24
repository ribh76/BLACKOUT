import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { JSDOM } from "jsdom";
import { CascadeExplorerContent } from "../src/CascadeExplorer.tsx";
import { explainAsset, flattenCascadeTree } from "../src/cascade.ts";
import type { CascadeResponse } from "../src/cascade.ts";
import { traceCausalSequence } from "../src/playback.ts";
import type { InfrastructureNode, SimulationEvent } from "../src/playback.ts";

const hospital: InfrastructureNode = {
  id: "hospital",
  name: "Hospital A",
  type: "HOSPITAL",
  status: "CRITICAL",
  coordinates: { latitude: 37.3, longitude: -121.9 },
  criticality: 1,
  population_served: 1000,
  current_load: 100,
  backup_capacity: 300,
  backup_remaining: 210,
};
const transition: SimulationEvent = {
  elapsed_minutes: 60,
  time: "2026-07-15T15:00:00-07:00",
  kind: "STATUS_TRANSITION",
  node_id: hospital.id,
  old_status: "DEGRADED",
  new_status: "CRITICAL",
  cause: "DEPENDENCY_PRESSURE",
  source_node_id: "grid",
  explanation: "Providers deteriorated.",
  dependency_causes: [
    {
      provider_id: "grid",
      provider_status: "FAILED",
      dependency_type: "POWER",
      weight: 0.98,
      contribution: 0.4,
    },
    {
      provider_id: "road",
      provider_status: "CRITICAL",
      dependency_type: "ACCESS",
      weight: 0.8,
      contribution: 0.5,
    },
  ],
};
const empty: CascadeResponse = {
  node_id: hospital.id,
  provider_edges: [],
  dependent_edges: [],
  downstream_tree: [],
  impact: { affected_population: 0, critical_facility_count: 0 },
};

test("explanation uses current status, all recorded causes, and reserve duration", () => {
  const explanation = explainAsset(hospital, [hospital], [transition]);
  assert.match(explanation, /Hospital A is currently critical/);
  assert.match(explanation, /power pressure from grid \(was failed, 98%/);
  assert.match(explanation, /access pressure from road \(was critical, 80%/);
  assert.match(explanation, /2\.1 hours at current load/);
  assert.match(
    explainAsset({ ...hospital, backup_remaining: 0 }, [], []),
    /reserve is exhausted/,
  );
  assert.match(
    explainAsset(
      { ...hospital, backup_capacity: 0, backup_remaining: 0 },
      [],
      [],
    ),
    /No backup capacity/,
  );
  assert.match(
    explainAsset({ ...hospital, current_load: 0 }, [], []),
    /cannot be estimated at zero load/,
  );
  const recovered = explainAsset(
    { ...hospital, status: "OPERATIONAL" },
    [],
    [transition],
  );
  assert.match(recovered, /currently operational/);
  assert.doesNotMatch(recovered, /power pressure|currently critical/);
});

test("multiple recorded causes form branches and missing source events stay unresolved", () => {
  const roots = ["grid", "road"].map((id): SimulationEvent => ({
    ...transition,
    node_id: id,
    elapsed_minutes: 0,
    new_status: "FAILED",
    source_node_id: null,
    dependency_causes: [],
  }));
  assert.deepEqual(
    traceCausalSequence([...roots, transition], hospital.id).map(
      (e) => e.node_id,
    ),
    ["grid", "road", "hospital"],
  );
  assert.deepEqual(traceCausalSequence([transition], hospital.id), [
    transition,
  ]);
});

test("causal tracing uses the previous tick and stops at a provider recovery", () => {
  const source = {
    ...transition,
    node_id: "grid",
    elapsed_minutes: 0,
    new_status: "DEGRADED" as const,
    source_node_id: null,
    dependency_causes: [],
  };
  const concurrent = {
    ...source,
    elapsed_minutes: 60,
    new_status: "FAILED" as const,
  };
  assert.equal(
    traceCausalSequence([source, concurrent, transition], hospital.id)[0]
      .new_status,
    "DEGRADED",
  );
  const recovery = {
    ...source,
    elapsed_minutes: 30,
    new_status: "OPERATIONAL" as const,
  };
  assert.deepEqual(
    traceCausalSequence([source, recovery, transition], hospital.id),
    [transition],
  );
});

test("isolated, missing, and long paths render without losing nodes or indentation space", () => {
  const render = (cascade: CascadeResponse) =>
    new JSDOM(
      renderToStaticMarkup(
        <CascadeExplorerContent
          selectedNode={hospital}
          nodes={[hospital]}
          cascade={cascade}
          events={[transition]}
          causalEvents={[transition]}
          onSelect={() => {}}
          onClear={() => {}}
        />,
      ),
    ).window.document;
  assert.match(
    render(empty).body.textContent ?? "",
    /No direct providers.*No direct dependents.*No downstream assets/s,
  );
  const tree = Array.from({ length: 1200 }, (_, i) => ({
    node_id: `node-${i}`,
    parent_id: i ? `node-${i - 1}` : hospital.id,
    depth: i + 1,
    edge: {
      provider_id: i ? `node-${i - 1}` : hospital.id,
      dependent_id: `node-${i}`,
      dependency_type: "POWER" as const,
      weight: 0.8,
      failure_delay_minutes: 15,
    },
  }));
  const cascade = { ...empty, downstream_tree: tree };
  assert.equal(flattenCascadeTree(cascade).length, 1200);
  const long = render(cascade);
  assert.equal(long.querySelectorAll(".cascade-tree li").length, 1200);
  assert.equal(
    long.querySelector('[data-depth="1200"]')?.getAttribute("style"),
    "margin-left:40px",
  );
  const missing = render({
    ...empty,
    downstream_tree: [{ ...tree[0], parent_id: "missing" }],
  });
  assert.match(missing.body.textContent ?? "", /Some paths are unavailable/);
  assert.match(missing.body.textContent ?? "", /Source events unavailable/);
});
