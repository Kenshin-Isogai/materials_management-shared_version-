# GCP Rollout Checklist

## Scope Rule

Backward compatibility is not required for any item in this checklist.

If a legacy compatibility path conflicts with the target GCP model, prefer removal or replacement instead of preserving it.

## 1. Architecture and Storage

- [x] Define the canonical storage boundary: temporary local disk vs persistent GCS object storage
  Current implementation status: durable item/order outputs and default durable moves now route through `backend/app/storage.py`; request-scoped staging remains local.
- [x] Introduce a backend storage abstraction for persistent file operations
  Current implementation status: generated artifacts, item-import archive metadata, default registered item archive moves, and default registered order CSV/PDF moves now go through the storage layer.
- [ ] Remove business-critical dependence on repo-local `imports/` and `exports/`
  Remaining gap: the storage implementation is still local-backed, so Cloud Run durability still requires a GCS-backed storage implementation behind the new boundary.
- [x] Replace path-derived artifact identifiers with durable DB/object identifiers where needed
  Current implementation status: browser-facing artifact retrieval uses opaque `artifact_id` values; public API responses no longer depend on workspace-relative paths.
- [ ] Define naming conventions for GCS buckets and object prefixes
- [ ] Define lifecycle/retention policy for staging, generated artifacts, and exports

## 2. Backend Runtime

- [x] Make DB pool configuration environment-driven
- [ ] Define Cloud SQL connection strategy
- [x] Separate Alembic migration execution from normal autoscaled service startup
- [x] Review health/readiness endpoint expectations for Cloud Run
- [ ] Review request timeout sensitivity of heavy synchronous endpoints
- [ ] Confirm that no request requires durable local state across instances
  Remaining gap: repo-local staging/archive implementations still need a GCS-backed storage provider before this can be treated as Cloud Run-complete.

## 3. Frontend Runtime

- [x] Confirm how the frontend resolves the backend base URL in Cloud Run
- [ ] Confirm whether nginx remains necessary for the frontend container
- [x] Confirm whether CORS is needed between frontend Cloud Run and backend Cloud Run
- [ ] Review upload size expectations against Cloud Run and HTTP proxy limits
- [ ] Review direct-download and export behavior for cloud-hosted access
  Current status: frontend API-base handling and download contracts are cleaned up; final validation still depends on the real Cloud Run + GCS deployment topology.

## 4. Security

- [x] Replace permissive CORS defaults with explicit allowed origins
- [ ] Define secret sources for DB credentials and other sensitive settings
- [ ] Define the future authentication boundary for mutations
- [x] Review the current `X-User-Name` model as a temporary mechanism only
  Current implementation status: this remains intentionally temporary; current rollout work hardened CORS/storage-path exposure without replacing mutation identity yet.
- [ ] Identify admin-only and operator-only operations that will need stronger protection
- [x] Ensure file/object references do not expose internal storage layout
  Current implementation status: artifact and item-batch/manual-import responses now avoid exposing raw storage paths to the browser.
- [ ] Review auditability expectations for imports, exports, and high-impact mutations

## 5. Cost Control

- [ ] Review the largest CSV and ZIP import paths
- [ ] Review planning and export endpoints that can produce large responses
- [ ] Estimate Cloud SQL connection usage under Cloud Run concurrency
- [ ] Define GCS retention and cleanup rules for temporary objects
- [ ] Decide whether large import paths should move to asynchronous execution later
- [ ] Define baseline monitoring and cost-alert dimensions

## 6. Data and Migration

- [ ] Define how existing local import/export/archive data will be treated
- [ ] Decide what historic files must be preserved in GCS and what can be discarded
- [ ] Review schema/index needs for production-scale PostgreSQL usage
- [x] Confirm that rollout documentation no longer assumes local/shared-server compatibility

## 7. Validation

- [x] Validate backend tests for touched behavior
  Current implementation status: targeted backend runtime/storage tests have been run for the touched paths.
- [x] Validate frontend build/runtime assumptions for the new deployment model
  Current implementation status: frontend production build has been rerun after each contract change; final Cloud Run runtime validation is still pending.
- [x] Validate import, export, planning, and artifact retrieval paths after storage refactoring
  Current implementation status: targeted API/service validation has been run for generated artifacts and item batch/archive flows; full Cloud Run + GCS validation remains pending.
- [x] Validate health endpoint behavior and startup flow
- [ ] Validate mutation requests with the expected identity model

## 8. Documentation

- [x] Keep this folder aligned with implementation decisions
- [x] Update root `README.md` when the deployment contract changes
- [x] Update `documents\technical_documentation.md` when architecture or maintenance guidance changes
- [x] Update `documents\source_current_state.md` when runtime behavior changes
- [x] Update `documents\change_log.md` with meaningful migration-related progress
