# Materials Management

Materials Management is a full-stack inventory system for optical components. It manages item master data, stock by location, supplier quotations and orders, reservations, assemblies, projects, and transaction history with undo support.

The recommended future-planning workflow is now:

`Workspace` -> `Projects` / `Planning` / `RFQ` -> `Orders` / `Reservations`

`Workspace` is the default summary-first route for future demand. It opens with a project dashboard, provides a committed pipeline view, and offers a planning board that previews project impact with server-owned sequential netting data and supply-source breakdowns. The dedicated `Projects`, `Planning`, and `RFQ` pages remain available for heavier editing and operational fallback.

The workspace drawers now complete the main planning loop in place:

- Project drawer: inline project requirement editing plus preview-first bulk item entry
- Item drawer: inventory, incoming orders, and cross-project planning allocation context for the selected item
- RFQ drawer: inline RFQ batch and line editing, including supplier, ETA, status, and linked-order updates
- Planning board: CSV export for the currently selected project/preview date

`Planning` still performs sequential project netting so earlier committed projects, including already-started work, consume future planning capacity before later projects are analyzed. `RFQ` stores project-dedicated shortage follow-up, reuses the planning date selected on the planning board, and links real orders back to the project when purchasing starts.

## Tech Stack

- Backend: Python, FastAPI, PostgreSQL, SQLAlchemy engine bootstrap, Alembic, `uv`
- Frontend: React, TypeScript, Vite, SWR, nginx in production
- Deployment: Docker Compose (`db`, `backend`, `nginx`)
- Data/Files: PostgreSQL database + mounted app-data volume (`imports/`, `exports/`)

For Cloud Run deployment posture, the backend now supports:

- `APP_RUNTIME_TARGET=cloud_run`
- automatic `PORT` pickup from Cloud Run
- default ephemeral app-data root under `/tmp` when `APP_DATA_ROOT` is not set
- startup that skips legacy repo/workspace folder migration in Cloud Run mode
- startup migration disabled by default in Cloud Run mode
- frontend nginx image no longer assumes a backend container-side `/api` proxy in the Cloud Run-target image
- environment-driven DB pool settings (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE_SECONDS`)
- environment-driven upload/concurrency guardrails (`MAX_UPLOAD_BYTES`, `HEAVY_REQUEST_TARGET_SECONDS`, `CLOUD_RUN_CONCURRENCY_TARGET`)
- explicit cloud deployment metadata for Cloud SQL and storage (`INSTANCE_CONNECTION_NAME`, `STORAGE_BACKEND`, `GCS_BUCKET`, `GCS_OBJECT_PREFIX`, `BACKEND_PUBLIC_BASE_URL`, `FRONTEND_PUBLIC_BASE_URL`)
- explicit CORS origins instead of wildcard defaults

## Repository Structure

- `backend/`: API server, PostgreSQL/Alembic schema bootstrap, business logic, tests
- `frontend/`: Web UI
- `docker-compose.yml`: production composition for PostgreSQL + backend + nginx
- `docker-compose.override.yml`: local development override
- `docker-compose.test.yml`: PostgreSQL test database
- `imports/orders/`: Registered/unregistered order import CSV/PDF files
- `exports/`: Generated CSV exports (for example missing-item registration templates)
- `documents/`: Technical documentation
- `specification.md`: Detailed functional specification
- `start-app.ps1` / `stop-app.ps1`: PowerShell helper scripts to start/stop the Docker Compose stack
- `launch-start-app.bat` / `launch-stop-app.bat`: Batch wrappers for the PowerShell scripts

## Quick Start (Docker Compose)

1. Copy `.env.example` to `.env` and set the PostgreSQL password.
2. Start the stack:

```powershell
docker compose up --build
```

Or use the Windows helper script for the base compose stack:

```powershell
.\start-app.ps1
```

Use `.\start-app.ps1 -IncludeDevOverride` only when you explicitly want the local dev override (`backend:8000`, `frontend-dev:5173`).

Stop the stack with:

```powershell
.\stop-app.ps1
```

3. Open:
- Frontend: `http://127.0.0.1/`
- API: `http://127.0.0.1/api`
- Swagger: `http://127.0.0.1/docs`

The Docker Compose stack keeps the local `/api` path by mounting `frontend/nginx.local-proxy.conf`, while the built frontend image keeps `frontend/nginx.conf` as the cloud-first no-proxy default.

4. Stop:

```powershell
docker compose down
```

Detailed Windows Server deployment steps are in `documents/postgresql_windows_server_instructions.md`.

## Local Development

Backend:

```powershell
cd backend
uv sync
uv run main.py
```

Frontend:

```powershell
cd frontend
npm install
$env:VITE_API_BASE = "http://127.0.0.1:8000/api"
npm run dev
```

Automated UI tests should use the isolated Docker workflow from the repo root so test data does not leak into the normal local stack:

```powershell
.\run-e2e.ps1
```

This wrapper sets `NGINX_HOST_PORT=8088` for the E2E stack, so Playwright does not need the normal local `:80` frontend binding.

## Cloud Run Runtime Notes

- Set `APP_RUNTIME_TARGET=cloud_run`
- Set `DATABASE_URL` from Secret Manager / Cloud SQL connection config
- Set `INSTANCE_CONNECTION_NAME` for the target Cloud SQL instance and keep `DATABASE_URL` on the Cloud SQL Unix-socket form
- Set `VITE_API_BASE` to the backend Cloud Run public `/api` URL for split-service deployment
- Set `VITE_IDENTITY_PLATFORM_API_KEY` to the Identity Platform web API key used by the frontend login form
- The built frontend image no longer proxies `/api` to an internal backend container by default; browser API traffic should come from `VITE_API_BASE`
- Set `BACKEND_PUBLIC_BASE_URL` and `FRONTEND_PUBLIC_BASE_URL` if you want the runtime health surface to report the intended public URLs explicitly
- Set `CORS_ALLOWED_ORIGINS` to the frontend Cloud Run origin explicitly
- Set `JWT_VERIFIER=jwks` plus `OIDC_JWKS_URL`, `OIDC_EXPECTED_ISSUER`, and `OIDC_EXPECTED_AUDIENCE` for deployed OIDC verification
- `DIAGNOSTICS_AUTH_ROLE` defaults to `admin` in Cloud Run so `/api/health` and `/api/auth/capabilities` do not stay anonymously public
- Keep `MAX_UPLOAD_BYTES=33554432` unless you intentionally revise the first-rollout 32 MB ceiling
- Keep `CLOUD_RUN_CONCURRENCY_TARGET=10` and align actual Cloud Run/Gunicorn settings with Cloud SQL capacity
- Set `STORAGE_BACKEND=gcs` plus `GCS_BUCKET` and optional `GCS_OBJECT_PREFIX` for Cloud Run durable storage; `local` remains the local/shared-server default
- `PORT` is honored automatically; you do not need to force `APP_PORT`
- If `APP_DATA_ROOT` is omitted, the backend now defaults to an ephemeral temp directory suitable for Cloud Run
- Cloud Run startup no longer copies legacy `quotations/` or repo-local `imports/` folders into runtime storage
- Cloud Run should run Alembic as a deployment step; request-serving startup should keep `AUTO_MIGRATE_ON_STARTUP=0`
- local Docker Compose now relies on normal backend startup migration (`AUTO_MIGRATE_ON_STARTUP=1` by default in compose) instead of embedding `alembic upgrade head` into the container command
- manual order-import missing-item outputs are now exposed through artifact metadata/download endpoints rather than raw path fields
- Legacy ZIP/PDF compatibility import remains a local/shared-server workflow, not the target Cloud Run path
- Concrete first-rollout deploy steps are documented in [documents/gcp_cloud_run_rollout/cloud_run_deployment_runbook.md](documents/gcp_cloud_run_rollout/cloud_run_deployment_runbook.md)
- Repo-side deployment assets live under `deployment/gcp/`, including backend/frontend env templates, PowerShell deploy scripts, and a Secret Manager helper
- A manual GitHub Actions deploy workflow now lives at `.github/workflows/deploy-gcp.yml`

## API

- API base: `http://127.0.0.1:8000/api`
- API docs (Swagger): `http://127.0.0.1:8000/docs`
- Browser/API auth now uses `Authorization: Bearer <JWT>`.
- Runtime auth is controlled by `AUTH_MODE` (`none`, `oidc_dry_run`, `oidc_enforced`) and `RBAC_MODE` (`none`, `rbac_dry_run`, `rbac_enforced`).
- `JWT_VERIFIER` supports `shared_secret` for local fixtures and `jwks` for deployed OIDC verification.
- App users are mapped from verified OIDC claims (`email`, `sub`, `hd`) onto active rows in `users`.
- The frontend header bar now supports Identity Platform email/password sign-in when `VITE_IDENTITY_PLATFORM_API_KEY` is configured and keeps manual Bearer token entry as a fallback.

## Database and File Layout

- Database: PostgreSQL via `DATABASE_URL`
- Orders import roots:
  - `imports/orders/unregistered/csv_files/<supplier>/`
  - `imports/orders/unregistered/pdf_files/<supplier>/`
  - `imports/orders/registered/csv_files/<supplier>/`
  - `imports/orders/registered/pdf_files/<supplier>/`
- Unregistered item register roots:
  - `imports/items/unregistered/` (single consolidated missing-item CSV per batch run)
  - `imports/items/registered/<YYYY-MM>/`

## Testing

```powershell
docker compose -f docker-compose.test.yml up -d db-test
$env:TEST_DATABASE_URL = "postgresql+psycopg://develop:test@localhost:5433/materials_test"
$env:PYTHONPATH = "backend"
uv run --project backend python -m pytest --import-mode=importlib
cd ..\frontend
npm run test
npm run build
```

Run Playwright from the repo root with the isolated Docker stack:

```powershell
.\run-e2e.ps1
```

To fully reinitialize the normal local Docker app state before starting it again, use:

```powershell
.\start-app.ps1 -ResetData
```

For targeted backend slices from the repo root, keep the same `TEST_DATABASE_URL` / `PYTHONPATH` setup and run `uv run --project backend python -m pytest --import-mode=importlib backend/tests/...`.

## Documentation

- Functional specification: [`specification.md`](specification.md)
- Technical architecture and ER diagrams: [`documents/technical_documentation.md`](documents/technical_documentation.md)
- Team onboarding (clone/install/run/test): [`documents/team_onboarding.md`](documents/team_onboarding.md)
- Current source snapshot: [`documents/source_current_state.md`](documents/source_current_state.md)
- Project change history: [`documents/change_log.md`](documents/change_log.md)


### CSV import shortcuts

- Header-only template downloads (UTF-8 with BOM):
  - `GET /api/items/import-template`
  - `GET /api/inventory/import-template`
  - `GET /api/purchase-order-lines/import-template`
  - `GET /api/reservations/import-template`
- Preview-first manual imports:
  - `POST /api/items/import-preview`
  - previews duplicate item rows, alias create/update behavior, and canonical-item reconciliation before final `POST /api/items/import`
  - the Items page can preview/import one or more CSV files in a single run
  - order-generated missing-item CSVs now come back through this same Items import flow after the user edits the downloaded CSV
  - final item import accepts optional per-row `row_overrides` (`canonical_item_number`, `units_per_order`) and archives successful manual-import CSV content into `imports/items/registered/<YYYY-MM>/` as durable history without a follow-up folder rescan
  - `POST /api/inventory/import-preview`
  - validates movement rows, simulates stock balance changes, and allows per-row `item_id` correction before final `POST /api/inventory/import-csv`
  - `POST /api/purchase-order-lines/import-preview`
  - classifies rows as `exact`, `high_confidence`, `needs_review`, or `unresolved`
  - requires `supplier` on every CSV row
  - surfaces duplicate quotation conflicts before commit
  - supports per-row canonical item correction plus optional supplier-alias save on final `POST /api/purchase-order-lines/import`
  - the Orders page can preview/import multiple CSV files in a single run
  - when orders still contain unresolved item numbers, the page exposes a downloadable missing-item CSV instead of routing into a dedicated Items resolver
  - `POST /api/reservations/import-preview`
  - validates item/assembly targets, previews assembly expansion, and allows per-row `item_id`/`assembly_id` correction before final `POST /api/reservations/import-csv`
  - preview-confirmation JSON fields are strict: malformed JSON, wrong top-level shapes, missing required keys, and override row numbers not present in the uploaded CSV return `422` instead of bubbling as server errors
- Projects quick requirement parsing:
  - `POST /api/projects/requirements/preview`
  - parses `item_number,quantity` lines, classifies exact/review/unresolved matches, lets the UI apply corrected rows into project requirements, and can export unresolved rows as an Items import-compatible CSV
- BOM spreadsheet reconciliation:
  - `POST /api/bom/preview`
  - classifies supplier/item matches as `exact`, `high_confidence`, `needs_review`, or `unresolved`
  - returns ranked supplier and item candidates plus projected shortage data before the UI runs `POST /api/bom/analyze`, `POST /api/bom/reserve`, or `POST /api/purchase-candidates/from-bom`
- Live reference CSV downloads:
  - `GET /api/items/import-reference`
  - `GET /api/inventory/import-reference`
  - `GET /api/purchase-order-lines/import-reference` (optional `?supplier_name=...`)
  - `GET /api/reservations/import-reference`
- Movements CSV upload: `POST /api/inventory/import-csv`
  - columns: `operation_type,item_id,quantity,from_location,to_location,location,note`
- Reservations CSV upload: `POST /api/reservations/import-csv`
  - columns: `item_id` or `assembly`, `quantity`, optional `assembly_quantity,purpose,deadline,note,project_id`
- Reservations page `Reservation Entry` now also supports optional project selection directly in the UI for provisional project linkage.
- Orders page `Order Details` now includes `Create Provisional Reservation…` to open Reservations with prefilled draft fields from the selected order.
- Reservations page now includes `Provisional Allocation Summary` and `Export Summary CSV` for project-level provisional reservation and incoming-supply review.

### Catalog search shortcut

- Typed selector search for write flows: `GET /api/catalog/search?q=...&types=item,assembly,supplier,project`
- `CatalogPicker` now powers Projects requirements, Assemblies components, BOM spreadsheet entry and BOM preview reconciliation, Reservations entry, and Items/Orders/Movements/Reservations import reconciliation
- Single-select `CatalogPicker` inputs now resync their visible text when the parent selection changes while the popover is open, so preview correction rows stay aligned with the final submitted state
