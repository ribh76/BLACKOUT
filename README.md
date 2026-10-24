# Blackout

Blackout is a deterministic emergency decision-support system for exploring
cascading infrastructure failures, constrained interventions, and
counterfactual recovery in a simulated San Jose environment.

The simulator is the source of truth. AI features will explain and orchestrate
verified simulator output; they will not invent infrastructure state.

## Current status

The repository contains the FastAPI and React foundation, a versioned simulated
San Jose city and dependency graph, a reproducible disaster scenario, and a
deterministic cascade engine. Later response and risk features are described in
the [master development plan](DOCS/BLACKOUT_MASTER_DEVELOPMENT_PLAN.md).

The **Extreme Heat + Grid Failure** scenario starts at a fixed simulation time
with 105°F heat, 97% grid load, Substation 03 failed, and Substation 07 degraded.
Use `GET /api/scenarios` or `GET /api/scenarios/extreme-heat-grid-failure` to
inspect its fixed inputs. `POST /api/scenarios/extreme-heat-grid-failure/start`
returns the initial event snapshot; `POST /api/scenarios/extreme-heat-grid-failure/reset`
returns the pristine city snapshot. Repeated starts return the same state and
initial events. `POST /api/scenarios/extreme-heat-grid-failure/simulate` returns
the complete T+0 through T+120 cascade timeline, final node states, and final
metrics. Repeated simulations return identical results.

All infrastructure and outcomes are simulated for demonstration and software
development. This project is not an operational emergency-management system.

## Repository layout

See [DOCS/Repo_structure.md](DOCS/Repo_structure.md) for the planned layout and
[DOCS/Build_overview.md](DOCS/Build_overview.md) for the product shape.

## Local development

Create a virtual environment and install backend dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r backend/requirements-dev.txt
```

Install frontend dependencies:

```bash
cd frontend && npm install
```

Run the backend and frontend in separate terminals:

```bash
make backend
make frontend
```

The backend health check is available at http://localhost:8000/api/health and
the frontend at http://localhost:5173.

The City view loads all infrastructure assets from the backend. It uses
OpenStreetMap tiles by default. To use Mapbox dark tiles, set
`VITE_MAPBOX_ACCESS_TOKEN` in `frontend/.env.local` before starting Vite.
Select a map symbol to inspect its current condition, load, and backup.
`SIMULATE BLACKOUT` retrieves the deterministic cascade and plays its events
in order; Pause, Resume, and Reset control the local playback. The event feed
shows each transition and its cause.
The live metrics count affected neighborhoods, critical facilities, and failed
assets from the currently displayed nodes. The Critical Infrastructure panel
shows backend risk rankings for the current playback state. Sort by risk,
impact, or operational priority, then select an entry to highlight its map
symbol and inspect its score drivers and downstream assets. Scores are
simulated estimates based on synthetic city data.
Select a critical or failed asset from the map, event feed, or risk ranking to
open the Cascade Explorer. It shows direct providers and dependents with
relationship type, weight, and delay, plus a nested downstream chain and
potential exposure. The chain is based on the directed dependency graph and
can be read from `GET /api/infrastructure/{node_id}/cascade`.
When an asset is focused, the map brightens its reachable nodes and draws
dashed potential dependency links. Solid links follow recorded simulator
events. The Explorer also distinguishes currently impaired downstream residents
and facilities from potential exposure, and lists the visible causal event
sequence. Clear focus returns to the city-wide map.
Explanations use recorded provider states and weights plus current backup
reserve and demand. Backup duration is an equivalent reserve estimate at
current load; limited backup coverage is reported separately. Multiple
recorded contributors appear in the explanation and event chain.

Run `npm test` in `frontend` for the UI and explanation checks. Run
`npm run test:contract` there to compare rendered tree rows, statuses, backup
labels, and impact totals against fresh backend API and simulator output.
The contract check uses `.venv/bin/python` by default; set
`BLACKOUT_TEST_PYTHON` to use another Python environment with backend
dependencies installed.

## Contribution conventions

Use small branches named `codex/<short-description>` or
`feature/<short-description>`, keep commits focused, and verify that the
application starts before merging. Run `make test`, `make lint`, and
`make format` for changes that touch the corresponding layer.
