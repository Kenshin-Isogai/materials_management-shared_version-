# Environment and Runtime Matrix

## Purpose

This file defines the GCP runtime/deployment variable contract.

It focuses on:

- which variables matter in cloud operation
- whether they are secrets
- whether they can be finalized before a real GCP project exists

## Classification legend

- **Service**: where the variable is consumed
- **Secret**: whether it should be treated as sensitive
- **Stage**:
  - `now`: can be decided before a GCP project exists
  - `project`: depends on real cloud resources or real service URLs

## Backend variables

| Variable | Service | Secret | Stage | Notes |
|---|---|---:|---|---|
| `APP_RUNTIME_TARGET` | Backend | No | now | Use `cloud_run` in Cloud Run |
| `DATABASE_URL` | Backend | Yes | project | Final value depends on real Cloud SQL naming and Secret Manager wiring |
| `INSTANCE_CONNECTION_NAME` | Backend | No | project | Real Cloud SQL instance identifier |
| `STORAGE_BACKEND` | Backend | No | now | Use `gcs` in cloud |
| `GCS_BUCKET` | Backend | No | project | Real bucket name per environment |
| `GCS_OBJECT_PREFIX` | Backend | No | now | Prefix pattern can be decided now; exact value may still depend on environment naming |
| `CORS_ALLOWED_ORIGINS` | Backend | No | project | Final value depends on the real frontend URL |
| `BACKEND_PUBLIC_BASE_URL` | Backend | No | project | Final value depends on the real backend URL |
| `FRONTEND_PUBLIC_BASE_URL` | Backend | No | project | Final value depends on the real frontend URL |
| `AUTO_MIGRATE_ON_STARTUP` | Backend | No | now | Keep `0` for Cloud Run |
| `DB_POOL_SIZE` | Backend | No | now | Tune conservatively for Cloud SQL |
| `DB_MAX_OVERFLOW` | Backend | No | now | Tune conservatively for Cloud SQL |
| `DB_POOL_TIMEOUT` | Backend | No | now | Tune conservatively for Cloud SQL |
| `DB_POOL_RECYCLE_SECONDS` | Backend | No | now | Keep finite recycling in cloud |
| `WEB_CONCURRENCY` | Backend | No | now | Keep aligned with DB capacity and Cloud Run concurrency |
| `MAX_UPLOAD_BYTES` | Backend | No | now | First-rollout ceiling remains 32 MB |
| `HEAVY_REQUEST_TARGET_SECONDS` | Backend | No | now | First-rollout target remains about 60 seconds |
| `CLOUD_RUN_CONCURRENCY_TARGET` | Backend | No | now | Conservative first-rollout target remains about 10 |
| `LOG_LEVEL` | Backend | No | now | Standard runtime setting |
| `PORT` | Backend | No | project | Provided by Cloud Run at runtime |

## Frontend variables

| Variable | Service | Secret | Stage | Notes |
|---|---|---:|---|---|
| `VITE_API_BASE` | Frontend | No | project | Final value depends on the real backend URL and is baked in at build time |

## Local-only or de-emphasized variables

| Variable | Why it is not part of the durable cloud contract |
|---|---|
| `APP_DATA_ROOT` | Acceptable for temporary local working files only |
| `IMPORTS_ROOT` | Local compatibility path, not durable cloud state |
| `EXPORTS_ROOT` | Local compatibility path, not durable cloud state |
| `APP_HOST` | Local bind behavior only |
| `APP_PORT` | Local fallback only |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Local Docker Compose bootstrap only |

## Canonical value patterns that can be decided now

- `APP_RUNTIME_TARGET=cloud_run`
- `AUTO_MIGRATE_ON_STARTUP=0`
- `STORAGE_BACKEND=gcs`
- `MAX_UPLOAD_BYTES=33554432`
- `HEAVY_REQUEST_TARGET_SECONDS=60`
- `CLOUD_RUN_CONCURRENCY_TARGET=10`
- `VITE_API_BASE=https://<backend-service-url>/api`
- `DATABASE_URL=postgresql+psycopg://<user>:<password>@/<db-name>?host=/cloudsql/<project>:<region>:<instance>`

## Values that cannot be finalized yet

- actual frontend URL
- actual backend URL
- actual bucket name
- actual object prefix by environment
- actual Cloud SQL instance name
- actual Secret Manager secret names

## Operational note

A correct environment contract is necessary, but not sufficient, for safe production use.

The following still need separate operational ownership:

- backup and restore
- deployment rollback
- monitoring and alerting
- stronger production authentication

## Repo-visible recovery contract

Even before a real GCP project exists, the backend now treats the following as the expected recovery contract:

- Cloud SQL automated backups are required
- Cloud SQL PITR is required for `staging` and `prod`
- Cloud SQL restore should default to restore-into-new-instance then cut over after validation
- GCS should use one bucket per environment with fixed `staging` / `exports` / `artifacts` / `archives` prefixes
- GCS retention target remains:
  - `staging`: 7 days
  - `exports`: 30 days
  - `artifacts`: 90 days
  - `archives`: no automatic deletion
- GCS object versioning policy must be explicitly decided before production cutover

This contract is exposed through `GET /api/health` as a repo-side diagnostic summary, but it is not proof that live Cloud SQL or GCS settings are already enabled.
