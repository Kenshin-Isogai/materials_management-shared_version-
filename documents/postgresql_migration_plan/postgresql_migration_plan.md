# PostgreSQL Migration Plan Status And Completion Guide

> Status: In progress
> Last updated: 2026-03-24
> Scope: Repository implementation status, deployment status, and remaining tasks to complete PostgreSQL/shared-server rollout

---

## 1. Purpose

This document records:

- what has already been implemented from the PostgreSQL migration plan
- what has been verified locally
- what still must be completed to finish the rollout
- the exact order of remaining work on the Windows Server

This file is intended to be the working handoff document for finishing the migration.

---

## 2. Completed Work

### 2.1 Backend migration foundation

The backend has been migrated from SQLite bootstrap logic to a PostgreSQL-first runtime foundation.

Implemented:

- SQLAlchemy engine bootstrap in `backend/app/db.py`
- Alembic baseline migration in `backend/alembic/`
- PostgreSQL schema creation through `001_initial_schema.py`
- compatibility wrapper so the existing raw-SQL service layer can continue working during migration
- server-only backend entrypoint in `backend/main.py`
- startup migration control via `AUTO_MIGRATE_ON_STARTUP`

### 2.2 PostgreSQL schema and audit support

Implemented:

- `users` table
- PostgreSQL baseline schema for core application tables
- audit-related user references (`created_by`, `updated_by`, `performed_by`) where added in this migration phase

### 2.3 User identity support

Implemented:

- mutation requests require `X-User-Name`
- anonymous reads remain allowed
- `/api/users` CRUD endpoints
- `/api/users/me`
- frontend user selection support in the header

### 2.4 Frontend deployment behavior

Implemented:

- frontend API base now uses `/api`
- Vite dev proxy for `/api`
- nginx static hosting + reverse proxy
- frontend dev service moved behind a Compose `dev` profile so production-style startup does not automatically run the dev server

### 2.5 Docker deployment artifacts

Implemented:

- root `docker-compose.yml`
- root `docker-compose.override.yml`
- root `docker-compose.test.yml`
- `backend/Dockerfile`
- `frontend/Dockerfile`
- `frontend/nginx.conf`
- `.env.example`
- `backend/.dockerignore`
- `frontend/.dockerignore`

### 2.6 PostgreSQL compatibility fixes already completed

The following runtime/test compatibility issues were fixed during migration:

- PostgreSQL-safe `GROUP BY` fixes in RFQ aggregate queries
- `ILIKE` for intended case-insensitive catalog search
- normalization of PostgreSQL date/datetime results back to ISO strings where the service layer expected strings
- integrity-error remapping for existing duplicate-handling paths
- savepoint compatibility for application-managed undo/redo flows
- null-parameter handling in a planning query
- seeded test user header support in backend tests
- `/api/users/me` route ordering fix
- read requests with `X-User-Name` now resolve `request.state.user` without forcing headers for anonymous reads

---

## 3. Verification Completed

### 3.1 Automated verification

Confirmed completed earlier in this migration work:

- backend PostgreSQL test suite: `166 passed`
- frontend production build: `npm run build`
- backend compile smoke check: `uv run python -m compileall app main.py tests`

Note:

- a later full-suite rerun from the coding tool timed out before finishing, but an earlier full PostgreSQL run completed successfully with `166 passed`

### 3.2 Runtime verification

Confirmed on the Compose stack:

- `docker compose -f docker-compose.yml up --build -d` starts successfully
- `db` container healthy
- `backend` container healthy
- `nginx` container serving on host port `80`

Smoke-tested successfully:

- `GET /api/health`
- `GET /api/users`
- `GET /api/users/me` with `X-User-Name`
- authenticated `PUT /api/users/{id}`
- frontend root `/`

### 3.3 Seeded users

The following users were created in the live PostgreSQL database during smoke testing:

- `admin`
- `operator1`

These are bootstrap users for initial validation. Adjust or replace them as needed for actual operation.

---

## 4. Current Remaining Work

The repository-side migration foundation is substantially complete. The remaining work is operational rollout, real-flow validation, and production hardening.

### 4.1 Required before calling the migration complete

1. Validate real application flows in the browser against the Compose stack.
2. Validate file-based import/export behavior on the mounted application data path.
3. Finalize server-side `.env` values and persistent volume strategy.
4. Register the actual operator/admin users that will use the system.
5. Perform first deployment on the target Windows Server using the runbook.
6. Confirm restart/recovery behavior after container recreation and host reboot.

### 4.2 Recommended but not strictly blocking

1. Re-run the full backend PostgreSQL suite directly in a local terminal and let it complete visibly.
2. Add or update automated tests covering `/api/users/me` header-resolution behavior on read requests.
3. Replace bootstrap smoke-test users with named operational users.
4. Decide whether the temporary SQL compatibility wrapper should remain for the next phase or be incrementally replaced by explicit SQLAlchemy Core query code.

---

## 5. Exact Remaining Steps

### Step 1. Confirm `.env` is final

The Compose stack currently depends on a working `.env` file. Confirm at minimum:

```env
POSTGRES_USER=develop
POSTGRES_PASSWORD=<real-password>
POSTGRES_DB=materials_db
DATABASE_URL=postgresql+psycopg://develop:<real-password>@db:5432/materials_db
TEST_DATABASE_URL=postgresql+psycopg://develop:test@localhost:5433/materials_test
APP_DATA_ROOT=/app/data
APP_HOST=0.0.0.0
APP_PORT=8000
LOG_LEVEL=info
WEB_CONCURRENCY=4
AUTO_MIGRATE_ON_STARTUP=0
VITE_API_BASE=/api
```

Important:

- `POSTGRES_USER` must match the username in `DATABASE_URL`
- if these values change after DB initialization, recreate the DB volume before retesting

### Step 2. Run the production-style stack

From repository root:

```powershell
docker compose -f docker-compose.yml up --build -d
docker compose -f docker-compose.yml ps
docker compose -f docker-compose.yml logs backend --tail=50
docker compose -f docker-compose.yml logs db --tail=50
```

Expected:

- `db` healthy
- `backend` healthy
- `nginx` running

### Step 3. Verify the API and frontend

Required checks:

- open `http://localhost/`
- open `http://localhost/api/health`
- open `http://localhost/api/users`
- confirm the frontend loads through nginx
- confirm the user selector shows registered users

### Step 4. Validate authenticated write flows

At minimum, verify one real write operation from the UI while a user is selected.

Suggested minimum checks:

- edit an existing user or create a new user
- create or update one item
- create or update one order

### Step 5. Validate import/export flows

This is the highest remaining functional risk area.

Validate all relevant file flows against the containerized runtime:

- items CSV import
- orders import
- inventory import
- reservations import if used operationally
- CSV export flows
- any quotation/PDF linked file flow

For each one, confirm:

- upload succeeds
- server-side file path is valid
- moved/registered files end up in the expected persistent location
- exported files can be downloaded correctly

### Step 6. Finalize users

Create the real operational users in PostgreSQL.

Minimum recommendation:

- one `admin`
- one or more `operator` users

Remove or deactivate temporary smoke-test users if they should not remain.

### Step 7. Deploy on the Windows Server

Use:

- `documents/postgresql_windows_server_instructions.md`

Required server checks:

- Docker Desktop or equivalent engine available and stable
- repository present on the server
- `.env` configured correctly
- persistent Docker volumes retained
- host firewall/network allows HTTP access to the chosen port

### Step 8. Post-deployment validation

After deployment on the real server:

- test the app from another machine on the same network
- verify browser access through the server host/IP
- verify one read-only flow
- verify one authenticated mutation flow
- verify one import flow
- restart containers and confirm recovery
- reboot-check if this environment is intended for continuous operation

---

## 6. Open Risks And Known Follow-Up Items

### 6.1 Remaining operational risks

- import/export path behavior may differ between local Docker and the target Windows Server
- persistent-volume expectations must be validated under real server maintenance and restart conditions
- if `.env` credentials are edited after database initialization, Compose may appear healthy while app login to PostgreSQL fails until volumes are recreated

### 6.2 Remaining technical debt

- the service layer still uses a PostgreSQL compatibility wrapper rather than a full query-by-query SQLAlchemy Core rewrite
- some legacy compatibility API and planning/procurement transitional paths remain in the codebase
- `/api/users/me` behavior should ideally have a dedicated regression test if not already added later

---

## 7. Suggested Completion Criteria

Treat the PostgreSQL migration as fully complete only when all of the following are true:

- backend PostgreSQL suite passes in a visible local terminal run
- Compose stack starts cleanly from scratch
- frontend loads through nginx
- user selection works
- at least one authenticated write flow works from the UI
- real import/export file flows are verified
- server deployment runbook has been executed successfully on the target Windows Server
- actual operational users are registered

---

## 8. Useful Commands

### Start production-style stack

```powershell
docker compose -f docker-compose.yml up --build -d
```

### Stop and remove containers

```powershell
docker compose -f docker-compose.yml down
```

### Recreate DB volume when credentials/schema bootstrap must restart

```powershell
docker compose -f docker-compose.yml down -v
docker compose -f docker-compose.yml up --build -d
```

### Start test database only

```powershell
docker compose -f docker-compose.test.yml up -d
```

### Run backend tests against PostgreSQL

```powershell
cd backend
$env:TEST_DATABASE_URL='postgresql+psycopg://develop:test@localhost:5433/materials_test'
uv run python -m pytest
```

### Show live-ish detailed pytest progress in a normal terminal

```powershell
cd backend
$env:TEST_DATABASE_URL='postgresql+psycopg://develop:test@localhost:5433/materials_test'
uv run python -m pytest -vv
```

---

## 9. Handoff Summary

Implementation under the repository is largely complete for the PostgreSQL migration foundation.

What remains is not a large missing-code phase. It is the final rollout phase:

- finish browser-level validation
- finish file-flow validation
- finalize users and environment values
- deploy and verify on the actual Windows Server

For server execution details, use:

- `documents/postgresql_windows_server_instructions.md`

