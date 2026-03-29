# GCP Production Readiness Checklist

## Status legend

- `[x]` complete in the repository or operating model
- `[~]` partially complete or still dependent on operational follow-through
- `[ ]` not yet complete
- `[Blocked]` cannot complete without a real GCP project or cloud resources

## 1. Architecture and runtime contract

- [x] Backend runtime supports a distinct `cloud_run` posture
- [x] Frontend/backend split-service topology is fixed
- [x] Frontend uses an absolute backend HTTPS `/api` base
- [x] Production migration strategy is externalized from normal startup
- [x] Cloud SQL Unix-socket style connectivity is supported
- [x] Durable object storage supports GCS-backed refs
- [x] Browser-facing artifact access avoids exposing storage layout

## 2. Production security boundary

- [x] The temporary `X-User-Name` mutation model is explicitly documented as temporary
- [x] Secret Manager is the intended source of cloud secrets
- [~] Stronger production authentication is partially implemented (`/api/users*` can now be admin-gated when RBAC is enabled, but the rollout still relies on temporary header-based identity)
- [~] Production access policy for health/admin/diagnostic endpoints is partially finalized (`/healthz`, `/readyz`, `/api/health`, and `/api/auth/capabilities` remain anonymous; `/api/users*` is admin-only once RBAC is enforced)

## 3. Change management and rollback

- [x] The deployment model can separate image rollout from DB migration
- [~] Revision-based rollback procedure is documented
- [ ] Revision rollback has been rehearsed in a real cloud environment
- [x] Schema-change rollback decision rules are documented for operators

## 4. Backup and recoverability

- [~] Cloud SQL automated backup / PITR policy is documented in the repo, but still needs real per-environment enablement
- [~] GCS lifecycle/versioning policy is documented in the repo, but still needs real per-environment enablement
- [~] Restore procedure exists for DB-centric incidents in the runbook, but has not been rehearsed against real cloud resources
- [~] Restore procedure exists for object-storage incidents in the runbook, but has not been rehearsed against real cloud resources
- [x] Import job metadata exists for operator inspection
- [x] Safe undo/redo exists for item import jobs
- [x] Equivalent recovery strategy is defined for order import mistakes

## 5. Observability and operations

- [ ] Cloud Monitoring / alerting baseline is defined
- [~] Request latency and error-rate telemetry is emitted via structured request logs, but Cloud Monitoring / alert policies still need to be provisioned
- [ ] Cloud SQL connection pressure is monitored
- [ ] GCS growth and failed file-flow monitoring is in place
- [ ] Deployment / migration / incident ownership is defined

## 6. Live cloud validation

- [Blocked] real Cloud Run frontend URL
- [Blocked] real Cloud Run backend URL
- [Blocked] real `INSTANCE_CONNECTION_NAME`
- [Blocked] real `GCS_BUCKET` and object prefix
- [Blocked] Secret Manager wiring
- [Blocked] live validation against Cloud Run, Cloud SQL, and GCS

## 7. Release bar for first serious production use

Do not treat the rollout as operationally ready until all items below are complete:

- stronger auth is either implemented or explicitly risk-accepted with owner and expiry
- live cloud validation is complete
- backup/restore path is documented and enabled
- rollback path is rehearsed
- monitoring baseline is active
