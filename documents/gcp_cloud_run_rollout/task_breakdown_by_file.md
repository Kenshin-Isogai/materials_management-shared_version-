# GCP Rollout Task Breakdown by File

## Purpose

This file maps the remaining rollout work to concrete repository surfaces.

Use this file for "what changes where".

Use `implementation_plan.md` for sequencing and `migration_checklist.md` for status.

## 1. High-priority files that can be changed now

| File | Why it matters | Remaining action |
|---|---|---|
| `frontend\nginx.conf` | Defines the built frontend image contract | Keep the cloud-first no-proxy contract in place and avoid reintroducing backend-container assumptions |
| `frontend\Dockerfile` | Bakes `VITE_API_BASE` at build time | Keep the build-time contract explicit and document that production expects an absolute backend URL |
| `frontend\src\lib\api.ts` | Defines the browser API base behavior and mutation header injection | Keep the absolute `/api` contract explicit and keep the temporary `X-User-Name` behavior centralized |
| `docker-compose.yml` | Encodes the local/shared-server stack contract | Keep local convenience startup separate from the Cloud Run migration contract |
| `backend\app\service.py` | Still contains a local-only artifact compatibility fallback | Decide whether to keep or fully remove the remaining local raw-path compatibility behavior |
| `backend\app\order_import_paths.py` | Now holds only the order path helpers still used by active import flows | Keep the module limited to active path rules and avoid reviving unused scan helpers |
| `backend\app\config.py` | Defines runtime posture and path roots | Keep local path variables explicitly local-only in cloud documentation and avoid implying durable cloud use |

## 2. Files that mainly need documentation alignment

| File | Why it matters | Remaining action |
|---|---|---|
| `documents\gcp_cloud_run_rollout\README.md` | Entry point for the whole doc set | Keep reading order and file responsibilities clear |
| `documents\gcp_cloud_run_rollout\implementation_plan.md` | Tracks what can be done now vs later | Keep repository work and project-dependent work separated |
| `documents\gcp_cloud_run_rollout\migration_checklist.md` | Readiness tracker | Keep statuses aligned with actual code and packaging state |
| `documents\gcp_cloud_run_rollout\environment_and_runtime_matrix.md` | Env-var contract | Keep placeholders separate from resource-specific values not yet known |
| `documents\gcp_cloud_run_rollout\cloud_run_deployment_runbook.md` | Deployment instructions | Keep it explicitly framed as post-project work |

## 3. Files that mostly wait on a real GCP project

| File | Why it matters | Project-dependent work |
|---|---|---|
| `documents\gcp_cloud_run_rollout\cloud_run_deployment_runbook.md` | Uses real resource names | Fill in actual service names, URLs, Cloud SQL instance, bucket, and secrets |
| `.env.example` | Example values | Add final real example patterns once resource naming is decided |
| `README.md` | Repository-level deployment guidance | Update with finalized real deployment commands after the first real GCP environment exists |

## 4. Concrete refactor targets

### Frontend delivery contract

- keep backend proxying assumptions out of `frontend\nginx.conf`
- keep `VITE_API_BASE` absolute in production
- ensure docs consistently say the frontend is built per environment

### Backend migration contract

- keep `AUTO_MIGRATE_ON_STARTUP=0` as the Cloud Run norm
- keep Alembic execution in a separate deployment step
- avoid treating compose startup as the production model

### Backend filesystem cleanup

- review `backend\app\service.py` for `legacy_path` fallback
- keep `backend\app\order_import_paths.py` limited to active path-validation helpers only
- keep temporary local disk only for request-scoped work

## 5. Out of scope for this first documentation pass

- implementing stronger production authentication
- choosing final GCP resource names before a project exists
- validating against real Cloud Run, Cloud SQL, and GCS resources
