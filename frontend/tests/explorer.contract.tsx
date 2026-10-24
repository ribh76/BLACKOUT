import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { JSDOM } from "jsdom";
import { CascadeExplorerContent } from "../src/CascadeExplorer.tsx";
import type { CascadeResponse, DependencyEdge } from "../src/cascade.ts";
import { traceCausalSequence } from "../src/playback.ts";
import type { InfrastructureNode, SimulationEvent } from "../src/playback.ts";

test("frontend traversal and labels match fresh backend API and simulator output", () => {
  const python =
    process.env.BLACKOUT_TEST_PYTHON ??
    fileURLToPath(new URL("../../.venv/bin/python", import.meta.url));
  const backend = fileURLToPath(new URL("../../backend/", import.meta.url));
  const data = JSON.parse(
    execFileSync(python, ["tests/export_explorer_contract.py"], {
      cwd: backend,
      env: { ...process.env, PYTHONPATH: backend },
      encoding: "utf8",
      maxBuffer: 5_000_000,
    }),
  ) as {
    edges: DependencyEdge[];
    cascades: Record<string, CascadeResponse>;
    states: { nodes: InfrastructureNode[]; events: SimulationEvent[] }[];
  };
  const document = new JSDOM("<body></body>").window.document;
  for (const state of data.states) {
    for (const node of state.nodes) {
      const cascade = data.cascades[node.id];
      const distances = new Map([[node.id, 0]]);
      const queue = [node.id];
      for (let i = 0; i < queue.length; i++) {
        for (const edge of data.edges.filter(
          (edge) => edge.provider_id === queue[i],
        )) {
          if (!distances.has(edge.dependent_id)) {
            distances.set(edge.dependent_id, distances.get(queue[i])! + 1);
            queue.push(edge.dependent_id);
          }
        }
      }
      document.body.innerHTML = renderToStaticMarkup(
        <CascadeExplorerContent
          selectedNode={node}
          nodes={state.nodes}
          cascade={cascade}
          events={state.events}
          causalEvents={traceCausalSequence(state.events, node.id)}
          onSelect={() => {}}
          onClear={() => {}}
        />,
      );
      const rows = [...document.querySelectorAll(".cascade-tree li")];
      assert.equal(rows.length, distances.size - 1);
      for (const row of rows) {
        const id = row.getAttribute("data-node-id")!;
        assert.equal(Number(row.getAttribute("data-depth")), distances.get(id));
        const downstream = state.nodes.find((item) => item.id === id)!;
        assert.ok(
          row.textContent?.includes(
            `currently ${downstream.status.toLowerCase()}`,
          ),
        );
      }
      assert.ok(
        document
          .querySelector(".cascade-explanation")
          ?.textContent?.startsWith(
            `${node.name} is currently ${node.status.toLowerCase()}.`,
          ),
      );
      assert.equal(
        cascade.provider_edges.length,
        data.edges.filter((edge) => edge.dependent_id === node.id).length,
      );
      const downstream = state.nodes.filter(
        (item) => item.id !== node.id && distances.has(item.id),
      );
      const population = downstream
        .filter(
          (item) =>
            item.type === "NEIGHBORHOOD" && item.status !== "OPERATIONAL",
        )
        .reduce((sum, item) => sum + item.population_served, 0);
      const facilities = downstream.filter(
        (item) =>
          [
            "SUBSTATION",
            "HOSPITAL",
            "PHARMACY",
            "SHELTER",
            "COOLING_CENTER",
          ].includes(item.type) && item.status !== "OPERATIONAL",
      ).length;
      assert.ok(
        document
          .querySelector(".cascade-impact")
          ?.textContent?.includes(
            `Currently impaired downstream: ${population.toLocaleString()} residents · ${facilities} critical facilities.`,
          ),
      );
      if (
        node.backup_capacity > 0 &&
        node.backup_remaining > 0 &&
        node.current_load > 0
      ) {
        assert.ok(
          document
            .querySelector(".cascade-explanation")
            ?.textContent?.includes(
              `${(node.backup_remaining / node.current_load).toFixed(1)} hours at current load`,
            ),
        );
      }
    }
  }
});
