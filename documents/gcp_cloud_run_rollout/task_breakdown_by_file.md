# GCP Rollout Task Breakdown by File

## Purpose

This document maps the GCP rollout work to concrete files, functions, and runtime surfaces in this repository.

Backward compatibility is explicitly out of scope.

If a compatibility path conflicts with the target Cloud Run + Cloud SQL + GCS model, prefer replacing or removing it.

## 1. Backend storage refactoring

### Goal

Remove persistent business-critical dependence on Cloud Run local disk.

### Primary files

- `backend\app\service.py`
- `backend\app\config.py`
- `backend\app\api.py`
- `backend\app\db.py`

### Current repository signals

- Filesystem roots are defined in `backend\app\config.py`.
- Workspace roots are still materialized by `ensure_workspace_layout()` in `backend\app\config.py`.
- Generated artifacts are tracked in `generated_artifacts` and served through backend endpoints wired in `backend\app\api.py`.
- File-heavy business flows live in `backend\app\service.py`, including:
  - `register_unregistered_item_csvs()`
  - `consolidate_registered_item_csvs()`
  - `_build_project_planning_snapshot()` for heavier planning work

### Work items

1. Introduce a storage abstraction for persistent file operations.
2. Separate temporary local working files from durable storage.
3. Move generated artifacts and durable import/export files to object-backed references.
4. Remove runtime folder migration assumptions that only exist for local/shared-server compatibility.

### Concrete code areas to review first

- `backend\app\config.py`
  - `APP_DATA_ROOT`
  - `IMPORTS_ROOT`
  - `EXPORTS_ROOT`
  - `ITEMS_IMPORT_*`
  - `ORDERS_IMPORT_*`
  - `STAGING_IMPORT_*`
  - `ensure_workspace_layout()`

- `backend\app\service.py`
  - generated artifact create/list/load paths
  - item batch upload and registration flows
  - order import and artifact generation flows
  - export generation paths used by download endpoints

- `backend\app\api.py`
  - file download endpoints
  - multipart upload endpoints
  - artifact download endpoints

### Recommended implementation direction

- Add a storage boundary such as:
  - `LocalTemporaryStorage` for request-scoped temporary disk use
  - `DurableObjectStorage` for persistent files
- Persist only opaque identifiers and durable object references in DB-backed contracts.
- Stop exposing internal relative paths in any browser-facing response model.

## 2. Backend startup and migration behavior

### Goal

Make the backend safe for autoscaled Cloud Run startup.

### Primary files

- `backend\app\api.py`
- `backend\app\db.py`
- `backend\main.py`
- `backend\Dockerfile`
- `docker-compose.yml`

### Current repository signals

- `create_app()` in `backend\app\api.py` calls `init_db()` during lifespan startup when `AUTO_MIGRATE_ON_STARTUP` is enabled.
- `init_db()` in `backend\app\db.py` currently calls both `ensure_workspace_layout()` and `run_migrations()`.
- `docker-compose.yml` currently runs `uv run alembic upgrade head` before Gunicorn starts.
- `backend\Dockerfile` starts Gunicorn and respects `PORT`.

### Work items

1. Decouple normal app startup from migration execution.
2. Ensure startup does not depend on creating durable workspace layout on local disk.
3. Keep `/api/health` useful for deployment checks, but avoid surfacing sensitive internals.
4. Define one migration execution path for deployment.

### Recommended implementation direction

- Production Cloud Run:
  - disable `AUTO_MIGRATE_ON_STARTUP`
  - run Alembic in a controlled deployment step
- Keep request-serving startup limited to:
  - config loading
  - DB engine creation
  - middleware/app initialization

## 3. Cloud SQL connection management

### Goal

Prevent Cloud Run scaling from creating unstable or expensive connection pressure.

### Primary files

- `backend\app\db.py`
- `backend\app\config.py`
- `docker-compose.yml`

### Current repository signals

- `get_engine()` in `backend\app\db.py` hard-codes:
  - `pool_size=5`
  - `max_overflow=10`
  - `pool_pre_ping=True`

### Work items

1. Move pool sizing and possibly pool timeout/recycle settings into environment variables.
2. Define a Cloud SQL connection contract.
3. Document concurrency assumptions between:
  - Cloud Run instance concurrency
  - Gunicorn worker count
  - SQLAlchemy pool size

### Recommended implementation direction

- Add explicit settings in `backend\app\config.py` for DB pool tuning.
- Use those settings in `backend\app\db.py`.
- Record an operational formula for safe default values before production rollout.

## 4. Frontend-to-backend deployment contract

### Goal

Make frontend/backend communication explicit for Cloud Run deployment.

### Primary files

- `frontend\src\lib\api.ts`
- `frontend\Dockerfile`
- `frontend\nginx.conf`
- `docker-compose.yml`

### Current repository signals

- `frontend\src\lib\api.ts` resolves API traffic from `VITE_API_BASE`.
- The frontend currently stores the selected mutation user in browser local storage and sends `X-User-Name` on mutations.
- `frontend\nginx.conf` currently reverse proxies `/api/` to `backend:8000`.
- `frontend\Dockerfile` bakes `VITE_API_BASE` at build time.

### Work items

1. Decide whether frontend Cloud Run continues serving through nginx or moves to a simpler static-serving container.
2. Decide whether frontend talks to backend by:
  - same-origin path proxy
  - absolute backend URL
3. Align backend CORS settings with that decision.
4. Re-check upload size assumptions because nginx currently enforces `client_max_body_size 50M`.

### Recommended implementation direction

- Prefer an explicit production API base contract.
- If frontend and backend are separate Cloud Run services, configure explicit allowed origins and review browser upload limits carefully.

## 5. Authentication and trust boundary cleanup

### Goal

Document and isolate the current temporary identity model so it can be replaced cleanly.

### Primary files

- `backend\app\api.py`
- `backend\app\config.py`
- `frontend\src\lib\api.ts`

### Current repository signals

- `UserIdentityMiddleware` in `backend\app\api.py` drives the current `X-User-Name` behavior.
- `get_auth_mode()` in `backend\app\config.py` recognizes:
  - `none`
  - `rbac_dry_run`
  - `rbac_enforced`
- `frontend\src\lib\api.ts` injects `X-User-Name` for mutation methods.

### Work items

1. Keep the current model clearly marked as temporary.
2. Define which backend boundary should later consume real user identity.
3. Review all mutation-protected endpoints that currently rely on this header model.

### Recommended implementation direction

- Keep identity interpretation centralized in middleware or one dependency boundary.
- Avoid leaking the temporary mutation model into more endpoint-specific code.

## 6. CORS and browser security defaults

### Goal

Replace development-friendly defaults with explicit cloud-ready defaults.

### Primary files

- `backend\app\config.py`
- `backend\app\api.py`
- `frontend\nginx.conf`
- `docker-compose.yml`

### Current repository signals

- `get_cors_allowed_origins()` defaults to `"*"`.
- `create_app()` installs `CORSMiddleware` with wildcard-ready values.
- nginx adds some security headers for the current frontend container.

### Work items

1. Replace wildcard origin defaults with explicit origins.
2. Reconfirm required headers and methods for browser uploads/downloads.
3. Decide which response security headers stay at the frontend tier and which are enforced elsewhere.

## 7. Heavy processing and cost-risk surfaces

### Goal

Identify code paths that should be closely reviewed before production rollout.

### Primary files

- `backend\app\service.py`
- `frontend\src\pages\WorkspacePage.tsx`
- `frontend\src\pages\OrdersPage.tsx`
- `frontend\src\pages\ItemsPage.tsx`
- `frontend\src\pages\InventoryPage.tsx`
- `frontend\src\pages\ReservationsPage.tsx`
- `frontend\src\pages\ProcurementPage.tsx`

### Current repository signals

- The frontend uses `apiDownload()` across multiple pages for export and artifact retrieval.
- Planning and workspace exports can produce larger payloads and downloads.
- CSV import endpoints exist across items, inventory, orders, and reservations.

### Work items

1. Review maximum realistic payload sizes for upload and download flows.
2. Review whether the heaviest synchronous operations should stay synchronous.
3. Review planning queries and export generation for production-scale usage.

### Recommended implementation direction

- Keep the first rollout synchronous if acceptable, but document thresholds that would trigger asynchronous redesign later.

## 8. Deployment and operations documentation

### Goal

Keep the rollout executable by engineers without rediscovery.

### Primary files

- `README.md`
- `documents\technical_documentation.md`
- `documents\source_current_state.md`
- `documents\change_log.md`
- this folder

### Work items

1. Keep the target cloud architecture documented separately from local Docker behavior.
2. Update the root README when deployment/runtime assumptions change.
3. Update architecture and current-state docs whenever implementation lands.

## 9. Suggested implementation sequence

1. Introduce storage abstraction and remove durable local-path contracts.
2. Refactor generated artifacts and file download behavior around durable object references.
3. Externalize DB pool tuning and finalize Cloud SQL startup strategy.
4. Tighten CORS and document the temporary mutation identity model.
5. Finalize frontend/backend Cloud Run communication contract.
6. Validate heavy flows and add cost-control guidance.
