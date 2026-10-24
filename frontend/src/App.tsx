import React, { useCallback, useEffect, useRef, useState } from "react";
import L from "leaflet";
import {
  applyPlaybackStep,
  buildPlaybackSteps,
  currentMetrics,
} from "./playback";
import type {
  InfrastructureNode,
  InfrastructureSnapshot,
  InfrastructureType,
  NodeStatus,
  PlaybackStep,
  SimulationEvent,
  SimulationResult,
} from "./playback";

const apiUrl = import.meta.env?.VITE_API_URL ?? "http://localhost:8000";
const mapboxToken = import.meta.env?.VITE_MAPBOX_ACCESS_TOKEN;
const SAN_JOSE: L.LatLngExpression = [37.3355, -121.89];
const SAN_JOSE_BOUNDS = L.latLngBounds([37.225, -121.965], [37.422, -121.805]);
const statusColors = {
  OPERATIONAL: "#42c6b2",
  DEGRADED: "#f3cb54",
  CRITICAL: "#f28b48",
  FAILED: "#e85a62",
} as const;
type PlaybackPhase =
  "idle" | "loading" | "running" | "paused" | "complete" | "resetting";
const SCENARIO_ID = "extreme-heat-grid-failure";
const STEP_DELAY_MS = 600;
const typeLabels: Record<InfrastructureType, string> = {
  SUBSTATION: "Substation",
  HOSPITAL: "Hospital",
  INTERSECTION: "Intersection",
  PHARMACY: "Pharmacy",
  SHELTER: "Shelter",
  COOLING_CENTER: "Cooling center",
  WAREHOUSE: "Warehouse",
  NEIGHBORHOOD: "Neighborhood",
  EMERGENCY_ROUTE: "Emergency route",
};
// Each asset type has a distinct pictogram, independent of its status color.
const typeSymbols: Record<InfrastructureType, string> = {
  SUBSTATION: '<path d="M14 2 6 13h6l-2 9 8-12h-6l2-8Z"/>',
  HOSPITAL: '<path d="M10 3h4v7h7v4h-7v7h-4v-7H3v-4h7V3Z"/>',
  INTERSECTION:
    '<path d="M10 2h4v8h8v4h-8v8h-4v-8H2v-4h8V2Z"/><circle cx="12" cy="12" r="2" fill="currentColor"/>',
  PHARMACY:
    '<path d="M7 4a4 4 0 0 1 5 0l8 8a4 4 0 0 1-6 6L6 10a4 4 0 0 1 1-6Z"/><path d="m9 13 4-4" fill="none" stroke="currentColor" stroke-width="2"/>',
  SHELTER:
    '<path d="m2 11 10-8 10 8v10H2V11Z"/><path d="M10 21v-7h4v7" fill="none" stroke="currentColor" stroke-width="2"/>',
  COOLING_CENTER:
    '<path d="M12 2v20M2 12h20M5 5l14 14M19 5 5 19" fill="none" stroke="currentColor" stroke-width="2"/>',
  WAREHOUSE:
    '<path d="m2 9 10-6 10 6v12H2V9Z"/><path d="M7 21v-9h10v9M7 16h10" fill="none" stroke="currentColor" stroke-width="2"/>',
  NEIGHBORHOOD:
    '<path d="M2 10h6v11H2V10Zm7-7h7v18H9V3Zm8 9h5v9h-5v-9Z"/><path d="M4 13h2M11 7h3M11 11h3M19 15h1" fill="none" stroke="currentColor" stroke-width="1.5"/>',
  EMERGENCY_ROUTE:
    '<path d="M3 19h7v-5h5v-4h6" fill="none" stroke="currentColor" stroke-width="3"/><path d="m16 5 5 5-5 5" fill="none" stroke="currentColor" stroke-width="3"/>',
};
function symbol(type: InfrastructureType) {
  return `<svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">${typeSymbols[type]}</svg>`;
}
function markerIcon(node: InfrastructureNode, selected: boolean) {
  return L.divIcon({
    className: "asset-icon-wrap",
    html: `<span class="asset-icon${selected ? " asset-icon-selected" : ""}" style="--asset-color:${statusColors[node.status]}">${symbol(node.type)}</span>`,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
    popupAnchor: [0, -15],
  });
}
function CityMap({
  nodes,
  selectedId,
  onSelect,
}: {
  nodes: InfrastructureNode[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);
  useEffect(() => {
    if (!containerRef.current) return;
    const map = L.map(containerRef.current, {
      center: SAN_JOSE,
      zoom: 12,
      minZoom: 10,
      maxZoom: 17,
      zoomControl: false,
    });
    L.control.zoom({ position: "bottomright" }).addTo(map);
    if (mapboxToken) {
      L.tileLayer(
        `https://api.mapbox.com/styles/v1/mapbox/dark-v11/tiles/{z}/{x}/{y}?access_token=${encodeURIComponent(mapboxToken)}`,
        {
          tileSize: 512,
          zoomOffset: -1,
          maxZoom: 17,
          attribution:
            '&copy; <a href="https://www.mapbox.com/about/maps/">Mapbox</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        },
      ).addTo(map);
    } else {
      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 17,
        attribution:
          '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(map);
    }
    layerRef.current = L.layerGroup().addTo(map);
    const frame = requestAnimationFrame(() => {
      map.invalidateSize();
      map.fitBounds(SAN_JOSE_BOUNDS, {
        padding: [24, 24],
        maxZoom: 12,
        animate: false,
      });
    });
    return () => {
      cancelAnimationFrame(frame);
      map.remove();
      layerRef.current = null;
    };
  }, []);
  useEffect(() => {
    const layer = layerRef.current;
    if (!layer) return;
    layer.clearLayers();
    nodes.forEach((node) => {
      const marker = L.marker(
        [node.coordinates.latitude, node.coordinates.longitude],
        {
          icon: markerIcon(node, selectedId === node.id),
          title: `${node.name} — ${typeLabels[node.type]}, ${node.status.toLowerCase()}`,
        },
      );
      marker.on("click", () => onSelect(node.id));
      marker.addTo(layer);
    });
  }, [nodes, selectedId, onSelect]);
  return (
    <div
      ref={containerRef}
      className="city-map"
      aria-label="Map of San Jose infrastructure"
    />
  );
}
export function App() {
  const [snapshot, setSnapshot] = useState<InfrastructureSnapshot | null>(null);
  const [nodes, setNodes] = useState<InfrastructureNode[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [simulationError, setSimulationError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const [phase, setPhase] = useState<PlaybackPhase>("idle");
  const [elapsedMinutes, setElapsedMinutes] = useState(0);
  const [feed, setFeed] = useState<SimulationEvent[]>([]);
  const [steps, setSteps] = useState<PlaybackStep[]>([]);
  const [stepIndex, setStepIndex] = useState(0);
  const [finalRiskScore, setFinalRiskScore] = useState<number | null>(null);
  const generationRef = useRef(0);
  const requestRef = useRef<{
    kind: "simulate" | "reset";
    controller: AbortController;
  } | null>(null);
  const timerRef = useRef<number | null>(null);
  const feedListRef = useRef<HTMLOListElement>(null);

  useEffect(
    () => () => {
      generationRef.current += 1;
      requestRef.current?.controller.abort();
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    },
    [],
  );

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${apiUrl}/api/infrastructure`, { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error(`API returned ${response.status}`);
        return response.json() as Promise<InfrastructureSnapshot>;
      })
      .then((data) => {
        if (!Array.isArray(data.nodes))
          throw new Error("Invalid infrastructure response");
        setSnapshot(data);
        setNodes(data.nodes);
        setSelectedId((current) => current ?? data.nodes[0]?.id ?? null);
        setLoadError(null);
      })
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setLoadError(
          cause instanceof Error ? cause.message : "Unable to load city data",
        );
      });
    return () => controller.abort();
  }, [retryKey]);

  const runSimulation = async () => {
    if (
      !snapshot ||
      requestRef.current ||
      phase === "loading" ||
      phase === "running" ||
      phase === "paused" ||
      phase === "resetting"
    )
      return;
    const generation = ++generationRef.current;
    const controller = new AbortController();
    requestRef.current = { kind: "simulate", controller };
    setSimulationError(null);
    setPhase("loading");
    setNodes(snapshot.nodes);
    setElapsedMinutes(0);
    setFeed([]);
    setSteps([]);
    setStepIndex(0);
    setFinalRiskScore(null);
    try {
      const response = await fetch(
        `${apiUrl}/api/scenarios/${SCENARIO_ID}/simulate`,
        { method: "POST", signal: controller.signal },
      );
      if (!response.ok)
        throw new Error(`Simulation API returned ${response.status}`);
      const result = (await response.json()) as SimulationResult;
      if (
        !Array.isArray(result.events) ||
        !Array.isArray(result.states) ||
        result.states.length === 0 ||
        result.states.some(
          (state) => !Array.isArray(state.city_state?.nodes),
        ) ||
        result.scenario_id !== SCENARIO_ID
      ) {
        throw new Error("Invalid simulation response");
      }
      if (generation !== generationRef.current) return;
      const playback = buildPlaybackSteps(result);
      setFinalRiskScore(result.final_metrics?.system_risk_score ?? null);
      setSteps(playback);
      setPhase(playback.length ? "running" : "complete");
    } catch (cause: unknown) {
      if (generation !== generationRef.current || controller.signal.aborted)
        return;
      setSimulationError(
        cause instanceof Error ? cause.message : "Unable to run simulation",
      );
      setPhase("idle");
    } finally {
      if (requestRef.current?.controller === controller)
        requestRef.current = null;
    }
  };

  const resetSimulation = async () => {
    if (
      !snapshot ||
      phase === "resetting" ||
      requestRef.current?.kind === "reset"
    )
      return;
    const generation = ++generationRef.current;
    requestRef.current?.controller.abort();
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    const controller = new AbortController();
    requestRef.current = { kind: "reset", controller };
    setPhase("resetting");
    setSimulationError(null);
    setNodes(snapshot.nodes);
    setElapsedMinutes(0);
    setFeed([]);
    setSteps([]);
    setStepIndex(0);
    setFinalRiskScore(null);
    try {
      const response = await fetch(
        `${apiUrl}/api/scenarios/${SCENARIO_ID}/reset`,
        { method: "POST", signal: controller.signal },
      );
      if (!response.ok)
        throw new Error(`Reset API returned ${response.status}`);
      const result = (await response.json()) as { nodes: InfrastructureNode[] };
      if (!Array.isArray(result.nodes))
        throw new Error("Invalid reset response");
      if (generation !== generationRef.current) return;
      setNodes(result.nodes);
      setPhase("idle");
    } catch (cause: unknown) {
      if (generation !== generationRef.current || controller.signal.aborted)
        return;
      setSimulationError(
        cause instanceof Error ? cause.message : "Unable to reset simulation",
      );
      setPhase("idle");
    } finally {
      if (requestRef.current?.controller === controller)
        requestRef.current = null;
    }
  };

  useEffect(() => {
    if (phase !== "running") return;
    if (stepIndex >= steps.length) {
      setPhase("complete");
      return;
    }
    const generation = generationRef.current;
    const timer = window.setTimeout(() => {
      timerRef.current = null;
      if (generation !== generationRef.current) return;
      const step = steps[stepIndex];
      if (step.kind === "event") {
        setFeed((current) => [...current, step.event]);
      }
      setNodes((current) => applyPlaybackStep(current, step));
      setElapsedMinutes(step.elapsed_minutes);
      setStepIndex((current) => current + 1);
    }, STEP_DELAY_MS);
    timerRef.current = timer;
    return () => {
      window.clearTimeout(timer);
      if (timerRef.current === timer) timerRef.current = null;
    };
  }, [phase, stepIndex, steps]);

  useEffect(() => {
    if (phase === "running" && feedListRef.current) {
      feedListRef.current.scrollTop = feedListRef.current.scrollHeight;
    }
  }, [feed.length, phase]);

  const selectNode = useCallback((id: string) => setSelectedId(id), []);
  const pausePlayback = () => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = null;
    setPhase("paused");
  };
  const selectedNode = nodes.find((node) => node.id === selectedId) ?? null;
  const metrics = currentMetrics(nodes);
  const statuses = Object.keys(statusColors) as NodeStatus[];
  const types = Object.keys(typeLabels) as InfrastructureType[];
  const unit = selectedNode
    ? snapshot?.capacity_units[selectedNode.type]
    : undefined;
  const canRun =
    Boolean(snapshot) && (phase === "idle" || phase === "complete");
  const canReset = Boolean(snapshot) && phase !== "resetting";

  return (
    <main className="dashboard">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" />
          BLACKOUT<span className="brand-separator">/</span>
          <span className="brand-context">CITY VIEW</span>
        </div>
        <div className="location">
          <span className="location-dot" /> SAN JOSE, CALIFORNIA{" "}
          <span className="location-divider">•</span> SIMULATED NETWORK
        </div>
      </header>
      <section className="heading" aria-labelledby="page-title">
        <div>
          <p className="eyebrow">INFRASTRUCTURE MONITOR / 01</p>
          <h1 id="page-title">
            Watch the city change<span>.</span>
          </h1>
          <p className="intro">
            Run the deterministic blackout scenario and follow each change as it
            reaches the network.
          </p>
        </div>
        <div className="network-count">
          <span>NETWORK ASSETS</span>
          <strong>{snapshot?.count ?? "—"}</strong>
          <small>across 9 infrastructure types</small>
        </div>
      </section>
      <section className="simulation-controls" aria-label="Simulation controls">
        <div className="clock">
          <span>SIMULATION CLOCK</span>
          <strong>
            T+{elapsedMinutes}
            <small> MIN</small>
          </strong>
          <em>
            {phase === "loading"
              ? "Preparing cascade"
              : phase === "running"
                ? "Playing cascade"
                : phase === "paused"
                  ? "Paused"
                  : phase === "complete"
                    ? "Simulation complete"
                    : phase === "resetting"
                      ? "Resetting city"
                      : "Ready to simulate"}
          </em>
        </div>
        <div className="control-buttons">
          <button
            className="simulate-button"
            onClick={runSimulation}
            disabled={!canRun}
          >
            {phase === "loading" ? "SIMULATING…" : "SIMULATE BLACKOUT"}
          </button>
          {phase === "running" && (
            <button className="secondary-button" onClick={pausePlayback}>
              Pause
            </button>
          )}
          {phase === "paused" && (
            <button
              className="secondary-button"
              onClick={() => setPhase("running")}
            >
              Resume
            </button>
          )}
          <button
            className="secondary-button"
            onClick={resetSimulation}
            disabled={!canReset}
          >
            Reset
          </button>
        </div>
      </section>
      {simulationError && (
        <div className="error-banner" role="alert">
          {simulationError}
        </div>
      )}
      <section className="metrics-grid" aria-label="Current system metrics">
        <div className="metric-card">
          <span>PEOPLE AFFECTED</span>
          <strong>{metrics.affectedPopulation.toLocaleString()}</strong>
          <small>residents in impaired neighborhoods</small>
        </div>
        <div className="metric-card">
          <span>CRITICAL FACILITIES</span>
          <strong>{metrics.criticalFacilities}</strong>
          <small>critical or failed facilities</small>
        </div>
        <div className="metric-card">
          <span>FAILED INFRASTRUCTURE</span>
          <strong>{metrics.failedInfrastructure}</strong>
          <small>assets offline</small>
        </div>
        <div className="metric-card">
          <span>CURRENT SYSTEM RISK</span>
          <strong>
            {phase === "complete" && finalRiskScore !== null
              ? `${Math.round(finalRiskScore * 100)}%`
              : "Not scored"}
          </strong>
          <small>
            {phase === "complete" && finalRiskScore !== null
              ? "backend risk score"
              : "risk engine pending"}
          </small>
        </div>
      </section>
      <section
        className="workspace"
        aria-label="Infrastructure map and details"
      >
        <div className="map-panel">
          <div className="map-topline">
            <span>01 / GEOGRAPHIC OVERVIEW</span>
            <span>37.3355° N &nbsp; 121.8900° W</span>
          </div>
          <CityMap
            nodes={nodes}
            selectedId={selectedId}
            onSelect={selectNode}
          />
          {!snapshot && (
            <div className="map-message" role={loadError ? "alert" : "status"}>
              {loadError ? (
                <>
                  City data unavailable: {loadError}
                  <button onClick={() => setRetryKey((key) => key + 1)}>
                    Retry
                  </button>
                </>
              ) : (
                "Loading infrastructure…"
              )}
            </div>
          )}
          <div className="map-bottomline">
            <span>SELECT A SYMBOL TO INSPECT AN ASSET</span>
            <span>SIMULATED LOCATIONS</span>
          </div>
        </div>
        <aside className="side-panel" aria-label="Asset details and map legend">
          <section className="detail-panel" aria-label="Node details">
            <p className="eyebrow">SELECTED ASSET</p>
            {selectedNode ? (
              <>
                <h2>{selectedNode.name}</h2>
                <div className="detail-status">
                  <span
                    className="status-swatch"
                    style={{
                      backgroundColor: statusColors[selectedNode.status],
                    }}
                  />
                  {selectedNode.status.toLowerCase()}
                </div>
                <dl className="detail-list">
                  <div>
                    <dt>Type</dt>
                    <dd>{typeLabels[selectedNode.type]}</dd>
                  </div>
                  <div>
                    <dt>Criticality</dt>
                    <dd>{Math.round(selectedNode.criticality * 100)}%</dd>
                  </div>
                  <div>
                    <dt>Population served</dt>
                    <dd>{selectedNode.population_served.toLocaleString()}</dd>
                  </div>
                  <div>
                    <dt>Backup remaining</dt>
                    <dd>
                      {selectedNode.backup_remaining.toLocaleString()} {unit}
                    </dd>
                  </div>
                  <div>
                    <dt>Current load</dt>
                    <dd>
                      {selectedNode.current_load.toLocaleString()} {unit}
                    </dd>
                  </div>
                </dl>
              </>
            ) : (
              <p className="legend-help">
                Select a symbol on the map to inspect an asset.
              </p>
            )}
          </section>
          <section className="legend-panel" aria-label="Map legend">
            <p className="eyebrow">READING THE MAP</p>
            <h2>System status</h2>
            <ul className="status-list">
              {statuses.map((status) => (
                <li key={status}>
                  <span
                    className="status-swatch"
                    style={{ backgroundColor: statusColors[status] }}
                  />
                  <span>{status.toLowerCase()}</span>
                  <strong>
                    {nodes.filter((node) => node.status === status).length}
                  </strong>
                </li>
              ))}
            </ul>
            <div className="type-section">
              <h2>Infrastructure type</h2>
              <ul className="type-list">
                {types.map((type) => (
                  <li key={type}>
                    <span
                      className="type-symbol"
                      dangerouslySetInnerHTML={{ __html: symbol(type) }}
                    />
                    {typeLabels[type]}
                  </li>
                ))}
              </ul>
            </div>
            <p className="data-note">
              {snapshot?.data_notice ??
                "Synthetic planning data; locations are illustrative."}
            </p>
          </section>
        </aside>
      </section>
      <section className="event-panel" aria-label="Simulation event feed">
        <div className="event-heading">
          <div>
            <p className="eyebrow">CASCADE TIMELINE</p>
            <h2>
              Event feed <span>{feed.length}</span>
            </h2>
          </div>
          <p>Events appear in simulation order.</p>
        </div>
        {feed.length === 0 ? (
          <p className="empty-feed">
            Run the simulation to watch infrastructure changes appear here.
          </p>
        ) : (
          <ol ref={feedListRef} className="event-list">
            {feed.map((event, index) => {
              const node =
                nodes.find((item) => item.id === event.node_id) ??
                snapshot?.nodes.find((item) => item.id === event.node_id);
              const transition =
                event.kind === "STATUS_TRANSITION"
                  ? `${event.old_status.toLowerCase()} → ${event.new_status.toLowerCase()}`
                  : event.kind.replaceAll("_", " ").toLowerCase();
              return (
                <li
                  key={`${event.elapsed_minutes}-${event.node_id}-${event.kind}-${index}`}
                >
                  <time dateTime={event.time}>
                    T+{event.elapsed_minutes}
                    <small>{event.time.slice(11, 16)}</small>
                  </time>
                  <div>
                    <strong>{node?.name ?? event.node_id}</strong>
                    <span>{transition}</span>
                    <p>
                      <b>{event.cause.replaceAll("_", " ").toLowerCase()}:</b>{" "}
                      {event.explanation}
                    </p>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </section>
    </main>
  );
}
