# GCP Rollout Checklist

## Status legend

- `[x]` complete in the repository
- `[~]` partially complete or decided, but still needing repository cleanup
- `[ ]` not yet complete
- `[Blocked]` waits on having a real GCP project or real cloud resources

## 1. Architecture and storage

- [x] Backend runtime supports a distinct `cloud_run` posture
- [x] Durable storage supports GCS-backed object references
- [x] No business-critical durable workflow depends on repo-local paths
- [x] Browser-facing artifact access uses opaque IDs instead of exposing storage layout
- [x] Canonical bucket/prefix model is documented
- [x] Retention policy expectations are documented

## 2. Frontend and backend contract

- [x] Split frontend/backend Cloud Run topology is decided
- [x] The frontend API contract is an absolute backend HTTPS URL ending in `/api`
- [x] `VITE_API_BASE` is treated as build-time configuration
- [x] Frontend production delivery no longer assumes Docker-local backend proxying
- [x] Production migration strategy is clearly externalized

## 3. Backend runtime

- [x] Cloud SQL Unix-socket style connectivity is documented and supported
- [x] DB pool tuning is environment-driven
- [x] Upload and heavy-request operating limits are environment-driven
- [x] CORS is explicit for cloud deployment posture
- [x] Startup is fully aligned with Cloud Run-safe behavior at the packaging/runtime-contract level

## 4. Security and trust boundary

- [x] The temporary `X-User-Name` mutation model is explicitly documented as temporary
- [x] Secret Manager is the documented cloud secret source
- [x] Browser-facing responses avoid exposing storage layout
- [ ] Stronger production authentication is implemented

## 5. Remaining code cleanup

- [x] Remove remaining legacy local path fallback from generated artifact retrieval
- [x] Remove or isolate local directory-scan compatibility helpers from the cloud target path
- [x] Confirm no production-critical workflow depends on durable local workspace reconstruction

## 6. Documentation set

- [x] `target_architecture.md` states the target operating model
- [x] `environment_and_runtime_matrix.md` defines the config contract
- [x] `cloud_run_deployment_runbook.md` defines the post-project deployment path
- [x] This folder now separates architecture, plan, checklist, and runbook responsibilities

## 7. Blocked until a GCP project exists

- [Blocked] real Cloud Run frontend URL
- [Blocked] real Cloud Run backend URL
- [Blocked] real `INSTANCE_CONNECTION_NAME`
- [Blocked] real `GCS_BUCKET` and object prefix
- [Blocked] Secret Manager wiring
- [Blocked] Cloud Run deployment commands with real values
- [Blocked] live validation against Cloud Run, Cloud SQL, and GCS
