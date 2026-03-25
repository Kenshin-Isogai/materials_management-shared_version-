# PostgreSQL Migration & Shared-Server Deployment Plan

> **Status**: Draft
> **Last Updated**: 2026-03-24
> **Scope**: Migrate from SQLite to PostgreSQL, containerize with Docker Compose, deploy on shared Windows Server

---

## 1. Executive Summary

### Current State

- **Database**: SQLite (single file, `backend/database/inventory.db`)
- **Backend**: Python + FastAPI, raw `sqlite3` module, 164 passing tests
- **Frontend**: React + TypeScript + Vite + SWR, port-scanning API discovery
- **Deployment**: Local-first, two console windows via `start-dev.bat`
- **CLI**: Extensive CLI commands in `main.py` (import, arrival, move, consume, etc.)
- **File I/O**: imports/exports directories accessed locally on disk
- **Auth**: None (trusted local environment)

### Target State

- **Database**: PostgreSQL 16+ in Docker container
- **Backend**: Python + FastAPI, SQLAlchemy Core + psycopg (async-ready), Alembic migrations
- **Frontend**: React static build served by nginx reverse proxy
- **Deployment**: Docker Compose (PostgreSQL + backend + nginx+frontend), works on Windows Server
- **CLI**: Removed; all operations via API/UI only
- **File I/O**: UI-only upload/download; server-side persistent Docker volume
- **Auth**: Anonymous reads; header-based user identification (`X-User-Name`) required for mutations, users pre-registered in DB

### Key Decisions (Confirmed)

| Decision | Choice |
|----------|--------|
| Deployment target | Windows Server, Docker Compose |
| DB driver | SQLAlchemy Core (`text()` wrapped raw SQL) + psycopg |
| Migration tool | Alembic (fresh baseline, no SQLite history) |
| Data migration | No automated migration; start with fresh PostgreSQL and re-enter/import required data via UI |
| HTTPS | Not now (internal trusted network, HTTP only) |
| Authentication | Anonymous reads; `X-User-Name` required for mutation requests, no password |
| User management | Pre-registered in DB (`users` table), admin-managed |
| Audit trail | Mutation operations record user attribution where schema support is added in this phase |
| CLI | Drop entirely (API-only) |
| File storage | UI-only upload/download, persistent Docker volume |
| Local dev environment | Docker Compose (same as deployment) |
| Test database | PostgreSQL in Docker (no SQLite fallback) |

---

## 2. Architecture Overview

### Target Deployment Diagram

```
┌──────────────────────────────────────────────────┐
│                 Windows Server                   │
│                                                  │
│  ┌────────────────────────────────────────────┐  │
│  │           Docker Compose Network            │  │
│  │                                            │  │
│  │  ┌──────────┐   ┌──────────┐  ┌────────┐  │  │
│  │  │  nginx   │──▶│ backend  │  │postgres│  │  │
│  │  │ (static  │   │ (FastAPI │──│  :5432 │  │  │
│  │  │ +reverse │   │  gunicorn│  │        │  │  │
│  │  │  proxy)  │   │  +uvicorn│  └────────┘  │  │
│  │  │  :80     │   │  :8000)  │       │      │  │
│  │  └──────────┘   └──────────┘       │      │  │
│  │       │                            │      │  │
│  │       │          ┌─────────────────┘      │  │
│  │       │          │  Docker Volumes:       │  │
│  │       │          │  - pgdata (DB files)   │  │
│  │       │          │  - appdata (imports/   │  │
│  │       │          │    exports/ files)     │  │
│  │       │          └────────────────────────│  │
│  └───────│────────────────────────────────────┘  │
│          │                                       │
│          ▼                                       │
│    http://<server-ip>/     → frontend (static)   │
│    http://<server-ip>/api/ → FastAPI backend     │
└──────────────────────────────────────────────────┘
```

### Request Flow

```
Browser → nginx:80
  ├── /api/*  → proxy_pass → backend:8000
  ├── /       → serve static files (frontend dist/)
  └── /*      → try_files → index.html (SPA fallback)
```

### Authentication Flow

```
Browser request
  └─ Header: X-User-Name: alice
       │
       ▼
  nginx (pass-through)
       │
       ▼
  FastAPI middleware / dependency
    ├── For read-only requests: allow anonymous access
    ├── For mutation requests: extract X-User-Name header
    ├── Lookup user in `users` table
    ├── If missing / not found / inactive → 403 Forbidden
    └── If found → inject user context into request state
         │
         ▼
  Service layer
      └── Mutation operations receive user attribution where applicable
```

---

## 3. Phase Breakdown

### Phase 0: Preparation & Infrastructure Setup

> Set up Docker Compose skeleton, PostgreSQL container, and project tooling before touching application code.

#### 0-1. Docker Compose Configuration

Create `docker-compose.yml` at project root with three services:

| Service | Image | Ports | Volumes |
|---------|-------|-------|---------|
| `db` | `postgres:16-alpine` | `5432` (internal only) | `pgdata:/var/lib/postgresql/data` |
| `backend` | Custom Dockerfile | `8000` (internal only) | `appdata:/app/data` |
| `nginx` | `nginx:alpine` | `80:80` (host-mapped) | frontend `dist/` as static |

Environment variables in `.env`:

```env
# Database
POSTGRES_USER=materials
POSTGRES_PASSWORD=<generated>
POSTGRES_DB=materials_db
DATABASE_URL=postgresql+psycopg://materials:<password>@db:5432/materials_db

# Application
APP_DATA_ROOT=/app/data
APP_HOST=0.0.0.0
APP_PORT=8000
LOG_LEVEL=info

# CORS
CORS_ALLOWED_ORIGINS=http://localhost,http://<server-ip>
```

#### 0-2. Backend Dockerfile

```dockerfile
FROM python:3.12-slim
# Install uv, copy project, install deps, run with gunicorn+uvicorn
```

- Multi-stage build: install → runtime
- Use `gunicorn` with `uvicorn.workers.UvicornWorker`
- Expose port 8000

#### 0-3. Frontend Build + nginx Dockerfile

```dockerfile
# Stage 1: Build
FROM node:20-alpine AS build
# npm ci && npm run build

# Stage 2: Serve
FROM nginx:alpine
# Copy dist/ + nginx.conf
```

- `VITE_API_BASE=/api` baked into build
- nginx config: static files + `/api/` reverse proxy

#### 0-4. Development Docker Compose Override

Create `docker-compose.override.yml` for local development:

- Backend: mount source code, hot-reload via `uvicorn --reload`
- Frontend: mount source code, run `npm run dev` with Vite (not nginx)
- PostgreSQL: same container, port 5432 exposed to host

---

### Phase 1: Database Layer Migration (Core)

> Replace sqlite3 with SQLAlchemy Core + psycopg. This is the largest and highest-risk phase.

#### 1-1. Add Dependencies

Add to `pyproject.toml`:

```toml
dependencies = [
    # ... existing ...
    "sqlalchemy>=2.0",
    "psycopg[binary]>=3.1",
    "alembic>=1.13",
]
```

Remove: No packages to remove (sqlite3 is stdlib), but the `sqlite3` import will be eliminated.

#### 1-2. Rewrite `app/db.py` — Connection & Engine Management

**Current**: `sqlite3.connect()` with manual PRAGMAs and `row_factory`.

**Target**: SQLAlchemy `create_engine()` + connection pool.

```python
from sqlalchemy import create_engine, text
from sqlalchemy.pool import QueuePool

engine = create_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)
```

Key changes:

| Aspect | Before (SQLite) | After (PostgreSQL) |
|--------|------------------|--------------------|
| Connection | `sqlite3.connect(path)` | `engine.connect()` |
| Row factory | `sqlite3.Row` → dict-like | SQLAlchemy `Row` → `._mapping` |
| Foreign keys | `PRAGMA foreign_keys = ON` | Always on (PostgreSQL default) |
| WAL mode | `PRAGMA journal_mode = WAL` | Not needed (PostgreSQL has MVCC) |
| Thread safety | `check_same_thread=False` | Connection pool handles this |
| Transaction | `conn.execute("BEGIN")` | `with conn.begin():` |

#### 1-3. Rewrite `app/db.py` — Schema Definition

**Remove entirely**:
- All `CREATE TABLE IF NOT EXISTS` raw SQL strings
- All `CREATE INDEX IF NOT EXISTS` raw SQL strings
- All `CREATE TRIGGER` statements
- All `PRAGMA` calls
- All migration functions (`migrate_db`, `_ensure_column`, `_normalize_date_column`, etc.)

**Replace with**: Alembic-managed migrations (see Phase 1-5).

#### 1-4. Schema Translation: SQLite → PostgreSQL

Comprehensive column type mapping for all 24 tables:

| SQLite Type | PostgreSQL Type | Affected Columns |
|-------------|----------------|------------------|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `INTEGER GENERATED ALWAYS AS IDENTITY` | All 24 PK columns |
| `TEXT` (date) | `DATE` | order_date, expected_arrival, arrival_date, issue_date, planned_start, deadline, target_date, finalized_date |
| `TEXT` (timestamp) | `TIMESTAMP WITHOUT TIME ZONE` | created_at, updated_at, timestamp (transaction_log) |
| `TEXT` (general) | `TEXT` | No change needed |
| `INTEGER` (boolean-like 0/1) | `BOOLEAN` | project_id_manual (orders) |
| `REAL` | `DOUBLE PRECISION` | (if any exist) |

**Trigger replacement**:

| SQLite Trigger | PostgreSQL Replacement |
|----------------|----------------------|
| `trg_orders_validate_insert` | CHECK constraint or PL/pgSQL `BEFORE INSERT` trigger |
| `trg_orders_validate_update` | PL/pgSQL `BEFORE UPDATE` trigger |
| `trg_orders_autofill_after_insert` | PL/pgSQL `AFTER INSERT` trigger or application-level default |

**GLOB → DATE type**: Date columns becoming `DATE` type means GLOB validation is no longer needed — PostgreSQL enforces valid dates natively.

**Timestamp policy**:
- Preserve the existing fixed-JST application contract.
- Store timestamps as `TIMESTAMP WITHOUT TIME ZONE`.
- Continue generating timestamps in the application layer using JST helpers instead of relying on database/session timezone defaults.
- Avoid `NOW()` defaults for business timestamps unless the database session timezone is explicitly pinned to JST.

**Index changes**:
- All 35 existing indexes recreated with PostgreSQL syntax
- `CREATE INDEX IF NOT EXISTS` syntax preserved (PostgreSQL supports it)
- Consider partial indexes and GIN indexes for text search where beneficial

**SQL dialect changes**:

| Pattern | SQLite | PostgreSQL |
|---------|--------|------------|
| Last insert ID | `cursor.lastrowid` | `INSERT ... RETURNING id` |
| Boolean | `0` / `1` | `FALSE` / `TRUE` |
| String concat | `\|\|` | `\|\|` (same) |
| COALESCE | Same | Same |
| NULLIF | Same | Same |
| GROUP_CONCAT | `GROUP_CONCAT(x, ',')` | `STRING_AGG(x::text, ',')` |
| SUBSTR | `substr(x, start, len)` | `SUBSTRING(x FROM start FOR len)` or `substr()` |
| Date functions | `date('now')`, `strftime(...)` | `CURRENT_DATE`, `TO_CHAR(...)` |
| ON CONFLICT | `INSERT OR IGNORE` | `ON CONFLICT DO NOTHING` |
| ON CONFLICT | `INSERT OR REPLACE` | `ON CONFLICT (...) DO UPDATE SET ...` |
| Table exists check | `sqlite_master` | `information_schema.tables` |
| Column info | `PRAGMA table_info(t)` | `information_schema.columns` |
| LIKE | Case-insensitive by default | Case-sensitive; use `ILIKE` |
| Parameter placeholder | `?` | `:param` (named, via `text()`) |

#### 1-5. Alembic Setup & Initial Migration

```
backend/
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_schema.py    ← PostgreSQL-native schema
├── alembic.ini
```

- `alembic.ini` reads `DATABASE_URL` from environment
- Initial migration creates all 24 tables + indexes + trigger functions + `users` table (Phase 10)
- No migration history from SQLite era

#### 1-6. Rewrite FastAPI Dependency Injection

**Current** (`api.py`):
```python
def _db_dep(app):
    def _get_db():
        conn = get_connection(app.state.db_path)
        try:
            yield conn
        finally:
            conn.close()
    return _get_db
```

**Target**:
```python
def get_db():
    with engine.connect() as conn:
        yield conn
```

- Connection pooling handled by SQLAlchemy engine
- No manual close needed (context manager)
- Transaction management via `conn.begin()` / `conn.commit()`

#### 1-7. Rewrite `app/service.py` SQL Queries

This is the **largest single task**. The file is ~456KB with hundreds of raw SQL queries.

**Systematic approach**:

1. **Wrap all SQL in `text()`**: `conn.execute("SELECT ...")` → `conn.execute(text("SELECT ..."))`
2. **Parameter binding**: `?` → `:param` (named parameters)
3. **`lastrowid` → `RETURNING`**: All 20+ occurrences of `cursor.lastrowid`
4. **LIKE → ILIKE**: Where case-insensitive matching is intended
5. **GROUP_CONCAT → STRING_AGG**: Where used
6. **INSERT OR IGNORE → ON CONFLICT DO NOTHING**
7. **sqlite3.Row → SQLAlchemy Row**: `row["column"]` → `row._mapping["column"]` or helper
8. **Transaction pattern**: `with transaction(conn):` → `with conn.begin():`
9. **Add user attribution threading**: To mutation functions that will persist `performed_by` / `created_by` / `updated_by` (Phase 10 integration)

**Estimated scope**: ~200-300 individual SQL statement modifications.

#### 1-8. Update `app/utils.py`

- `to_dict(row)` function: Update to handle SQLAlchemy Row objects
- Date functions: No change needed (Python-side, not SQL)

#### 1-9. Update `app/config.py`

**Add new settings**:

```python
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://materials:materials@localhost:5432/materials_db")
APP_DATA_ROOT = Path(os.getenv("APP_DATA_ROOT", str(WORKSPACE_ROOT)))
IMPORTS_ROOT = Path(os.getenv("IMPORTS_ROOT", str(APP_DATA_ROOT / "imports")))
EXPORTS_ROOT = Path(os.getenv("EXPORTS_ROOT", str(APP_DATA_ROOT / "exports")))
CORS_ALLOWED_ORIGINS = os.getenv("CORS_ALLOWED_ORIGINS", "*").split(",")
APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "info")
```

**Remove**:
- `resolve_db_path()` (replaced by `DATABASE_URL`)
- `DEFAULT_DB_PATH` (no more SQLite file)
- `INVENTORY_DB_PATH` env var reference

---

### Phase 2: CLI Removal & Entrypoint Simplification

#### 2-1. Simplify `main.py`

**Remove**: All CLI subcommands (import-orders, arrival, move, consume, reserve, etc.).

**Keep**: Server entrypoint only:

```python
import uvicorn
from app.api import create_app
from app.config import APP_HOST, APP_PORT

app = create_app()

def main():
    uvicorn.run(app, host=APP_HOST, port=int(APP_PORT))

if __name__ == "__main__":
    main()
```

For production, use gunicorn directly:

```bash
gunicorn main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000
```

#### 2-2. Update `create_app()` in `api.py`

- Remove `db_path` parameter (use `DATABASE_URL` from config)
- Initialize SQLAlchemy engine in lifespan
- Run Alembic migration check on startup (optional, or require manual `alembic upgrade head`)

---

### Phase 3: Frontend Production Build Configuration

#### 3-1. API Client Simplification (`src/lib/api.ts`)

**Remove**:
- Port scanning logic (`fallbackApiBases`, `resolveApiBase`, `probingPromise`)
- Hardcoded port list `[8000, 8001, 8010, 18000]`

**Replace with**:
```typescript
const API_BASE = import.meta.env.VITE_API_BASE || "/api";
```

- Production build: `VITE_API_BASE=/api` (relative, served by same nginx)
- Dev build: `VITE_API_BASE=http://localhost:8000/api` (via docker-compose override)

#### 3-2. Vite Production Build Config

Update `vite.config.ts` to add dev proxy:

```typescript
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: "http://backend:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
```

#### 3-3. nginx Configuration

```nginx
server {
    listen 80;
    server_name _;

    root /usr/share/nginx/html;
    index index.html;

    # SPA fallback
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API reverse proxy
    location /api/ {
        proxy_pass http://backend:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 50M;
    }
}
```

#### 3-4. Add User Identity to Frontend

Frontend needs to send `X-User-Name` header with every mutation API request:

- Add user selection UI (dropdown or login-like screen on first visit)
- Store selected user in `localStorage`
- Inject `X-User-Name` header in mutating `fetch()` calls via `api.ts`
- Add `GET /api/users` endpoint to populate user list

---

### Phase 4: CORS & Security Hardening

#### 4-1. CORS Configuration

**Current**: `allow_origins=["*"]` (fully permissive).

**Target**: Configurable via `CORS_ALLOWED_ORIGINS` env var.

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

#### 4-2. Security Headers (nginx)

```nginx
add_header X-Frame-Options DENY;
add_header X-Content-Type-Options nosniff;
add_header X-XSS-Protection "1; mode=block";
```

---

### Phase 5: File Storage Adaptation

#### 5-1. Path Configuration via Environment Variables

All file paths resolved from `APP_DATA_ROOT`:

```
/app/data/                    ← APP_DATA_ROOT (Docker volume: appdata)
├── imports/
│   ├── items/
│   │   ├── unregistered/
│   │   └── registered/
│   └── orders/
│       ├── unregistered/{csv_files,pdf_files}/
│       └── registered/{csv_files,pdf_files}/
└── exports/
```

#### 5-2. Ensure UI-Only File Access

Current UI-driven file operations (keep as-is):
- `POST /api/items/import` — file upload via multipart form
- `POST /api/orders/import` — file upload via multipart form
- `GET /api/procurement-batches/{id}/export.csv` — file download
- `GET /api/workspace/planning-export` — file download

CLI batch commands (`register-unregistered-items`, `import-unregistered-orders`) are being dropped with CLI removal (Phase 2). If batch import workflows are still needed later, they can be re-implemented as API endpoints accepting file uploads.

#### 5-3. Docker Volume Configuration

```yaml
volumes:
  pgdata:
    driver: local
  appdata:
    driver: local
```

---

### Phase 6: Process Management & Production Server

#### 6-1. Backend Production Server

```dockerfile
CMD ["gunicorn", "main:app", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-w", "4", \
     "-b", "0.0.0.0:8000", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
```

- Worker count: configurable via `WEB_CONCURRENCY` env var
- Graceful shutdown handled by Docker stop signal

#### 6-2. Health Checks

```yaml
db:
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U materials"]
    interval: 10s
    timeout: 5s
    retries: 5

backend:
  depends_on:
    db:
      condition: service_healthy
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
    interval: 15s
    timeout: 5s
    retries: 3
```

#### 6-3. Logging

- Backend logs to stdout/stderr (Docker captures)
- nginx access/error logs to stdout/stderr
- PostgreSQL logs to Docker
- View logs: `docker compose logs -f backend`

---

### Phase 7: Fresh-Start Data Cutover

> No SQLite-to-PostgreSQL data migration script is planned. Cut over with a fresh PostgreSQL database and load only the data you still need through the new UI/import flows.

#### 7-1. Cutover Approach

**Approach**:
1. Deploy the PostgreSQL-backed application with an empty database.
2. Seed required users in `users` before opening mutation flows to operators.
3. Recreate or import active master data through the supported UI/API flows:
   - manufacturers / suppliers
   - items
   - quotations / orders as needed
   - projects / requirements
   - open reservations if still relevant
4. Validate critical business flows on the new system before retiring the SQLite-based workflow.

**Why this is acceptable here**:
- Existing data volume is small enough for manual re-entry/import.
- This avoids carrying forward legacy SQLite normalization and migration complexity.
- It reduces risk versus maintaining a one-off data-conversion script for a moving schema.

---

### Phase 8: Test Suite Migration

#### 8-1. Test Configuration for PostgreSQL

Update `conftest.py`:

```python
@pytest.fixture(scope="session")
def pg_engine():
    test_url = os.getenv("TEST_DATABASE_URL",
        "postgresql+psycopg://materials:materials@localhost:5432/materials_test")
    engine = create_engine(test_url)
    # Run Alembic migrations
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", str(test_url))
    command.upgrade(alembic_cfg, "head")
    yield engine
    engine.dispose()

@pytest.fixture
def conn(pg_engine):
    with pg_engine.connect() as connection:
        trans = connection.begin()
        yield connection
        trans.rollback()
```

#### 8-2. Docker Compose for Tests

```yaml
# docker-compose.test.yml
services:
  db-test:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: materials
      POSTGRES_PASSWORD: test
      POSTGRES_DB: materials_test
    ports:
      - "5433:5432"
    tmpfs:
      - /var/lib/postgresql/data
```

#### 8-3. Update Test Assertions

- Fix date/timestamp comparison for PostgreSQL result types and confirm JST-formatted timestamp expectations
- Fix boolean comparison (`True`/`False` instead of `1`/`0`)
- Update row access patterns for SQLAlchemy Row objects

---

### Phase 9: Documentation Updates

| Document | Changes |
|----------|---------|
| `specification.md` | Database: SQLite → PostgreSQL; remove CLI spec; add Docker deployment; add user/audit model |
| `documents/technical_documentation.md` | Architecture diagram, DB section, deployment section, auth section |
| `documents/source_current_state.md` | Full snapshot update |
| `documents/change_log.md` | Add migration entry |
| `README.md` (root) | New setup instructions (Docker Compose) |
| `backend/README.md` | Update for PostgreSQL + Docker |
| `frontend/README.md` | Update for production build |

**New files**:

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Production composition |
| `docker-compose.override.yml` | Development overrides |
| `docker-compose.test.yml` | Test database |
| `backend/Dockerfile` | Backend container |
| `frontend/Dockerfile` | Frontend build + nginx |
| `frontend/nginx.conf` | Reverse proxy config |
| `.env.example` | Environment variable template |

---

### Phase 10: User Management & Audit Trail

> Anonymous reads with header-based user identification for mutation requests, plus mutation audit attribution where this phase adds schema support.

#### 10-1. Database Schema: `users` Table

```sql
CREATE TABLE users (
    user_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'operator',  -- admin, operator, viewer (future RBAC)
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITHOUT TIME ZONE
);

CREATE UNIQUE INDEX idx_users_username ON users (username);
```

Roles are stored for future RBAC but **not enforced** in this phase.

#### 10-2. Add Audit Columns to Existing Tables

Add to the primary tables whose mutations will be attributed in this phase:

| Table | New Columns |
|-------|-------------|
| `transaction_log` | `performed_by INTEGER REFERENCES users(user_id)` |
| `orders` | `created_by INTEGER REFERENCES users(user_id)`, `updated_by INTEGER REFERENCES users(user_id)` |
| `reservations` | `created_by`, `updated_by` |
| `items_master` | `created_by`, `updated_by` |
| `projects` | `created_by`, `updated_by` |
| `procurement_batches` | `created_by`, `updated_by` |
| `procurement_lines` | `created_by`, `updated_by` |
| `quotations` | `created_by`, `updated_by` |
| `import_jobs` | `created_by` |
| `inventory_ledger` | `updated_by` |

These columns are **nullable** initially to allow system-created rows, bootstrapping, and incremental adoption during the PostgreSQL transition.

#### 10-3. FastAPI Middleware: User Resolution

```python
from starlette.middleware.base import BaseHTTPMiddleware

class UserIdentityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.method in {"GET", "HEAD", "OPTIONS"} or request.url.path == "/api/health":
            return await call_next(request)

        username = request.headers.get("X-User-Name")

        if not username:
            return JSONResponse(status_code=403,
                content={"status": "error", "error": {"code": "USER_REQUIRED",
                    "message": "X-User-Name header is required"}})

        # Lookup user in DB
        user = lookup_user(username)
        if not user or not user.is_active:
            return JSONResponse(status_code=403,
                content={"status": "error", "error": {"code": "USER_NOT_FOUND",
                    "message": f"User '{username}' is not registered or inactive"}})

        request.state.user = user
        return await call_next(request)
```

#### 10-4. User Management API Endpoints

| Endpoint | Method | Description | Auth |
|----------|--------|-------------|------|
| `GET /api/users` | GET | List active users for login/user picker | Anonymous read |
| `GET /api/users/{id}` | GET | Get user detail | Anonymous read |
| `POST /api/users` | POST | Create user | Admin only (future) |
| `PUT /api/users/{id}` | PUT | Update user | Admin only (future) |
| `DELETE /api/users/{id}` | DELETE | Deactivate user | Admin only (future) |
| `GET /api/users/me` | GET | Current user from header | Named user |

For now, user management can be done via direct DB inserts or a seed script. Admin-only enforcement is deferred to RBAC phase.

#### 10-5. Service Layer Changes

All mutation functions gain a `user_id: int | None` parameter:

```python
# Before
def create_item(conn, data: dict) -> dict:
    ...

# After
def create_item(conn, data: dict, user_id: int | None = None) -> dict:
    # INSERT INTO items_master (..., created_by) VALUES (..., :user_id)
    ...
```

#### 10-6. Frontend: User Selection

- On first visit (no `localStorage` user), show a user picker screen
- `GET /api/users` populates the picker
- Selected user stored in `localStorage` as `username`
- Mutation API calls include `X-User-Name: <username>` header
- User switcher accessible from the app shell header

---

## 4. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| SQL dialect differences cause runtime errors | High | Comprehensive SQL audit completed; test all 164 tests against PG |
| `lastrowid` → `RETURNING` refactor misses edge cases | High | All 20+ occurrences cataloged; systematic replacement |
| Date/timestamp conversion breaks business logic | Medium | Keep DATE columns for business dates; keep JST application-generated timestamps |
| LIKE → ILIKE changes search behavior | Medium | Audit all LIKE queries; some may need case-sensitive matching |
| Transaction semantics differ (PG stricter) | Medium | PG auto-aborts on error within transaction; test concurrent scenarios |
| File path references in DB (pdf_link) | Low | Already relative paths; ensure `APP_DATA_ROOT` prefix works |
| Docker on Windows Server performance | Low | Use WSL2 backend for Docker Desktop |
| Anonymous read endpoints expose more metadata than desired | Low | Keep anonymous-read scope explicit and limited to intended read endpoints |
| User identity header spoofing | Low | Accepted risk for trusted internal network |

---

## 5. Implementation Order (Recommended)

```
Phase 0: Infrastructure Setup
    ├── 0-1. docker-compose.yml
    ├── 0-2. Backend Dockerfile
    ├── 0-3. Frontend Dockerfile + nginx
    └── 0-4. Dev override
         │
Phase 1: Database Migration (Critical Path)
    ├── 1-1. Add dependencies (SQLAlchemy, psycopg, Alembic)
    ├── 1-2. Rewrite db.py connection/engine
    ├── 1-3. Remove old schema DDL from db.py
    ├── 1-4. Schema translation (types, triggers, indexes)
    ├── 1-5. Alembic setup + initial migration
    ├── 1-6. Rewrite FastAPI dependency injection
    ├── 1-7. Rewrite service.py SQL queries  ← LARGEST TASK
    ├── 1-8. Update utils.py (Row handling)
    └── 1-9. Update config.py (env vars)
         │
Phase 10: User Management & Audit Trail
    ├── 10-1. users table schema
    ├── 10-2. Audit columns on existing tables
    ├── 10-3. FastAPI user middleware
    ├── 10-4. User management endpoints
    └── 10-5. Service layer user_id threading
         │
Phase 8: Test Suite Migration (Validates Phase 1 + 10)
    ├── 8-1. Update conftest.py for PostgreSQL
    ├── 8-2. Docker Compose for tests
    └── 8-3. Fix test assertions
         │
    ┌────┴────┐  (Parallel from here)
    │         │
Phase 2    Phase 3 + 3-4
CLI Drop   Frontend Build + User Picker
    │         │
Phase 4    Phase 5
CORS       File Storage
    │         │
Phase 6    Phase 7
Process    Fresh Cutover
    │         │
    └────┬────┘
         │
Phase 9: Documentation
```

---

## 6. Verification Checklist

- [ ] All 164+ backend tests pass against PostgreSQL
- [ ] Frontend production build succeeds (`npm run build`)
- [ ] Docker Compose starts all services cleanly (`docker compose up`)
- [ ] Health endpoint responds: `GET /api/health → {"status": "ok"}`
- [ ] User creation and listing works
- [ ] `X-User-Name` header enforced on mutation endpoints only
- [ ] CRUD operations work through UI (items, orders, inventory)
- [ ] Audit columns populated on the tables covered by this phase
- [ ] CSV/PDF import via UI uploads correctly
- [ ] CSV export via UI downloads correctly
- [ ] Fresh PostgreSQL deployment can be initialized and operated without SQLite data migration
- [ ] nginx serves frontend at `/` and proxies `/api/` correctly
- [ ] No SQLite references remain in codebase (`grep -r sqlite`)
- [ ] All documentation updated
- [ ] `.env.example` covers all required variables

---

## 7. Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `POSTGRES_USER` | Yes | — | PostgreSQL user (docker-compose) |
| `POSTGRES_PASSWORD` | Yes | — | PostgreSQL password (docker-compose) |
| `POSTGRES_DB` | Yes | — | PostgreSQL database name (docker-compose) |
| `APP_DATA_ROOT` | No | `/app/data` | Root directory for file storage |
| `IMPORTS_ROOT` | No | `$APP_DATA_ROOT/imports` | Import files directory |
| `EXPORTS_ROOT` | No | `$APP_DATA_ROOT/exports` | Export files directory |
| `APP_HOST` | No | `0.0.0.0` | Backend listen address |
| `APP_PORT` | No | `8000` | Backend listen port |
| `LOG_LEVEL` | No | `info` | Logging level |
| `CORS_ALLOWED_ORIGINS` | No | `*` | Comma-separated allowed origins |
| `WEB_CONCURRENCY` | No | `4` | Gunicorn worker count |
| `VITE_API_BASE` | No | `/api` | Frontend API base URL (build-time) |
| `TEST_DATABASE_URL` | No | — | Test database connection string |
