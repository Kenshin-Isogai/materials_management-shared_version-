# Environment and Runtime Matrix

## Purpose

This file defines the rollout configuration contract.

It focuses on which variables matter, where they are consumed, and whether they can be finalized before a real GCP project exists.

## Classification legend

- **Service**: where the variable is consumed
- **Secret**: whether it should be treated as sensitive
- **Stage**:
  - `now`: can be decided or documented before a GCP project exists
  - `project`: requires a real GCP project or real cloud resources
- **Notes**: rollout-specific expectation

## Backend variables

| Variable | Service | Secret | Stage | Notes |
|---|---|---:|---|---|
| `APP_RUNTIME_TARGET` | Backend | No | now | Use `cloud_run` for the target deployment posture |
| `DATABASE_URL` | Backend | Yes | project | Final value depends on real Cloud SQL naming and Secret Manager wiring |
| `INSTANCE_CONNECTION_NAME` | Backend | No | project | Requires the real Cloud SQL instance |
| `STORAGE_BACKEND` | Backend | No | now | Use `gcs` in cloud, `local` locally |
| `GCS_BUCKET` | Backend | No | project | Requires the real bucket name |
| `GCS_OBJECT_PREFIX` | Backend | No | now | Prefix pattern can be decided now; final value may still wait on environment naming |
| `CORS_ALLOWED_ORIGINS` | Backend | No | project | Final value depends on the real frontend URL |
| `BACKEND_PUBLIC_BASE_URL` | Backend | No | project | Final value depends on the real backend URL |
| `FRONTEND_PUBLIC_BASE_URL` | Backend | No | project | Final value depends on the real frontend URL |
| `AUTO_MIGRATE_ON_STARTUP` | Backend | No | now | Keep `0` for Cloud Run |
| `DB_POOL_SIZE` | Backend | No | now | Can be documented and tuned now |
| `DB_MAX_OVERFLOW` | Backend | No | now | Can be documented and tuned now |
| `DB_POOL_TIMEOUT` | Backend | No | now | Can be documented and tuned now |
| `DB_POOL_RECYCLE_SECONDS` | Backend | No | now | Cloud-friendly default can be documented now |
| `WEB_CONCURRENCY` | Backend | No | now | Cloud default can be decided now and adjusted later |
| `MAX_UPLOAD_BYTES` | Backend | No | now | First-rollout ceiling remains 32 MB |
| `HEAVY_REQUEST_TARGET_SECONDS` | Backend | No | now | First-rollout target remains about 60 seconds |
| `CLOUD_RUN_CONCURRENCY_TARGET` | Backend | No | now | Conservative first-rollout target remains about 10 |
| `LOG_LEVEL` | Backend | No | now | Standard runtime setting |
| `PORT` | Backend | No | project | Provided by Cloud Run at runtime; no manual final value needed |

## Frontend variables

| Variable | Service | Secret | Stage | Notes |
|---|---|---:|---|---|
| `VITE_API_BASE` | Frontend | No | project | Contract is already fixed, but the final value depends on the real backend URL and is baked in at build time |

## Local-only or de-emphasized variables

| Variable | Why it is not part of the durable cloud contract |
|---|---|
| `APP_DATA_ROOT` | Acceptable for temporary local working files, not durable cloud storage |
| `IMPORTS_ROOT` | Local compatibility path, not a durable cloud contract |
| `EXPORTS_ROOT` | Local compatibility path, not a durable cloud contract |
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
