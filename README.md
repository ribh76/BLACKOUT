# Blackout

Blackout is a deterministic emergency decision-support system for exploring
cascading infrastructure failures, constrained interventions, and
counterfactual recovery in a simulated San Jose environment.

The simulator is the source of truth. AI features will explain and orchestrate
verified simulator output; they will not invent infrastructure state.

## Current status

The repository currently contains the Phase 0 foundation: a FastAPI backend,
React/TypeScript frontend, environment configuration, health endpoint, and
developer commands. The city data model and cascade engine will be added in
dependency order from the [master development plan](DOCS/BLACKOUT_MASTER_DEVELOPMENT_PLAN.md).

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

## Contribution conventions

Use small branches named `codex/<short-description>` or
`feature/<short-description>`, keep commits focused, and verify that the
application starts before merging. Run `make test`, `make lint`, and
`make format` for changes that touch the corresponding layer.
