# GCP Rollout Implementation Plan

## Objective

Prepare this repository for deployment and operation on GCP using:

- Cloud Run for the frontend
- Cloud Run for the backend
- Cloud SQL for PostgreSQL
- Google Cloud Storage for application-managed files and generated artifacts

## Explicit Scope Decision

Backward compatibility is not required.

Implementation may simplify or remove legacy compatibility behavior when that behavior is not aligned with the target GCP architecture.

Examples of acceptable simplification:

- removing compatibility folder-migration logic
- removing filesystem-path-based public contracts
- removing local/shared-server assumptions from cloud-targeted execution paths
- replacing legacy transitional storage conventions with canonical object-storage conventions

## Guiding Principles

1. Prefer the target operating model over migration shims.
2. Make Cloud Run services stateless.
3. Move persistent file semantics to GCS.
4. Keep business rules in the existing service layer first, then adapt API and UI.
5. Make runtime configuration explicit and secret-driven.
6. Build cost-control and observability into the implementation instead of treating them as follow-up work.

## Current Repository Constraints

- The backend currently uses filesystem-backed import, staging, archival, and generated-artifact flows.
- `APP_DATA_ROOT`, `IMPORTS_ROOT`, and `EXPORTS_ROOT` still shape important behavior.
- Startup migration currently depends on `AUTO_MIGRATE_ON_STARTUP`.
- Mutation authorization currently depends on `X-User-Name`.
- The frontend currently assumes reverse-proxy-style `/api` access and is served through nginx in Docker Compose.

## Delivery Phases

For a faster execution framing that still completes the full target update, see `implementation_slices.md`.

### Phase 1: Finalize the target cloud operating contract

Goals:

- define canonical storage behavior for files and artifacts
- define service-to-service and user-to-service trust boundaries
- define runtime configuration and secrets contract

Outputs:

- canonical storage object model
- environment variable inventory
- migration ownership decision for Alembic execution
- frontend/backend deployment contract

Current locked decisions:

- split frontend/backend Cloud Run services with an absolute backend `/api` base URL
- initial public URLs use native Cloud Run `*.run.app`
- Cloud SQL Connector / Unix socket connectivity
- Google Secret Manager as the cloud secret source
- `dev` / `staging` / `prod` environment separation
- one GCS bucket per environment with prefix-based storage classes
- first-rollout retention of 7-day staging, 30-day exports, 90-day artifacts, and no auto-delete archives
- temporary continued use of `X-User-Name` even though the backend remains browser-reachable
- backend-mediated download endpoints instead of direct signed-object browser URLs
- small-team / conservative-concurrency operating assumptions
- 32 MB upload ceiling and about 60-second target for heavy synchronous requests
- no migration of historic local import/export/archive files in the first rollout

### Phase 2: Remove persistent local filesystem assumptions

Goals:

- introduce a storage abstraction for persistent files
- keep only temporary local disk usage where Cloud Run temporary storage is acceptable
- stop treating repo-local paths as durable identifiers

Primary refactor targets:

- item import staging and registration
- order import and generated artifact storage
- export generation and retrieval
- artifact metadata persistence

### Phase 3: Make backend deployment Cloud Run-safe

Goals:

- make startup deterministic across multiple instances
- externalize pool sizing and runtime tuning
- isolate migrations from normal request-serving startup

Primary refactor targets:

- DB engine and connection pooling
- startup sequence
- health and readiness checks
- request timeout awareness for heavy endpoints

### Phase 4: Harden security boundaries

Goals:

- replace implicit trust assumptions with explicit deployment boundaries
- constrain browser origins and sensitive configuration
- prepare the backend for stronger auth without blocking current development

Primary refactor targets:

- CORS configuration
- secret sourcing
- mutation identity model
- admin-only operational paths

### Phase 5: Reduce cost volatility

Goals:

- identify high-cost execution paths
- introduce limits, retention rules, and operational guardrails
- prepare large or long-running work for asynchronous execution if needed

Primary refactor targets:

- bulk CSV and ZIP processing
- planning/export endpoints with large response bodies
- Cloud SQL connection behavior
- object storage lifecycle and retention

### Phase 6: Deployment packaging and rollout validation

Goals:

- define build/deploy mechanics for frontend and backend
- validate runtime behavior in a cloud-like environment
- document rollout order and rollback expectations

Outputs:

- Cloud Run deployment manifest inputs
- migration execution runbook
- smoke-test list
- production-readiness checklist sign-off

## Recommended Work Order

1. Storage abstraction
2. Generated artifact contract cleanup
3. Database startup and migration strategy
4. Runtime configuration and secret contract
5. CORS and authentication boundary cleanup
6. Cost controls and retention rules
7. Cloud Run deployment packaging and validation

## Concrete Repository Areas To Touch

- `backend\app\service.py`
- `backend\app\api.py`
- `backend\app\db.py`
- `backend\app\config.py`
- `backend\alembic\versions\`
- `frontend\src\lib\api.ts`
- `frontend\Dockerfile`
- `frontend\nginx.conf`
- `docker-compose.yml`
- `README.md`

See also:

- `task_breakdown_by_file.md`
- `environment_and_runtime_matrix.md`
- `implementation_slices.md`

## Definition of Done for the Rollout Preparation Track

The repository is ready for GCP implementation when:

- no persistent business-critical workflow depends on Cloud Run local disk
- runtime configuration is explicit and cloud-oriented
- startup migrations are not coupled to autoscaled request-serving instances
- security defaults are explicit and restrictive
- heavy paths have cost-risk notes and mitigation
- deployment and validation steps are documented for the target GCP architecture
