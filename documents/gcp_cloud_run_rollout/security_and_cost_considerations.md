# Security and Cost Considerations for the GCP Rollout

## Scope Rule

Backward compatibility is intentionally excluded from these recommendations.

Security and cost controls should be designed for the target GCP deployment, not for preserving older shared-server behavior.

## 1. Security Priorities

### Locked first-rollout decisions

- Cloud Run uses Google Secret Manager as the canonical source for DB credentials and other sensitive settings.
- Frontend and backend remain separate Cloud Run services, so backend CORS must allow only the chosen frontend origin set.
- The backend remains a browser-reachable public HTTPS endpoint in the first rollout, using native Cloud Run `*.run.app` URLs unless custom domains are added later.
- Mutation requests keep the temporary `X-User-Name` model in the first rollout even though the backend stays publicly reachable; that is accepted only as a temporary shortcut until stronger auth lands.
- Stronger end-user authentication remains a follow-up hardening item, not a first-rollout prerequisite.
- Admin-only scope initially covers user administration and future role/setting management; normal business mutations/import/export remain operator-capable.
- Browser downloads remain backend-mediated through opaque download endpoints rather than direct GCS signed URLs.

### Current posture to treat as temporary

- anonymous reads are allowed
- mutation requests rely on `X-User-Name`
- RBAC exists as a planned direction rather than an enforced boundary
- the backend currently supports broad local/shared-server workflows that are not ideal for cloud isolation

### Immediate hardening targets

1. **CORS**
   - Replace permissive or development-oriented defaults with explicit frontend origins.

2. **Secrets**
   - Source database credentials and other sensitive values from managed secret storage.

3. **Mutation identity**
   - Treat `X-User-Name` as a temporary development-era contract, not a production-grade trust boundary.

4. **Operational endpoint review**
   - Review endpoints that expose artifact metadata, import job details, health diagnostics, or administrative capabilities.

5. **Storage exposure**
   - Do not expose internal bucket names, object prefixes, local paths, or migration-era storage details in browser-facing responses.

### Recommended target direction

- frontend-to-backend HTTPS only
- explicit allowed origins
- stronger user identity model for mutations after the first rollout boundary
- documented admin/operator/viewer boundary before production launch
- explicit audit expectations for imports, exports, and high-impact state changes

## 2. Cost Risk Review

### Cloud SQL risk areas

- Cloud Run autoscaling can multiply DB connections quickly.
- Heavy planning endpoints can create expensive repeated reads under load.
- Poorly bounded concurrency can push Cloud SQL instance sizing upward.

Recommended controls:

- environment-driven pool sizing
- concurrency review before production rollout
- query/index review for planning and reporting paths

### Cloud Run risk areas

- large synchronous CSV or ZIP processing can increase CPU and memory consumption
- oversized responses from planning/export endpoints can increase request duration and egress
- startup work that is too heavy can increase cold-start cost and latency

Recommended controls:

- keep startup lean
- bound upload sizes intentionally
- identify candidates for later async processing

Locked first-rollout operating limit:

- treat 32 MB as the operational request-size ceiling for CSV and ZIP uploads
- keep those flows synchronous within that ceiling
- target heavy synchronous requests to finish in about 60 seconds or less during normal operation
- revisit async execution only if observed workloads exceed that limit or request duration becomes unacceptable

### GCS risk areas

- staging objects can accumulate if failed jobs are not cleaned up
- generated artifacts can grow without retention policy
- re-downloadable exports can create silent storage growth

Recommended controls:

- object lifecycle rules
- retention classes by object purpose
- explicit cleanup ownership in the application or bucket policy

Locked first-rollout retention policy:

- `staging`: 7 days
- `exports`: 30 days
- `artifacts`: 90 days
- `archives`: no automatic deletion

## 3. Repository-Specific High-Risk Areas

### File-heavy workflows

The current application has documented and implemented flows for:

- staging import uploads
- archiving registered item CSVs
- generating missing-item registration CSVs
- exporting planning and procurement files

These are good candidates for cost and durability problems if moved to cloud infrastructure without redesign.

### Planning and analysis paths

The project planning and BOM analysis features can create heavier database and response loads than simple CRUD paths.

They should be reviewed for:

- result size
- repeated data access
- Cloud SQL index support
- request latency under concurrent access

First-rollout response contract:

- normal JSON planning responses stay synchronous
- file-producing exports remain download-oriented backend endpoints
- no new async-job or pagination contract is required unless production evidence shows the initial model is insufficient

### Migration/startup behavior

Automatic migration at service startup is convenient locally but risky for autoscaled production services.

It should be treated as a rollout concern, not a request-serving concern.

## 4. Decisions to Carry Into Implementation

- no new cloud design should depend on local durable disk
- no long-term production trust model should rely only on `X-User-Name`
- no public contract should expose storage layout
- no rollout plan should assume compatibility preservation is required
- first rollout secrets come from Google Secret Manager
- first rollout persistent GCS objects use one bucket per environment with prefix-based class separation
- first rollout audit coverage records actor, timestamp, action type, primary target identifiers, and result/outcome for imports, exports, undo, and high-impact mutations

## 5. Minimum Monitoring Topics for Production Planning

- Cloud SQL connection count
- Cloud SQL CPU and storage growth
- Cloud Run request latency and memory usage
- Cloud Run instance count and concurrency behavior
- GCS object count and storage growth by prefix
- API paths with the largest payloads and longest durations

First-rollout planning assumption:

- small-team workload, roughly under 10 concurrent active users
- conservative backend Cloud Run concurrency target around 10 requests per instance
