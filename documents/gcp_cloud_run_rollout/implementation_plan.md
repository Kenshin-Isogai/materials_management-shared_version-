# GCP Rollout Implementation Plan

## Objective

Prepare this repository for deployment on GCP using:

- Cloud Run for the frontend
- Cloud Run for the backend
- Cloud SQL for PostgreSQL
- GCS for persistent application-managed files and generated artifacts

This plan is intentionally split into:

- work that can be completed now without a GCP project
- work that is blocked until a real GCP project and resources exist

## Confirmed rollout decisions

- frontend and backend are separate Cloud Run services
- frontend uses an absolute backend HTTPS URL ending in `/api`
- `VITE_API_BASE` stays build-time
- frontend keeps nginx for the first rollout
- backend migrations run outside normal Cloud Run service startup
- persistent files use GCS, not durable local disk
- temporary mutation identity remains `X-User-Name` for the first rollout
- local compatibility behavior may be removed where it conflicts with the target cloud model

See `target_architecture.md` for the canonical architecture statement.

## What is already in place

- backend runtime has a `cloud_run` posture
- backend storage abstraction already supports `local` and `gcs`
- backend config already surfaces Cloud SQL, CORS, upload, and concurrency settings
- frontend already resolves API traffic from `VITE_API_BASE`
- a first-pass Cloud Run runbook and environment matrix already exist

## Remaining repository work before a GCP project exists

### Workstream 1: Finalize the frontend-to-backend contract

Goals:

- remove Docker-network assumptions from the frontend runtime
- make the absolute backend URL contract unambiguous
- keep nginx only for static asset delivery, not backend proxying

Primary files:

- `frontend\nginx.conf`
- `frontend\Dockerfile`
- `frontend\src\lib\api.ts`
- `docker-compose.yml`

Expected outcome:

- frontend production behavior no longer depends on `backend:8000`

### Workstream 2: Finalize the production migration contract

Goals:

- keep Cloud Run service startup clearly separate from Alembic execution
- make the repository docs and packaging reflect that strategy consistently

Primary files:

- `docker-compose.yml`
- `backend\Dockerfile`
- `backend\app\api.py`
- `documents\gcp_cloud_run_rollout\cloud_run_deployment_runbook.md`

Expected outcome:

- no confusion between local convenience startup and the production migration path

### Workstream 3: Remove remaining durable local filesystem assumptions

Goals:

- remove legacy path fallback where it is no longer needed
- isolate local-only directory scans from the cloud-target path
- keep only request-scoped temporary local disk usage

Primary files:

- `backend\app\service.py`
- `backend\app\order_import_paths.py`
- `backend\app\config.py`

Expected outcome:

- the repository no longer suggests that durable Cloud Run behavior depends on repo-local paths

### Workstream 4: Normalize the rollout documentation set

Goals:

- reduce duplication across the rollout docs
- keep one canonical file per topic
- make the docs usable before any real GCP resources exist

Primary files:

- `documents\gcp_cloud_run_rollout\README.md`
- `documents\gcp_cloud_run_rollout\migration_checklist.md`
- `documents\gcp_cloud_run_rollout\task_breakdown_by_file.md`
- `documents\gcp_cloud_run_rollout\environment_and_runtime_matrix.md`
- `documents\gcp_cloud_run_rollout\implementation_slices.md`

Expected outcome:

- the folder becomes a maintained working set instead of a pile of overlapping drafts

## Work blocked until a GCP project exists

### Resource-specific configuration

- choose actual Cloud Run service names
- create the Cloud SQL instance and obtain `INSTANCE_CONNECTION_NAME`
- choose bucket names and object prefixes
- define the actual frontend and backend public URLs

### Secret and deployment wiring

- configure Secret Manager
- deploy the backend image with Cloud SQL attachment
- deploy the frontend image with the real `VITE_API_BASE`
- run Alembic through a real Cloud Run Job or equivalent deployment step

### Runtime validation

- validate `/api/health` on a deployed backend
- validate browser CORS behavior between the real frontend and backend services
- validate artifact and archive flows against GCS
- validate mutation flows with a real active user and `X-User-Name`

## Recommended execution order

1. frontend/backend contract cleanup
2. migration contract cleanup
3. remaining local filesystem cleanup
4. documentation consolidation
5. GCP resource creation
6. deployment wiring
7. runtime validation

## Definition of ready before creating a GCP project

The repository is ready for project creation and deployment wiring when:

- frontend production behavior no longer assumes Docker-local backend proxying
- production migration strategy is clearly externalized
- remaining cloud-conflicting local compatibility paths are isolated or removed
- rollout docs clearly separate repository work from project-dependent work
