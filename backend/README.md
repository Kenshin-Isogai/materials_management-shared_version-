## Optical Component Inventory Management Backend

### Setup

```bash
uv sync
```

### Run API Server

```bash
uv run main.py
```

API base URL: `http://127.0.0.1:8000/api`

### Database Bootstrap

```bash
uv run alembic upgrade head
```

The backend is now PostgreSQL-first and expects `DATABASE_URL` to be set.

### Cloud Run Runtime

- Set `APP_RUNTIME_TARGET=cloud_run`
- `PORT` is used automatically for the listener port
- If `APP_DATA_ROOT` is not set, runtime file roots default under the OS temp directory
- In Cloud Run mode, startup skips legacy workspace/import folder migration and only creates the required empty runtime directories
- In Cloud Run mode, `AUTO_MIGRATE_ON_STARTUP` now defaults to off; run `uv run alembic upgrade head` as a deployment step instead
- DB connection pool behavior is environment-driven through `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, and `DB_POOL_RECYCLE_SECONDS`
- Request/upload guardrails are environment-driven through `MAX_UPLOAD_BYTES`, `HEAVY_REQUEST_TARGET_SECONDS`, and `CLOUD_RUN_CONCURRENCY_TARGET`
- Cloud deployment metadata is explicit through `INSTANCE_CONNECTION_NAME`, `STORAGE_BACKEND`, `GCS_BUCKET`, `GCS_OBJECT_PREFIX`, `BACKEND_PUBLIC_BASE_URL`, and `FRONTEND_PUBLIC_BASE_URL`
- Durable storage now supports `STORAGE_BACKEND=gcs` with `GCS_BUCKET` / `GCS_OBJECT_PREFIX` for Cloud Run object storage, while `local` remains the default for local/shared-server use
- `CORS_ALLOWED_ORIGINS` should be set explicitly to the frontend origin for split Cloud Run services

### Docker

```bash
docker compose up --build
```

### Backend Tests (Docker PostgreSQL)

From the repository root:

```powershell
docker compose -f docker-compose.test.yml up -d db-test
$env:TEST_DATABASE_URL = "postgresql+psycopg://develop:test@localhost:5433/materials_test"
$env:PYTHONPATH = "backend"
uv run --project backend python -m pytest --import-mode=importlib
```

### Authentication

- API auth uses `Authorization: Bearer <JWT>`.
- `AUTH_MODE` controls bearer-token enforcement: `none`, `oidc_dry_run`, or `oidc_enforced`.
- `RBAC_MODE` controls role enforcement: `none`, `rbac_dry_run`, or `rbac_enforced`.
- `JWT_VERIFIER` now supports `shared_secret` for local/test fixture tokens and `jwks` for deployed OIDC/JWKS verification.
- Set `OIDC_JWKS_URL` when `JWT_VERIFIER=jwks`.
- Verified OIDC claims are mapped to active `users` rows through `email`, `identity_provider` + `external_subject`, and optional `hosted_domain`.
- `DIAGNOSTICS_AUTH_ROLE` controls `GET /api/health` and `GET /api/auth/capabilities` exposure.
  - local default: `public`
  - Cloud Run default: `admin`
- Bootstrap exception: `POST /api/users` remains available without a bearer token only when there are zero active users.
