# Cloud Run Deployment and Operations Runbook

## Purpose

This runbook is for the phase after a real GCP project exists.

It covers:

- initial deployment
- normal bug-fix and feature update rollout
- rollback
- recovery-oriented operational guidance

## Preconditions

- frontend/backend split-service contract is unchanged
- `dev`, `staging`, and `prod` environments are treated as separate deployment targets
- backend startup migrations remain disabled in Cloud Run request-serving startup
- the team understands that repository auth now expects Bearer JWTs and that live Identity Platform/JWKS validation still needs cloud-side rollout work
- manual token entry in the current frontend is a local/test fallback, not the intended long-term production login UX

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

## Recovery policy contract to finalize per environment

Before serious Cloud Run production use, each environment must have the following operator-owned controls recorded alongside its real resource names:

- Cloud SQL automated backups enabled
- Cloud SQL point-in-time recovery enabled for `staging` and `prod` at minimum
- one GCS bucket per environment with one shared base prefix split into:
  - `staging/`
  - `exports/`
  - `artifacts/`
  - `archives/`
- GCS lifecycle retention aligned with the target architecture:
  - `staging`: 7 days
  - `exports`: 30 days
  - `artifacts`: 90 days
  - `archives`: no automatic deletion
- GCS object versioning policy decided and documented before production cutover
- recovery owner and approval path documented for DB restore and object-storage restore actions

Repository-side assumption:

- restore actions should recover into a new Cloud SQL instance or a versioned/new object location first, then cut traffic after validation
- do not treat in-place destructive restore as the default first action
- `GET /api/health` should expose this contract to operators as `recovery_policy` even before live GCP resources exist

## Canonical frontend build contract

Build the frontend with:

```text
VITE_API_BASE=https://<backend-service-url>/api
```

## Initial deployment order

1. Create the GCP project and enable required services.
2. Create Artifact Registry.
3. Create Cloud SQL.
4. Create the GCS bucket.
5. Create Secret Manager entries.
6. Build and push backend and frontend images.
7. Run Alembic through a one-off Cloud Run Job or equivalent.
8. Deploy the backend Cloud Run service.
9. Deploy the frontend Cloud Run service.
10. Validate health, browser access, mutations, and durable file flows.

## Example image build/push commands

```powershell
gcloud auth configure-docker <region>-docker.pkg.dev
docker build -t <region>-docker.pkg.dev/<project>/<repo>/materials-backend:<tag> .\backend
docker build -t <region>-docker.pkg.dev/<project>/<repo>/materials-frontend:<tag> --build-arg VITE_API_BASE=https://<backend-service-url>/api .\frontend
docker push <region>-docker.pkg.dev/<project>/<repo>/materials-backend:<tag>
docker push <region>-docker.pkg.dev/<project>/<repo>/materials-frontend:<tag>
```

## Example migration job pattern

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

## Standard change workflow for bug fixes and updates

Use the same path for bug fixes, small features, and dependency updates:

1. Build a versioned backend image and frontend image.
2. Deploy to `dev`.
3. Run smoke validation:
   - `GET /api/health`
   - frontend load
   - one read flow
   - one mutation with an active mapped user and bearer token
   - one artifact or archive flow if the change touches file handling
4. Run the same image pair in `staging`.
5. If schema changes exist, run migration in a controlled step before full production traffic shift.
6. Deploy to `prod` with a new revision.
7. Shift traffic conservatively and observe latency/error metrics.

## Rollback workflow

### Application rollback

Use Cloud Run revision rollback when:

- the application image is bad
- the new revision has elevated error rate or latency
- the problem is not caused by irreversible DB schema/data mutation

Preferred action:

1. stop increasing traffic to the bad revision
2. move traffic back to the last known good revision
3. verify `/healthz`, `/readyz`, and `/api/health`
4. verify one read flow and one mutation flow

### Database rollback / recovery

Do not treat application revision rollback as database rollback.

Use Cloud SQL recovery procedures when:

- a migration damaged schema or data
- operator error caused durable data corruption
- application-level undo is unavailable or insufficient

Preferred action:

1. stop or limit write traffic
2. determine whether the issue is row-level, import-job-level, or full DB recovery-level
3. use the least-destructive recovery path first:
   - item import undo/redo if applicable
   - order import undo/redo if applicable
   - targeted manual correction
   - point-in-time restore / backup restore if needed
4. revalidate application behavior after DB recovery

### Object storage recovery

Use GCS recovery procedures when:

- generated artifacts or archives were deleted unexpectedly
- lifecycle rules were misapplied
- an operator needs to recover a historical export or import artifact

Preferred action:

1. determine whether the missing object lived under `staging/`, `exports/`, `artifacts/`, or `archives/`
2. verify whether recovery should come from object versioning, a copied backup location, or regeneration from DB/application state
3. prefer regenerating temporary outputs (`staging`, many `exports`) over restoring them when regeneration is cheaper and safer
4. prefer restoring durable history (`artifacts`, `archives`) into a separate recovery prefix first
5. validate backend-mediated download flows after recovery

## Recoverability guidance by failure type

### Bad application release

- primary tool: Cloud Run revision rollback
- secondary tool: redeploy prior known-good image

### Bad item import

- primary tool: import-job inspection plus item import undo/redo where applicable
- confirm no later edits conflict before undoing

### Bad order import

- primary tool: import-job inspection plus order import undo/redo where applicable
- undo now checks for post-import modifications to orders, quotations, and aliases before applying changes
- escalate to targeted manual correction or Cloud SQL recovery only when import-level undo is blocked or insufficient

### Infrastructure or data incident

- primary tool: Cloud SQL backup/PITR and GCS recovery policy
- this must be prepared before relying on the platform for production use

## Restore validation checklist

After any DB or object restore:

1. verify `/healthz`, `/readyz`, and `/api/health`
2. verify import-job listing/detail endpoints for the affected workflow
3. verify one read flow and one mutation with an active user
4. verify one artifact download and, if relevant, one archive/history lookup
5. record which revision, DB instance, backup timestamp, and bucket/prefix generation were restored

## Restore drill acceptance criteria

Treat the repo-side PITR preparation as complete only when a future live-cloud drill can answer all of the following with evidence:

1. which backup/PITR timestamp was selected and why
2. which recovery target was used (new Cloud SQL instance, recovery bucket/prefix, or object version)
3. which application revision was paired with the restored data
4. whether `/api/health` matched the intended Cloud SQL socket and recovery contract after cutover
5. whether import-job inspection, artifact download, and one authenticated mutation all succeeded after restore

## Validation after deployment

### Backend validation

- `GET /healthz`
- `GET /readyz`
- `GET /api/health`
- confirm liveness returns quickly without DB dependency
- confirm readiness succeeds only when DB connectivity is healthy
- confirm `runtime_target = cloud_run`
- confirm `migration_strategy = external`
- confirm `storage.backend = gcs`
- confirm Cloud SQL connection metadata is populated as expected

### Browser validation

- open the frontend
- verify read/list pages load
- authenticate with the configured Identity Platform email/password flow or another valid bearer-token path
- execute at least one mutation using `Authorization: Bearer <JWT>`
- execute one artifact-producing flow
- execute one durable archive or import-history flow

## Minimum production monitoring topics

- Cloud Run request latency
- Cloud Run error rate
- Cloud Run instance count and concurrency behavior
- structured request logs with request ID, auth mode, status code, and latency
- Cloud SQL connection count, CPU, and storage growth
- GCS object count / storage growth by prefix
- failures in import, artifact, archive, and export flows

## Important warnings

- repository auth now expects bearer tokens, but production readiness still depends on live Identity Platform/JWKS rollout and cloud validation
- the backend remains browser-reachable in the first rollout unless a stronger edge design is introduced
- increase concurrency only after observing Cloud SQL connection behavior
- no production plan should assume that Cloud Run revision rollback alone solves DB-level mistakes
