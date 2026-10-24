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

## Contribution conventions

Use small branches named `codex/<short-description>` or
`feature/<short-description>`, keep commits focused, and verify that the
application starts before merging. Run `make test`, `make lint`, and
`make format` for changes that touch the corresponding layer.
