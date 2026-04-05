# Materials Management

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18-61DAFB.svg)](https://react.dev/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED.svg)](https://docs.docker.com/compose/)

A full-stack inventory management system for optical components. Covers item master data, multi-location stock, supplier quotations and purchase orders, reservations, assemblies, project-based demand planning, and transaction history with undo support.

![Workspace dashboard](documents/screenshots/screenshot.png)

## Features

- **Workspace dashboard** — project pipeline, planning board with sequential demand netting, and supply-source breakdown
- **Items & inventory** — item master with supplier aliases, multi-location stock, and movement history
- **Orders & RFQ** — CSV/PDF import, preview-first reconciliation, and project-linked shortage tracking
- **Reservations** — item and assembly reservations with project allocation summaries
- **Projects & planning** — project requirements, BOM reconciliation, and provisional purchase candidates
- **CSV import flows** — preview before commit for items, inventory, orders, and reservations, with per-row correction and conflict detection
- **Auth** — Bearer JWT with OIDC support (Google Identity Platform), configurable `AUTH_MODE` and `RBAC_MODE`

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, PostgreSQL, SQLAlchemy, Alembic, `uv` |
| Frontend | React, TypeScript, Vite, SWR |
| Production serving | nginx (reverse proxy + static files) |
| Deployment | Docker Compose / Google Cloud Run |

## Quick Start (Docker Compose)

**Prerequisites:** Docker Desktop, Git

```powershell
git clone <this-repo>
cd materials_menagement(shared_version)

# Copy and edit the environment file
cp .env.example .env   # set POSTGRES_PASSWORD at minimum

# Start the stack
.\start-app.ps1
```

| Service | URL |
|---|---|
| Frontend | http://127.0.0.1/ |
| API | http://127.0.0.1/api |
| Swagger UI | http://127.0.0.1/docs |

Stop the stack:

```powershell
.\stop-app.ps1
```

> **Windows Server deployment:** see [`documents/deployment/windows_server_docker_deployment.md`](documents/deployment/windows_server_docker_deployment.md)

## Repository Structure

```
├── backend/                   # FastAPI app, DB schema (Alembic), business logic, tests
├── frontend/                  # React/TypeScript UI
├── documents/                 # Documentation hub (spec, architecture, onboarding)
├── deployment/gcp/            # Cloud Run deploy scripts and env templates
├── imports/                   # Order and item import files (CSV/PDF)
├── exports/                   # Generated CSV exports
├── docker-compose.yml         # Production: db + backend + nginx
├── docker-compose.override.yml# Local dev override (hot-reload backend/frontend)
├── docker-compose.test.yml    # Isolated test database
├── start-app.ps1 / stop-app.ps1
└── run-e2e.ps1                # End-to-end test runner (isolated Docker stack)
```

## Local Development

**Backend:**

```powershell
cd backend
uv sync
uv run main.py
```

**Frontend:**

```powershell
cd frontend
npm install
$env:VITE_API_BASE = "http://127.0.0.1:8000/api"
npm run dev
```

For the full dev stack (hot-reload backend + frontend dev server):

```powershell
.\start-app.ps1 -IncludeDevOverride
```

## Testing

```powershell
# 1. Start the test database
docker compose -f docker-compose.test.yml up -d db-test

# 2. Backend tests
$env:TEST_DATABASE_URL = "postgresql+psycopg://develop:test@localhost:5433/materials_test"
$env:PYTHONPATH = "backend"
uv run --project backend python -m pytest --import-mode=importlib

# 3. Frontend unit tests and build check
cd frontend
npm run test
npm run build
```

**End-to-end (Playwright)** — runs against an isolated Docker stack so test data does not affect your local environment:

```powershell
.\run-e2e.ps1
```

Reset local Docker app data when needed:

```powershell
.\start-app.ps1 -ResetData
```

## Deployment

### Docker Compose (local / shared server)

Use `start-app.ps1` / `stop-app.ps1`. See the [Windows Server deployment guide](documents/deployment/windows_server_docker_deployment.md) for production setup.

### Google Cloud Run

See the [Cloud Run deployment runbook](documents/deployment/gcp_cloud_run_rollout/cloud_run_deployment_runbook.md) for step-by-step instructions, environment variable reference, and GitHub Actions workflow setup.

Deploy assets live under `deployment/gcp/`. A manual GitHub Actions workflow is at `.github/workflows/deploy-gcp.yml`.

## API Reference

Interactive docs are available at `/docs` (Swagger UI) when the stack is running.

- Auth: `Authorization: Bearer <JWT>` — supports `shared_secret` (local) and `jwks` OIDC (deployed)
- CSV import templates: `GET /api/{items,inventory,purchase-order-lines,reservations}/import-template`
- Catalog search: `GET /api/catalog/search?q=...&types=item,assembly,supplier,project`

## Documentation

| Document | Description |
|---|---|
| [`documents/README.md`](documents/README.md) | Documentation hub index |
| [`documents/specification.md`](documents/specification.md) | Functional specification |
| [`documents/technical_documentation.md`](documents/technical_documentation.md) | Architecture and ER diagrams |
| [`documents/setup/team_onboarding.md`](documents/setup/team_onboarding.md) | Onboarding: clone, install, run, test |
| [`documents/change_log.md`](documents/change_log.md) | Change history |

## License

[Apache License 2.0](LICENSE)
