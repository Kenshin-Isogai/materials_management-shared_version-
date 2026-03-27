# Cloud Run Deployment Runbook

## Purpose

This runbook describes the minimum deployment steps to run the current repository on:

- frontend on Cloud Run
- backend on Cloud Run
- PostgreSQL on Cloud SQL
- durable file/object storage on GCS

It is intentionally concrete and optimized for first rollout execution, not for preserving older shared-server behavior.

## Current implementation assumptions

- Backend runtime target: `APP_RUNTIME_TARGET=cloud_run`
- Backend durable storage: `STORAGE_BACKEND=gcs`
- Backend durable object bucket: `GCS_BUCKET`
- Optional shared object prefix: `GCS_OBJECT_PREFIX`
- Backend browser traffic is cross-origin from the frontend service
- Mutation identity is still temporarily `X-User-Name`
- Alembic runs as a controlled deployment step, not as normal request-serving startup

## Prerequisites

Before deploying, prepare:

1. A GCP project with billing enabled.
2. Artifact Registry for container images.
3. A Cloud SQL PostgreSQL instance.
4. A GCS bucket for this environment.
5. Secret Manager entries for DB/app secrets.
6. Two Cloud Run services:
   - frontend
   - backend

## Recommended resource naming

Use environment-specific names, for example:

- Cloud Run backend service: `materials-backend-dev`
- Cloud Run frontend service: `materials-frontend-dev`
- Cloud SQL instance: `materials-pg-dev`
- GCS bucket: `materials-dev-app`
- Artifact Registry repository: `materials`

## Required backend environment

Set these on the backend Cloud Run service:

```text
APP_RUNTIME_TARGET=cloud_run
AUTO_MIGRATE_ON_STARTUP=0
STORAGE_BACKEND=gcs
GCS_BUCKET=<env-bucket>
GCS_OBJECT_PREFIX=<optional-shared-prefix>
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

Notes:

- Keep `AUTO_MIGRATE_ON_STARTUP=0`.
- Keep `STORAGE_BACKEND=gcs` in cloud.
- Start conservatively with `WEB_CONCURRENCY=2` and Cloud Run concurrency near `10`.

## Required frontend environment

Build the frontend with:

```text
VITE_API_BASE=https://<backend-service-url>/api
```

The frontend service does not need DB or GCS credentials.

## Secret Manager recommendations

At minimum, keep these values in Secret Manager:

- database password
- full `DATABASE_URL` or the user/password components used to construct it
- any future auth/session secrets once stronger auth is introduced

## Build and push images

Example commands:

```powershell
gcloud auth configure-docker <region>-docker.pkg.dev
docker build -t <region>-docker.pkg.dev/<project>/<repo>/materials-backend:<tag> .\backend
docker build -t <region>-docker.pkg.dev/<project>/<repo>/materials-frontend:<tag> --build-arg VITE_API_BASE=https://<backend-service-url>/api .\frontend
docker push <region>-docker.pkg.dev/<project>/<repo>/materials-backend:<tag>
docker push <region>-docker.pkg.dev/<project>/<repo>/materials-frontend:<tag>
```

## Run migrations

Run Alembic before shifting traffic to the new backend revision.

One practical option is a one-off job/container run using the same backend image:

```powershell
gcloud run jobs deploy materials-backend-migrate `
  --image <region>-docker.pkg.dev/<project>/<repo>/materials-backend:<tag> `
  --region <region> `
  --set-cloudsql-instances <project>:<region>:<instance> `
  --set-env-vars APP_RUNTIME_TARGET=cloud_run,AUTO_MIGRATE_ON_STARTUP=0 `
  --set-secrets DATABASE_URL=<secret-name>:latest `
  --command uv `
  --args run,alembic,upgrade,head

gcloud run jobs execute materials-backend-migrate --region <region> --wait
```

## Deploy backend

Example:

```powershell
gcloud run deploy materials-backend-dev `
  --image <region>-docker.pkg.dev/<project>/<repo>/materials-backend:<tag> `
  --region <region> `
  --allow-unauthenticated `
  --port 8000 `
  --concurrency 10 `
  --memory 1Gi `
  --cpu 1 `
  --set-cloudsql-instances <project>:<region>:<instance> `
  --set-env-vars APP_RUNTIME_TARGET=cloud_run,AUTO_MIGRATE_ON_STARTUP=0,STORAGE_BACKEND=gcs,GCS_BUCKET=<env-bucket>,GCS_OBJECT_PREFIX=<prefix>,INSTANCE_CONNECTION_NAME=<project>:<region>:<instance>,CORS_ALLOWED_ORIGINS=https://<frontend-service-url>,BACKEND_PUBLIC_BASE_URL=https://<backend-service-url>,FRONTEND_PUBLIC_BASE_URL=https://<frontend-service-url>,MAX_UPLOAD_BYTES=33554432,HEAVY_REQUEST_TARGET_SECONDS=60,CLOUD_RUN_CONCURRENCY_TARGET=10,DB_POOL_SIZE=5,DB_MAX_OVERFLOW=10,DB_POOL_TIMEOUT=30,DB_POOL_RECYCLE_SECONDS=1800,WEB_CONCURRENCY=2 `
  --set-secrets DATABASE_URL=<secret-name>:latest
```

## Deploy frontend

Example:

```powershell
gcloud run deploy materials-frontend-dev `
  --image <region>-docker.pkg.dev/<project>/<repo>/materials-frontend:<tag> `
  --region <region> `
  --allow-unauthenticated `
  --port 80
```

## Post-deploy validation

Validate the backend health contract first:

1. `GET /api/health`
2. Confirm:
   - `runtime_target = cloud_run`
   - `migration_strategy = external`
   - `storage.backend = gcs`
   - `storage.bucket` matches the environment bucket
   - `cloud_sql.instance_connection_name_configured = true`
   - `upload_limits.max_upload_bytes = 33554432`

Then validate user-facing flow:

1. Open frontend.
2. Confirm list/read pages work anonymously.
3. Create/select an active user.
4. Validate one mutation path with `X-User-Name`.
5. Validate one artifact-producing path.
6. Validate one durable archive path:
   - Items batch upload
   - manual item import
   - manual order import with missing-item artifact generation

## Operational warnings

- The current mutation identity model is temporary.
- Anonymous backend reachability is still part of the first rollout contract.
- Some compatibility and directory-scan flows still exist and should be treated cautiously in cloud operation until they are fully removed or converted.
- Start with conservative concurrency and increase only after observing Cloud SQL connection behavior.

## Suggested next follow-up after deployment

1. Replace `X-User-Name` with stronger end-user authentication.
2. Remove remaining repo-local staging and compatibility directory-scan paths.
3. Add a repeatable CI/CD deployment pipeline around this runbook.
