import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";
import React, { act } from "react";
import { JSDOM } from "jsdom";
import { ResponsePlanPanel } from "../src/ResponsePlanPanel.tsx";
import type { PlanningCityState, ResponsePlan } from "../src/optimization";

const dom = new JSDOM("<!doctype html><body></body>", {
  url: "http://localhost:5173",
});
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  IS_REACT_ACT_ENVIRONMENT: true,
});
const { createRoot } = await import("react-dom/client");
const backend = fileURLToPath(new URL("../../backend/", import.meta.url));
const python =
  process.env.BLACKOUT_TEST_PYTHON ??
  fileURLToPath(new URL("../../.venv/bin/python", import.meta.url));
const contract = JSON.parse(
  execFileSync(python, ["tests/export_optimization_contract.py"], {
    cwd: backend,
    env: { ...process.env, PYTHONPATH: backend },
    encoding: "utf8",
    maxBuffer: 5_000_000,
  }),
) as { state: PlanningCityState; plan: ResponsePlan; empty_plan: ResponsePlan };
const response = (payload: unknown, ok = true) =>
  ({ ok, status: ok ? 200 : 503, json: async () => payload }) as Response;
const deferred = () => {
  let resolve!: (response: Response) => void;
  const promise = new Promise<Response>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};
async function mount(fetchImpl: typeof fetch) {
  globalThis.fetch = fetchImpl;
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  let cityState = contract.state,
    disabled = false;
  let selected: string | null = null;
  async function render() {
    await act(async () => {
      root.render(
        <ResponsePlanPanel
          cityState={cityState}
          elapsedMinutes={0}
          disabled={disabled}
          apiUrl="http://localhost:8000"
          onSelect={(id) => {
            selected = id;
          }}
        />,
      );
    });
  }
  await render();
  return {
    container,
    selected: () => selected,
    async update(state: PlanningCityState, busy = false) {
      cityState = state;
      disabled = busy;
      await render();
    },
    async cleanup() {
      await act(async () => root.unmount());
      container.remove();
    },
  };
}
async function click(element: Element | null) {
  assert.ok(element);
  await act(async () => {
    (element as HTMLElement).click();
  });
}
const generate = (container: Element) =>
  [...container.querySelectorAll("button")].find((b) =>
    b.textContent?.includes("PLAN"),
  )!;

test("renders fresh backend plan and sends complete current state", async () => {
  let body: unknown;
  const app = await mount(async (url, options) => {
    assert.match(String(url), /optimization\/plan$/);
    body = JSON.parse(String(options?.body));
    return response(contract.plan);
  });
  try {
    await click(generate(app.container));
    assert.deepEqual(
      (body as { current_city_state: unknown }).current_city_state,
      contract.state,
    );
    const rows = [...app.container.querySelectorAll(".plan-actions > li")];
    assert.equal(rows.length, contract.plan.selected_candidates.length);
    for (const [index, action] of contract.plan.selected_candidates.entries()) {
      const name = contract.state.nodes.find(
        (n) => n.id === action.intervention.target_node_id,
      )!.name;
      assert.ok(rows[index].textContent?.includes(name));
      assert.equal(rows[index].getAttribute("value"), String(action.rank));
      assert.ok(
        rows[index].textContent?.includes(
          `Effect T+${action.time_to_effect_minutes}`,
        ),
      );
    }
    assert.equal(app.container.querySelectorAll("tbody tr").length, 6);
    for (const [index, resource] of Object.keys(
      contract.plan.resource_utilization,
    ).entries()) {
      const row = app.container.querySelectorAll("tbody tr").item(index);
      const cells = row.querySelectorAll("td");
      const key = resource as keyof typeof contract.plan.resource_utilization;
      assert.equal(
        cells[0].textContent,
        String(contract.plan.resource_utilization[key]),
      );
      assert.equal(
        cells[2].textContent,
        String(contract.plan.remaining_resources[key]),
      );
    }
    assert.ok(
      app.container.textContent?.includes(
        contract.plan.plan_benefit.expected_risk_reduction.toFixed(2),
      ),
    );
    assert.match(app.container.textContent ?? "", /Rejected alternatives/);
    assert.ok(
      app.container.querySelector("a")?.href.endsWith(contract.plan.run_id),
    );
    await click(app.container.querySelector(".plan-target"));
    assert.equal(
      app.selected(),
      contract.plan.selected_candidates[0].intervention.target_node_id,
    );
  } finally {
    await app.cleanup();
  }
});

test("prevents duplicate requests and ignores stale results after state changes", async () => {
  const pending = deferred();
  let calls = 0;
  const app = await mount(async () => {
    calls++;
    return pending.promise;
  });
  try {
    await click(generate(app.container));
    assert.equal(generate(app.container).disabled, true);
    await click(generate(app.container));
    assert.equal(calls, 1);
    assert.match(
      app.container.querySelector('[role="status"]')?.textContent ?? "",
      /Evaluating/,
    );
    await app.update({
      ...contract.state,
      nodes: contract.state.nodes.map((n) => ({ ...n })),
    });
    await act(async () => pending.resolve(response(contract.plan)));
    assert.equal(app.container.querySelector(".plan-actions"), null);
    assert.equal(generate(app.container).disabled, false);
  } finally {
    await app.cleanup();
  }
});

test("shows errors, retries, and explains empty plans", async () => {
  let calls = 0;
  const app = await mount(async () =>
    ++calls === 1
      ? response({ detail: "Unable to record optimization run" }, false)
      : response(contract.empty_plan),
  );
  try {
    await click(generate(app.container));
    assert.match(
      app.container.querySelector('[role="alert"]')?.textContent ?? "",
      /Unable to record/,
    );
    await click(generate(app.container));
    assert.equal(app.container.querySelector('[role="alert"]'), null);
    assert.match(
      app.container.querySelector(".plan-empty")?.textContent ?? "",
      /No beneficial actions/,
    );
    await app.update(contract.state, true);
    assert.equal(generate(app.container).disabled, true);
  } finally {
    await app.cleanup();
  }
});
