# Cloud Run Deployment Runbook

## Purpose

This runbook is for the phase after a real GCP project exists.

Use `implementation_plan.md` and `migration_checklist.md` first if you are still cleaning up the repository before project creation.

## What must already be true before using this runbook

- frontend/backend split-service Cloud Run contract is finalized
- frontend no longer relies on Docker-local backend proxying for production behavior
- production migration strategy is externalized
- remaining cloud-conflicting local compatibility paths are understood or removed

## Inputs you do not have until a GCP project exists

- GCP project ID
- region
- Artifact Registry repository
- Cloud Run frontend service name
- Cloud Run backend service name
- Cloud SQL instance name
- `INSTANCE_CONNECTION_NAME`
- GCS bucket name
- Secret Manager secret names
- real frontend and backend public URLs

## Canonical backend environment contract

Use values in this shape:

```text
APP_RUNTIME_TARGET=cloud_run
AUTO_MIGRATE_ON_STARTUP=0
STORAGE_BACKEND=gcs
GCS_BUCKET=<env-bucket>
GCS_OBJECT_PREFIX=<base-prefix>
INSTANCE_CONNECTION_NAME=<project>:<region>:<cloud-sql-instance>
DATABASE_URL=postgresql+psycopg://<user>:<password>@/<db-name>?host=/cloudsql/<project>:<region>:<cloud-sql-instance>
CORS_ALLOWED_ORIGINS=https://<frontend-service-url>
BACKEND_PUBLIC_BASE_URL=https://<backend-service-url>
FRONTEND_PUBLIC_BASE_URL=https://<frontend-service-url>
MAX_UPLOAD_BYTES=33554432
HEAVY_REQUEST_TARGET_SECONDS=60
CLOUD_RUN_CONCURRENCY_TARGET=10
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE_SECONDS=1800
WEB_CONCURRENCY=2
```

## Canonical frontend build contract

Build the frontend with:

```text
VITE_API_BASE=https://<backend-service-url>/api
```

## Recommended deployment order

1. Create the GCP project and enable required services
2. Create Artifact Registry
3. Create Cloud SQL
4. Create the GCS bucket
5. Create Secret Manager entries
6. Build and push backend and frontend images
7. Run Alembic through a one-off Cloud Run Job or equivalent
8. Deploy the backend Cloud Run service
9. Deploy the frontend Cloud Run service
10. Validate health, browser access, mutations, and durable file flows

## Example commands after project creation

```powershell
gcloud auth configure-docker <region>-docker.pkg.dev
docker build -t <region>-docker.pkg.dev/<project>/<repo>/materials-backend:<tag> .\backend
docker build -t <region>-docker.pkg.dev/<project>/<repo>/materials-frontend:<tag> --build-arg VITE_API_BASE=https://<backend-service-url>/api .\frontend
docker push <region>-docker.pkg.dev/<project>/<repo>/materials-backend:<tag>
docker push <region>-docker.pkg.dev/<project>/<repo>/materials-frontend:<tag>
```

Migration job pattern:

```powershell
gcloud run jobs deploy materials-backend-migrate `
  --image <region>-docker.pkg.dev/<project>/<repo>/materials-backend:<tag> `
  --region <region> `
  --set-cloudsql-instances <project>:<region>:<instance> `
  --set-env-vars APP_RUNTIME_TARGET=cloud_run,AUTO_MIGRATE_ON_STARTUP=0 `
  --set-secrets DATABASE_URL=<secret-name>:latest `
  --command uv `
  --args run,alembic,upgrade,head
```

## Validation after deployment

### Backend validation

- `GET /api/health`
- confirm `runtime_target = cloud_run`
- confirm `migration_strategy = external`
- confirm `storage.backend = gcs`
- confirm Cloud SQL connection metadata is populated as expected

### Browser validation

- open the frontend
- verify read/list pages load
- select or create an active user
- execute at least one mutation using `X-User-Name`
- execute one artifact-producing flow
- execute one durable archive or import-history flow

## Important warnings

- `X-User-Name` remains temporary and is not a long-term production trust boundary
- the backend remains browser-reachable in the first rollout
- increase concurrency only after observing Cloud SQL connection behavior
- if any remaining local compatibility flow still matters, validate it explicitly before cutover
