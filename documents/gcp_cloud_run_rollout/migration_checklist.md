# GCP Rollout Checklist

## Scope Rule

Backward compatibility is not required for any item in this checklist.

If a legacy compatibility path conflicts with the target GCP model, prefer removal or replacement instead of preserving it.

## Status Legend

- `[Decision]`: the required product/deployment decision is locked, but implementation and/or runtime validation may still remain
- `[x]`: implementation or validation for that checklist item is complete enough for this rollout tracker
- `[ ]`: still unresolved, unimplemented, or unvalidated

## 1. Architecture and Storage

- [Decision] Define the canonical storage boundary: temporary local disk vs persistent GCS object storage
  Current implementation status: durable item/order outputs and default durable moves now route through `backend/app/storage.py`, which now supports both `local://...` and `gcs://...` refs; request-scoped staging remains local.
- [x] Introduce a backend storage abstraction for persistent file operations
  Current implementation status: generated artifacts, item-import archive metadata, default registered item archive moves, and default registered order CSV/PDF moves now go through the storage layer.
- [ ] Remove business-critical dependence on repo-local `imports/` and `exports/`
  Remaining gap: durable storage is now GCS-capable and the Items batch-upload path no longer depends on server-side staging, but some compatibility and directory-scan workflows still assume repo-local paths.
- [x] Replace path-derived artifact identifiers with durable DB/object identifiers where needed
  Current implementation status: browser-facing artifact retrieval uses opaque `artifact_id` values; public API responses no longer depend on workspace-relative paths.
- [Decision] Define naming conventions for GCS buckets and object prefixes
  Current decision: use one GCS bucket per environment and separate object classes by prefix under a shared base prefix, with canonical subprefixes `staging/`, `artifacts/`, `archives/`, and `exports/`.
- [Decision] Define lifecycle/retention policy for staging, generated artifacts, and exports
  Current decision: `staging` retains 7 days, `exports` retains 30 days, `artifacts` retains 90 days, and `archives` have no automatic deletion in the first rollout.

## 2. Backend Runtime

- [x] Make DB pool configuration environment-driven
- [Decision] Define Cloud SQL connection strategy
  Current decision: Cloud Run connects to Cloud SQL through the Cloud SQL Connector / Unix socket path, with credentials sourced from Secret Manager.
- [x] Separate Alembic migration execution from normal autoscaled service startup
- [x] Review health/readiness endpoint expectations for Cloud Run
- [Decision] Review request timeout sensitivity of heavy synchronous endpoints
  Current decision: the first rollout targets typical heavy synchronous paths to complete within 60 seconds; cases that are likely to exceed that become async candidates later rather than expanding the initial contract.
  Current implementation status: runtime now exposes `HEAVY_REQUEST_TARGET_SECONDS` and surfaces it via `/api/health` for deployment validation.
- [Decision] Confirm that no request requires durable local state across instances
  Current decision: no cross-request workflow may depend on instance-local disk; any upload/preview-confirm state that must survive across requests uses GCS-backed staging instead.
  Current implementation status: the Items batch-upload path now processes uploaded CSV bytes directly instead of creating a server-side staging directory first.
  Remaining implementation gap: older compatibility flows still need the same treatment before this can be treated as Cloud Run-complete.

## 3. Frontend Runtime

- [x] Confirm how the frontend resolves the backend base URL in Cloud Run
- [x] Confirm whether nginx remains necessary for the frontend container
  Current decision: keep nginx as the static frontend delivery layer for the first split-service Cloud Run rollout.
- [Decision] Confirm whether CORS is needed between frontend Cloud Run and backend Cloud Run
  Current implementation status: split-service cross-origin traffic is now the documented/default cloud posture, and backend/browser runtime surfaces expect explicit `CORS_ALLOWED_ORIGINS`.
- [Decision] Review upload size expectations against Cloud Run and HTTP proxy limits
  Current decision: treat 32 MB as the operational upload ceiling for CSV and ZIP requests in the first rollout.
  Current implementation status: backend request middleware and frontend nginx now both enforce the 32 MB ceiling.
- [Decision] Review direct-download and export behavior for cloud-hosted access
  Current decision: browser downloads stay backend-mediated through opaque download endpoints; the first rollout does not expose GCS signed URLs directly to the browser.

## 4. Security

- [x] Replace permissive CORS defaults with explicit allowed origins
- [Decision] Define secret sources for DB credentials and other sensitive settings
  Current decision: use Google Secret Manager as the canonical cloud secret source and inject values into Cloud Run at deploy/runtime.
  Current implementation status: README/runtime docs now treat Secret Manager as the expected cloud source; application config surfaces `INSTANCE_CONNECTION_NAME` explicitly for the Cloud SQL deployment contract.
- [Decision] Define the future authentication boundary for mutations
  Current decision: the first Cloud Run rollout keeps `X-User-Name` as a temporary mutation identity mechanism even though the backend remains a browser-reachable public HTTPS endpoint; this is accepted only as a temporary rollout shortcut behind explicit frontend-origin CORS and with stronger auth deferred.
  Current implementation status: `/api/health` and `/api/auth/capabilities` now report this as a temporary model requiring stronger follow-up auth.
- [Decision] Review the current `X-User-Name` model as a temporary mechanism only
  Current implementation status: this remains intentionally temporary; current rollout work hardened CORS/storage-path exposure without replacing mutation identity yet.
- [Decision] Identify admin-only and operator-only operations that will need stronger protection
  Current decision: `/users` administration and future role/setting management are the initial admin-only boundary; normal business mutations/import/export remain operator-capable in the first rollout.
- [x] Ensure file/object references do not expose internal storage layout
  Current implementation status: artifact and item-batch/manual-import responses now avoid exposing raw storage paths to the browser.
- [Decision] Review auditability expectations for imports, exports, and high-impact mutations
  Current decision: audit coverage should record actor, timestamp, action type, primary target identifiers, and outcome/result for imports, exports, undo, and other high-impact mutations, without requiring full file-body or full request/response retention.

## 5. Cost Control

- [Decision] Review the largest CSV and ZIP import paths
  Current decision: first-rollout upload handling is bounded to 32 MB per CSV/ZIP request and remains synchronous within that envelope.
- [Decision] Review planning and export endpoints that can produce large responses
  Current decision: normal JSON planning responses remain synchronous in the first rollout, while file-producing exports/downloads stay on backend download endpoints rather than introducing new async or pagination contracts now.
- [Decision] Estimate Cloud SQL connection usage under Cloud Run concurrency
  Current decision: size the first rollout for a small-team workload (roughly under 10 concurrent active users) and a conservative backend Cloud Run concurrency target of about 10 requests per instance.
  Current implementation status: runtime now exposes `CLOUD_RUN_CONCURRENCY_TARGET` and reports it through `/api/health` alongside DB pool settings.
- [Decision] Define GCS retention and cleanup rules for temporary objects
  Current decision: cleanup is primarily lifecycle-policy driven in GCS, using the retention classes defined above for `staging`, `exports`, and `artifacts`.
- [Decision] Decide whether large import paths should move to asynchronous execution later
  Current decision: keep first-rollout imports synchronous within the 32 MB request ceiling; revisit async only if real workloads need larger uploads or longer-running processing.
- [Decision] Define baseline monitoring and cost-alert dimensions
  Current decision: minimum monitoring covers Cloud Run latency/error rate/instance count/memory, Cloud SQL CPU/connections/storage, and GCS storage growth.

## 6. Data and Migration

- [Decision] Define how existing local import/export/archive data will be treated
  Current decision: new data created after cutover becomes GCS-authoritative; existing local import/export/archive files are not migrated in the first rollout.
- [Decision] Decide what historic files must be preserved in GCS and what can be discarded
  Current decision: no historic local files are copied into GCS during the first rollout; historical lookup remains an old-environment/legacy-reference concern if needed.
- [Decision] Review schema/index needs for production-scale PostgreSQL usage
  Current decision: the first rollout reviews major current read paths and adds only necessary indexes; broad schema/index redesign is out of scope until production evidence justifies it.
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
- [x] Add a concrete Cloud Run deployment runbook
