# Environment and Runtime Matrix

## Purpose

This document lists the repository runtime variables and deployment-facing configuration relevant to the GCP rollout.

Backward compatibility is explicitly out of scope.

## Classification Legend

- **Service**: where the variable is consumed
- **Secret**: whether it should be treated as sensitive
- **Target**: where it matters most (`local`, `cloud`, or `both`)
- **Action**: what should happen during the rollout

## Backend runtime variables

| Variable | Service | Secret | Target | Current use | Action |
|---|---|---:|---|---|---|
| `DATABASE_URL` | Backend | Yes | both | DB connection string in `backend\app\config.py` and `backend\app\db.py` | Keep, but source from managed secrets in cloud deployment |
| `APP_RUNTIME_TARGET` | Backend | No | both | Runtime posture selection in `backend\app\config.py` | Keep, but use explicitly in deployment config |
| `APP_DATA_ROOT` | Backend | No | both | Base local filesystem root in `backend\app\config.py` | De-emphasize for cloud; keep only for temporary local working files if still needed |
| `IMPORTS_ROOT` | Backend | No | local | Overrides local imports root in `backend\app\config.py` | Avoid as a durable cloud contract |
| `EXPORTS_ROOT` | Backend | No | local | Overrides local exports root in `backend\app\config.py` | Avoid as a durable cloud contract |
| `ITEMS_IMPORT_MAX_CONSOLIDATED_ROWS` | Backend | No | both | Consolidation chunk size in `backend\app\config.py` | Keep, but document cost/performance impact |
| `PORT` | Backend | No | cloud | Used by `backend\app\config.py` and container startup | Keep |
| `APP_PORT` | Backend | No | local | Local fallback port in `backend\app\config.py` | Keep for local only |
| `APP_HOST` | Backend | No | local | Local bind host in `backend\app\config.py` | Keep for local only |
| `LOG_LEVEL` | Backend | No | both | Logging level in `backend\app\config.py` and `backend\main.py` | Keep |
| `WEB_CONCURRENCY` | Backend | No | both | Gunicorn workers in compose and Dockerfile | Keep, but align with Cloud SQL pool/concurrency plan |
| `AUTO_MIGRATE_ON_STARTUP` | Backend | No | both | Startup migration gate in `backend\app\config.py` and `backend\app\api.py`; now defaults to off in Cloud Run and on locally | Keep for local/test bootstrap, disable in production Cloud Run |
| `INVENTORY_AUTH_MODE` | Backend | No | both | Auth posture mode in `backend\app\config.py` | Keep, but treat current modes as transitional |
| `CORS_ALLOWED_ORIGINS` | Backend | No | both | Origin parsing in `backend\app\config.py`; middleware use in `backend\app\api.py`; now defaults to localhost-only values locally and empty in Cloud Run | Keep, and require explicit cloud values |
| `K_SERVICE` | Backend | No | cloud | Implicit Cloud Run detection in `backend\app\config.py` | No code change required; deployment-provided |

## Frontend build/runtime variables

| Variable | Service | Secret | Target | Current use | Action |
|---|---|---:|---|---|---|
| `VITE_API_BASE` | Frontend | No | both | API base in `frontend\src\lib\api.ts`; build arg in `frontend\Dockerfile`; client now normalizes relative and absolute values | Keep; use an absolute backend `/api` URL for split Cloud Run services |

## Local Docker Compose variables already visible in the repo

| Variable | Service | Secret | Target | Current use | Action |
|---|---|---:|---|---|---|
| `POSTGRES_USER` | DB | Yes | local | Compose DB bootstrap | Local/dev only |
| `POSTGRES_PASSWORD` | DB | Yes | local | Compose DB bootstrap | Local/dev only |
| `POSTGRES_DB` | DB | No | local | Compose DB bootstrap | Local/dev only |

## Additional recommended variables for the rollout

These are not yet the documented canonical repository contract, but they are recommended targets for implementation.

| Variable | Service | Secret | Target | Why add it |
|---|---|---:|---|---|
| `DB_POOL_SIZE` | Backend | No | both | Externalize SQLAlchemy pool sizing |
| `DB_MAX_OVERFLOW` | Backend | No | both | Externalize burst connection behavior |
| `DB_POOL_TIMEOUT` | Backend | No | both | Make connection wait behavior explicit |
| `DB_POOL_RECYCLE_SECONDS` | Backend | No | cloud | Improve long-lived connection handling |
| `GCS_BUCKET_ARTIFACTS` | Backend | No | cloud | Durable storage for generated artifacts |
| `GCS_BUCKET_ARCHIVES` | Backend | No | cloud | Durable import/archive storage if retained |
| `GCS_BUCKET_STAGING` | Backend | No | cloud | Durable or multi-step staging if required |
| `GCS_OBJECT_PREFIX` | Backend | No | cloud | Namespace separation inside buckets |
| `FRONTEND_PUBLIC_BASE_URL` | Frontend | No | cloud | Optional explicit public URL handling |
| `BACKEND_PUBLIC_BASE_URL` | Frontend/Backend | No | cloud | Optional explicit service-to-service/browser endpoint target |

## Runtime surfaces that are not pure environment variables but still matter

### Backend startup path

- `backend\Dockerfile`
- `backend\main.py`
- `backend\app\api.py`
- `backend\app\db.py`

These files together define:

- process start command
- Gunicorn/Uvicorn worker behavior
- migration timing
- DB engine initialization

### Frontend delivery path

- `frontend\Dockerfile`
- `frontend\nginx.conf`
- `frontend\src\lib\api.ts`

These files together define:

- whether API routing is same-origin or cross-origin
- whether nginx remains part of the cloud deployment
- where browser uploads and downloads are sent

## Rollout recommendations

1. Keep only variables that express durable target behavior.
2. Avoid preserving variables whose main purpose is legacy local folder compatibility.
3. Make production-secret sourcing explicit rather than implicit.
4. Keep cloud and local defaults intentionally different where needed.
