import assert from "node:assert/strict";
import test from "node:test";
import { JSDOM } from "jsdom";
import React, { act } from "react";

const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  url: "http://localhost:5173/",
  pretendToBeVisual: true,
});
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  SVGElement: dom.window.SVGElement,
  Element: dom.window.Element,
  Node: dom.window.Node,
  requestAnimationFrame: dom.window.requestAnimationFrame.bind(dom.window),
  cancelAnimationFrame: dom.window.cancelAnimationFrame.bind(dom.window),
  IS_REACT_ACT_ENVIRONMENT: true,
});
Object.defineProperty(globalThis, "navigator", {
  value: dom.window.navigator,
  configurable: true,
});
Object.defineProperty(dom.window.HTMLElement.prototype, "clientWidth", {
  get: () => 800,
});
Object.defineProperty(dom.window.HTMLElement.prototype, "clientHeight", {
  get: () => 520,
});
const { createRoot } = await import("react-dom/client");
const { App } = await import("../src/App.tsx");

const node = (id: string, type = "SUBSTATION", status = "OPERATIONAL") => ({
  id,
  name: id === "hub" ? "Grid hub" : "East neighborhood",
  type,
  status,
  coordinates: { latitude: id === "hub" ? 37.33 : 37.35, longitude: -121.89 },
  criticality: 0.9,
  population_served: id === "hub" ? 1000 : 1200,
  backup_remaining: 10,
  current_load: 80,
});
const originalNodes = [node("hub"), node("east", "NEIGHBORHOOD")];
const snapshot = {
  city: "San Jose",
  data_notice: "Synthetic data",
  count: 2,
  capacity_units: { SUBSTATION: "MW", NEIGHBORHOOD: "residents" },
  nodes: originalNodes,
};
const event = (
  elapsed_minutes: number,
  node_id: string,
  old_status: string,
  new_status: string,
) => ({
  elapsed_minutes,
  time: "2026-07-15T14:00:00-07:00",
  kind: "STATUS_TRANSITION",
  node_id,
  old_status,
  new_status,
  cause: "GRID_PRESSURE",
  explanation: "Grid pressure spread.",
});
const result = {
  scenario_id: "extreme-heat-grid-failure",
  states: [
    {
      elapsed_minutes: 0,
      city_state: {
        nodes: [node("hub", "SUBSTATION", "FAILED"), originalNodes[1]],
      },
    },
    {
      elapsed_minutes: 30,
      city_state: {
        nodes: [
          node("hub", "SUBSTATION", "FAILED"),
          node("east", "NEIGHBORHOOD", "DEGRADED"),
        ],
      },
    },
  ],
  events: [
    event(30, "east", "OPERATIONAL", "DEGRADED"),
    event(0, "hub", "OPERATIONAL", "FAILED"),
  ],
  final_metrics: { system_risk_score: null },
};
const response = (body: unknown, ok = true, status = 200) => ({
  ok,
  status,
  json: async () => body,
});
const deferred = () => {
  let resolve!: (value: ReturnType<typeof response>) => void;
  const promise = new Promise<ReturnType<typeof response>>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};
async function mount(fetchImpl: typeof fetch) {
  globalThis.fetch = fetchImpl;
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<App />);
    await Promise.resolve();
  });
  return {
    container,
    async cleanup() {
      await act(async () => root.unmount());
      container.remove();
    },
  };
}
async function click(element: Element | null) {
  assert.ok(element, "expected clickable element");
  await act(async () => {
    (element as HTMLElement).click();
    await Promise.resolve();
  });
}
async function settle() {
  await act(async () => {
    await new Promise((done) => setTimeout(done, 0));
  });
}
function button(container: Element, name: string) {
  return (
    [...container.querySelectorAll("button")].find((item) =>
      item.textContent?.includes(name),
    ) ?? null
  );
}

test("renders API nodes on the map and shows selected details", async () => {
  const app = await mount(async () => response(snapshot) as Response);
  try {
    assert.equal(
      app.container.querySelectorAll(".leaflet-marker-icon").length,
      2,
    );
    assert.match(app.container.textContent ?? "", /Grid hub/);
    await click(app.container.querySelector('[title*="East neighborhood"]'));
    assert.match(
      app.container.querySelector(".detail-panel")?.textContent ?? "",
      /East neighborhood/,
    );
    assert.match(
      app.container.querySelector(".metrics-grid")?.textContent ?? "",
      /PEOPLE AFFECTED0/,
    );
  } finally {
    await app.cleanup();
  }
});

test("shows events in time order and updates metrics with playback", async () => {
  const app = await mount(
    async (input) =>
      response(
        String(input).endsWith("/simulate") ? result : snapshot,
      ) as Response,
  );
  try {
    await click(button(app.container, "SIMULATE BLACKOUT"));
    for (let step = 0; step < 4; step += 1) {
      await act(async () => {
        await new Promise((done) => setTimeout(done, 650));
      });
    }
    const feed = app.container.querySelectorAll(".event-list li");
    assert.equal(feed.length, 2);
    assert.match(
      feed[0].textContent ?? "",
      /T\+0.*Grid hub.*operational → failed.*grid pressure/is,
    );
    assert.match(
      feed[1].textContent ?? "",
      /T\+30.*East neighborhood.*operational → degraded.*grid pressure/is,
    );
    const metrics =
      app.container.querySelector(".metrics-grid")?.textContent ?? "";
    assert.match(metrics, /1,200/);
    assert.match(metrics, /Not scored/);
  } finally {
    await app.cleanup();
  }
});

test("reset ignores a late simulation response and prevents duplicate runs", async () => {
  const pending = deferred();
  let simulateCalls = 0;
  let resetCalls = 0;
  const app = await mount(async (input) => {
    if (String(input).endsWith("/simulate")) {
      simulateCalls += 1;
      return pending.promise as Promise<Response>;
    }
    if (String(input).endsWith("/reset")) {
      resetCalls += 1;
      return response({ nodes: originalNodes }) as Response;
    }
    return response(snapshot) as Response;
  });
  try {
    const run = button(app.container, "SIMULATE BLACKOUT");
    assert.ok(run);
    await act(async () => {
      run.click();
      run.click();
      await Promise.resolve();
    });
    assert.equal(simulateCalls, 1);
    await click(button(app.container, "Reset"));
    pending.resolve(response(result));
    await settle();
    assert.equal(resetCalls, 1);
    assert.equal(app.container.querySelectorAll(".event-list li").length, 0);
    assert.match(
      app.container.querySelector(".clock")?.textContent ?? "",
      /T\+0/,
    );
    assert.match(
      app.container.querySelector(".metrics-grid")?.textContent ?? "",
      /FAILED INFRASTRUCTURE0/,
    );
  } finally {
    await app.cleanup();
  }
});

test("reset during playback clears queued events before a fresh run", async () => {
  const app = await mount(async (input) => {
    if (String(input).endsWith("/simulate"))
      return response(result) as Response;
    if (String(input).endsWith("/reset"))
      return response({ nodes: originalNodes }) as Response;
    return response(snapshot) as Response;
  });
  try {
    await click(button(app.container, "SIMULATE BLACKOUT"));
    await act(async () => {
      await new Promise((done) => setTimeout(done, 650));
    });
    assert.equal(app.container.querySelectorAll(".event-list li").length, 1);
    await click(button(app.container, "Reset"));
    await act(async () => {
      await new Promise((done) => setTimeout(done, 700));
    });
    assert.equal(app.container.querySelectorAll(".event-list li").length, 0);
    assert.match(
      app.container.querySelector(".metrics-grid")?.textContent ?? "",
      /FAILED INFRASTRUCTURE0/,
    );
    await click(button(app.container, "SIMULATE BLACKOUT"));
    await act(async () => {
      await new Promise((done) => setTimeout(done, 650));
    });
    assert.equal(app.container.querySelectorAll(".event-list li").length, 1);
  } finally {
    await app.cleanup();
  }
});

test("shows API failures and permits retry with a clean state", async () => {
  let failures = 0;
  const app = await mount(async (input) => {
    if (String(input).endsWith("/simulate")) {
      failures += 1;
      return response({}, false, 503) as Response;
    }
    return response(snapshot) as Response;
  });
  try {
    await click(button(app.container, "SIMULATE BLACKOUT"));
    assert.match(
      app.container.querySelector('[role="alert"]')?.textContent ?? "",
      /503/,
    );
    assert.equal(app.container.querySelectorAll(".event-list li").length, 0);
    await click(button(app.container, "SIMULATE BLACKOUT"));
    assert.equal(failures, 2);
  } finally {
    await app.cleanup();
  }
});

test("shows an infrastructure load error and recovers on retry", async () => {
  let loads = 0;
  const app = await mount(async () => {
    loads += 1;
    return loads === 1
      ? (response({}, false, 503) as Response)
      : (response(snapshot) as Response);
  });
  try {
    assert.match(
      app.container.querySelector('[role="alert"]')?.textContent ?? "",
      /503/,
    );
    await click(button(app.container, "Retry"));
    assert.equal(loads, 2);
    assert.equal(
      app.container.querySelectorAll(".leaflet-marker-icon").length,
      2,
    );
  } finally {
    await app.cleanup();
  }
});
