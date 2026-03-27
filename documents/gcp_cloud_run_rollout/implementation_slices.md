# Implementation Slices

## Purpose

This document defines a practical delivery plan that is not overly cautious, but still ends with the full required target state completed.

The required target state is:

- frontend on Cloud Run
- backend on Cloud Run
- PostgreSQL on Cloud SQL
- persistent application-managed files on GCS

Backward compatibility is explicitly out of scope.

The plan assumes one coordinated update stream, but breaks the work into implementation slices so engineering can keep momentum and still finish the whole transition cleanly.

## Completion Rule

This plan is only considered complete when all of the following are true:

1. No business-critical persistent workflow depends on local container disk.
2. Backend startup is Cloud Run-safe and does not rely on concurrent startup migrations.
3. Frontend and backend deployment contracts are explicit for Cloud Run.
4. Cloud SQL connection behavior is explicitly configured.
5. Security-sensitive runtime defaults are explicit and restrictive.
6. The rollout documentation reflects the final cloud-first architecture.

## Delivery Style

- Move fast in one branch if desired.
- Keep slices broad enough to avoid unnecessary delay.
- Do not stop after partial infrastructure prep.
- Each slice must leave the repository closer to the final architecture, not to another temporary compatibility layer.

## Slice 1: Lock the target runtime contract

### Goal

Freeze the cloud-first technical contract so implementation does not drift.

### Must complete in this slice

- finalize the frontend-to-backend communication model
- finalize the persistent storage model for files and artifacts
- finalize the migration execution model
- finalize the runtime configuration contract

### Expected outputs

- one canonical API base strategy for Cloud Run
- one canonical durable storage strategy for artifacts, archives, and staging
- one canonical migration execution strategy
- final variable inventory for backend and frontend

### Repository surfaces

- `documents\gcp_cloud_run_rollout\target_architecture.md`
- `documents\gcp_cloud_run_rollout\environment_and_runtime_matrix.md`
- `documents\gcp_cloud_run_rollout\task_breakdown_by_file.md`

### Exit criteria

- there is no unresolved ambiguity about where persistent files live
- there is no unresolved ambiguity about how Cloud Run services talk to each other
- there is no unresolved ambiguity about how migrations run in production

## Slice 2: Replace durable local filesystem behavior

### Goal

Make the backend architecture compatible with Cloud Run and GCS.

### Must complete in this slice

- introduce the persistent storage abstraction
- move generated artifacts to durable object-backed storage behavior
- move import/export durable file semantics away from local-only directory assumptions
- remove compatibility-only folder migration behavior that is not required for the target cloud architecture

### Repository surfaces

- `backend\app\service.py`
- `backend\app\config.py`
- `backend\app\api.py`
- `backend\app\db.py`

### Mandatory outcomes

- local disk may still be used for temporary request-scoped work only
- durable artifact retrieval no longer depends on repository-style path semantics
- runtime startup does not need to reconstruct historical local folder layouts

### Exit criteria

- the backend can run on Cloud Run without treating local disk as durable application state

## Slice 3: Make backend startup and database behavior production-safe

### Goal

Complete the Cloud Run + Cloud SQL readiness work for the backend runtime.

### Must complete in this slice

- decouple migrations from ordinary app startup
- externalize DB pool settings
- align worker/concurrency assumptions with Cloud SQL usage
- keep health checks suitable for Cloud Run deployment validation

### Repository surfaces

- `backend\app\db.py`
- `backend\app\config.py`
- `backend\app\api.py`
- `backend\main.py`
- `backend\Dockerfile`

### Mandatory outcomes

- production startup does not race on Alembic
- connection behavior is configurable rather than hard-coded
- backend container startup contract is explicit for Cloud Run

### Exit criteria

- backend deployment behavior is consistent with Cloud Run autoscaling and Cloud SQL limits

## Slice 4: Finish frontend deployment alignment

### Goal

Complete the frontend runtime contract for Cloud Run.

### Must complete in this slice

- lock the Cloud Run API base contract
- align CORS with the chosen frontend/backend topology
- review upload and download behavior against cloud hosting constraints
- confirm whether nginx remains part of the final frontend runtime

### Repository surfaces

- `frontend\src\lib\api.ts`
- `frontend\Dockerfile`
- `frontend\nginx.conf`
- `docker-compose.yml`

### Mandatory outcomes

- frontend runtime does not depend on local Docker networking assumptions
- browser communication with the backend is explicit and production-ready

### Exit criteria

- frontend deployment assumptions are fully aligned with the target Cloud Run topology

## Slice 5: Finish security and cost controls

### Goal

Complete the minimum acceptable security and cost guardrails for cloud operation.

### Must complete in this slice

- replace permissive CORS defaults
- keep secret sourcing explicit
- document the temporary nature of `X-User-Name`
- identify heavy paths and define operating limits or next-step thresholds
- define retention expectations for staged files, artifacts, and exports

### Repository surfaces

- `backend\app\config.py`
- `backend\app\api.py`
- `frontend\src\lib\api.ts`
- `documents\gcp_cloud_run_rollout\security_and_cost_considerations.md`

### Mandatory outcomes

- cloud deployment does not rely on permissive defaults
- cost-risk areas are documented with concrete operating expectations

### Exit criteria

- the system has a cloud-ready baseline security and cost posture for first production rollout

## Slice 6: Final validation and documentation lock

### Goal

End the update plan with all required rollout work completed and documented.

### Must complete in this slice

- validate changed backend behavior
- validate frontend deployment assumptions
- validate import, export, planning, and artifact retrieval behavior
- update all relevant repository documentation

### Repository surfaces

- `README.md`
- `documents\technical_documentation.md`
- `documents\source_current_state.md`
- `documents\change_log.md`
- `documents\gcp_cloud_run_rollout\*`

### Mandatory outcomes

- docs describe the final cloud-first behavior, not transitional assumptions
- the plan ends in a complete target state, not a half-finished migration track

### Exit criteria

- all required target architecture items are complete
- documentation and validation results are aligned with the final implementation

## Recommended pace

If speed matters, use the following practical grouping:

1. Slices 1 and 2 together
2. Slice 3
3. Slices 4 and 5 together
4. Slice 6

This keeps the number of handoffs low without pretending the whole change is a single safe atomic edit.

## What this plan intentionally avoids

- indefinite “phase 0” preparation
- preserving compatibility-only behavior
- ending with infrastructure-ready but application-incomplete work
- splitting the work so finely that the real rollout never finishes
