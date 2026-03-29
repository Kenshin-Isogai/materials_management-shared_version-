# Implementation Slices

## Purpose

This file groups the remaining rollout work into execution slices.

It is intentionally shorter than `implementation_plan.md`; use it when you want a practical order of attack.

## Slice 1: Clean up the frontend/backend production contract

### Goal

Make the split-service Cloud Run communication model unambiguous.

### Main work

- keep nginx `/api` reverse proxy assumptions out of the built image
- keep `VITE_API_BASE` explicitly build-time
- keep absolute backend `/api` usage explicit in docs and code

### Primary files

- `frontend\nginx.conf`
- `frontend\Dockerfile`
- `frontend\src\lib\api.ts`
- `docker-compose.yml`

## Slice 2: Clean up the production migration contract

### Goal

Keep the backend startup model clearly safe for autoscaled Cloud Run.

### Main work

- keep migrations external to request-serving startup
- keep local compose startup from being confused with production startup
- keep Cloud SQL and runtime tuning documented consistently

### Primary files

- `docker-compose.yml`
- `backend\Dockerfile`
- `backend\app\api.py`
- `documents\gcp_cloud_run_rollout\cloud_run_deployment_runbook.md`

## Slice 3: Remove remaining cloud-conflicting local filesystem behavior

### Goal

Finish separating durable cloud behavior from legacy local compatibility behavior.

### Main work

- remove or isolate `legacy_path` fallback
- avoid reviving removed local directory-scan helpers
- keep only temporary request-scoped local disk usage

### Primary files

- `backend\app\service.py`
- `backend\app\order_import_paths.py`
- `backend\app\config.py`

## Slice 4: Lock the documentation set

### Goal

Make the rollout docs useful both before and after GCP project creation.

### Main work

- keep one canonical role per document
- separate "can do now" from "blocked on real GCP resources"
- keep checklist status aligned with actual repository state

### Primary files

- `documents\gcp_cloud_run_rollout\README.md`
- `documents\gcp_cloud_run_rollout\implementation_plan.md`
- `documents\gcp_cloud_run_rollout\migration_checklist.md`
- `documents\gcp_cloud_run_rollout\environment_and_runtime_matrix.md`

## Slice 5: Project-dependent rollout execution

### Goal

Use the cleaned repository and docs to execute the real deployment.

### Main work

- create real GCP resources
- wire Secret Manager and Cloud SQL
- deploy backend and frontend
- validate runtime behavior against Cloud Run, Cloud SQL, and GCS

### Primary files

- `documents\gcp_cloud_run_rollout\cloud_run_deployment_runbook.md`
- `README.md`

## Recommended order

1. Slice 1
2. Slice 2
3. Slice 3
4. Slice 4
5. Slice 5
