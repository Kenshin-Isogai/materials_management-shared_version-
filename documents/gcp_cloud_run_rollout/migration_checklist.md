# GCP Rollout Checklist

## Scope Rule

Backward compatibility is not required for any item in this checklist.

If a legacy compatibility path conflicts with the target GCP model, prefer removal or replacement instead of preserving it.

## 1. Architecture and Storage

- [ ] Define the canonical storage boundary: temporary local disk vs persistent GCS object storage
- [ ] Introduce a backend storage abstraction for persistent file operations
- [ ] Remove business-critical dependence on repo-local `imports/` and `exports/`
- [ ] Replace path-derived artifact identifiers with durable DB/object identifiers where needed
- [ ] Define naming conventions for GCS buckets and object prefixes
- [ ] Define lifecycle/retention policy for staging, generated artifacts, and exports

## 2. Backend Runtime

- [ ] Make DB pool configuration environment-driven
- [ ] Define Cloud SQL connection strategy
- [ ] Separate Alembic migration execution from normal autoscaled service startup
- [ ] Review health/readiness endpoint expectations for Cloud Run
- [ ] Review request timeout sensitivity of heavy synchronous endpoints
- [ ] Confirm that no request requires durable local state across instances

## 3. Frontend Runtime

- [ ] Confirm how the frontend resolves the backend base URL in Cloud Run
- [ ] Confirm whether nginx remains necessary for the frontend container
- [ ] Confirm whether CORS is needed between frontend Cloud Run and backend Cloud Run
- [ ] Review upload size expectations against Cloud Run and HTTP proxy limits
- [ ] Review direct-download and export behavior for cloud-hosted access

## 4. Security

- [ ] Replace permissive CORS defaults with explicit allowed origins
- [ ] Define secret sources for DB credentials and other sensitive settings
- [ ] Define the future authentication boundary for mutations
- [ ] Review the current `X-User-Name` model as a temporary mechanism only
- [ ] Identify admin-only and operator-only operations that will need stronger protection
- [ ] Ensure file/object references do not expose internal storage layout
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
- [ ] Confirm that rollout documentation no longer assumes local/shared-server compatibility

## 7. Validation

- [ ] Validate backend tests for touched behavior
- [ ] Validate frontend build/runtime assumptions for the new deployment model
- [ ] Validate import, export, planning, and artifact retrieval paths after storage refactoring
- [ ] Validate health endpoint behavior and startup flow
- [ ] Validate mutation requests with the expected identity model

## 8. Documentation

- [ ] Keep this folder aligned with implementation decisions
- [ ] Update root `README.md` when the deployment contract changes
- [ ] Update `documents\technical_documentation.md` when architecture or maintenance guidance changes
- [ ] Update `documents\source_current_state.md` when runtime behavior changes
- [ ] Update `documents\change_log.md` with meaningful migration-related progress
