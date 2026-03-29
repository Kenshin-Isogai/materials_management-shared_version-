# Target Architecture for GCP Operation

## Target Topology

- Frontend: Cloud Run service
- Backend: Cloud Run service
- Database: Cloud SQL for PostgreSQL
- Persistent file/object storage: Google Cloud Storage

## Architecture Intent

The target deployment should treat Cloud Run instances as stateless request processors.

Persistent state belongs in:

- Cloud SQL for relational data
- GCS for application-managed files, generated exports, staging objects, and archival artifacts that must survive container restarts

## Explicit Scope Decision

Backward compatibility is out of scope.

The target architecture does not need to preserve old shared-server folder contracts or compatibility-only filesystem behavior.

## Locked rollout decisions

- Frontend and backend remain separate Cloud Run services.
- The frontend calls the backend through an absolute HTTPS base URL ending in `/api`.
- The first rollout assumes native Cloud Run `*.run.app` public URLs; custom domains may come later.
- The frontend container continues to use nginx for static asset delivery in the first rollout.
- Cloud Run connects to Cloud SQL through the Cloud SQL Connector / Unix socket model.
- Cloud secrets are sourced from Google Secret Manager and injected into Cloud Run.
- The rollout is planned around `dev`, `staging`, and `prod` as distinct environments.
- Persistent file storage uses one GCS bucket per environment, with class-based prefixes under a shared base prefix.
- New post-cutover files become GCS-authoritative; historic local import/export/archive files are not migrated in the first rollout.
- Browser downloads remain backend-mediated through opaque download endpoints rather than direct GCS signed URLs.
- The first rollout is sized for a small-team operating profile and conservative backend concurrency.

## Canonical object prefix model

Use one bucket per environment and reserve a shared deployment prefix, then place object classes under fixed subprefixes:

- `<base-prefix>/staging/`
- `<base-prefix>/artifacts/`
- `<base-prefix>/archives/`
- `<base-prefix>/exports/`

Example:

- `gs://<env-bucket>/<base-prefix>/staging/...`
- `gs://<env-bucket>/<base-prefix>/artifacts/...`
- `gs://<env-bucket>/<base-prefix>/archives/...`
- `gs://<env-bucket>/<base-prefix>/exports/...`

Recommended retention for the first rollout:

- `staging`: 7 days
- `exports`: 30 days
- `artifacts`: 90 days
- `archives`: no automatic deletion

## Proposed Runtime Boundaries

### Frontend Cloud Run service

Responsibilities:

- serve the built SPA
- call the backend over HTTPS
- avoid embedding environment-specific secrets

Notes:

- If the frontend and backend are on different Cloud Run services, explicit CORS policy is required on the backend.
- The first rollout assumes the backend is still a browser-reachable public HTTPS endpoint, not a private internal-only service.
- The first rollout keeps nginx in the frontend container even though the backend is a separate service.
- If a simple static-hosting model becomes preferable later, the frontend should still keep the same API contract.

### Backend Cloud Run service

Responsibilities:

- expose the API
- execute business rules
- write relational state to Cloud SQL
- read/write persistent file objects through a storage abstraction backed by GCS

Non-responsibilities:

- relying on container-local directories as durable storage
- performing compatibility-only migration of old local folder layouts at runtime

### Cloud SQL for PostgreSQL

Responsibilities:

- system-of-record relational storage
- transactional consistency for inventory, orders, reservations, planning, and import job metadata

Operational notes:

- connection count must be managed explicitly
- startup migrations should not run concurrently from many autoscaled instances
- deployment should assume Cloud SQL Connector / Unix socket connectivity rather than direct long-lived public TCP assumptions
- first-rollout planning assumes a conservative backend Cloud Run concurrency target around 10 requests per instance

### Google Cloud Storage

Responsibilities:

- staging objects for browser-uploaded import inputs when persistence beyond a single request is needed
- generated artifact storage
- export file storage if files must be re-downloaded after request completion
- durable archive storage for import history if the product still requires that history

Object classes to define:

- staging objects
- generated artifacts
- durable archives
- temporary exports

Naming/retention decision for the first rollout:

- use one bucket per environment, not one bucket per object class
- separate classes by fixed prefixes under a shared base prefix
- apply lifecycle retention to `staging`, `exports`, and `artifacts`
- leave `archives` without automatic deletion until an explicit archival policy is introduced

## Design Implications for This Repository

### Filesystem-backed flows that must be redesigned

The current repository documents and implements important flows under:

- `imports\staging\...`
- `imports\items\unregistered\`
- `imports\items\registered\<YYYY-MM>\`
- `imports\orders\unregistered\...`
- `imports\orders\registered\...`
- `exports\...`

These flows are not safe as durable state on Cloud Run local disk.

### Generated artifact contract

Generated artifacts should be addressable by application-managed IDs and backed by durable object references, not by browser-visible relative paths.

### Startup contract

The backend should start quickly and deterministically even when multiple instances launch in parallel.

That implies:

- no startup migration that can race across instances
- no runtime folder migration for historical local layouts
- minimal boot-time work before serving requests

### Traffic contract

The backend should assume:

- browser-origin traffic from the frontend service
- direct API health checks
- possibly internal service-to-service calls later

This requires explicit CORS, explicit secret management, and an authentication strategy that is stronger than anonymous or manually managed browser identity.

For the current repository state, the trust boundary is split into "implemented now" and "finish before serious production use":

- reads may remain broadly available according to the current application contract
- browser/API requests use Bearer JWT identity with app-user mapping from OIDC claims
- the frontend still uses manual token entry today; a real Google Identity sign-in flow remains follow-up work
- deployed environments still need JWKS/OIDC-backed verification and live cloud validation before this should be treated as stable production posture

## Initial operational guardrails

- first-rollout upload ceiling: 32 MB per CSV/ZIP request
- heavy synchronous request target: usually complete within 60 seconds
- multi-request upload/preview-confirm flows must persist intermediate state in GCS-backed staging, not instance-local disk
- normal JSON planning responses remain synchronous for now
- file-producing exports and artifacts are delivered through backend download endpoints rather than direct object-store URLs

## Suggested Architecture Decisions to Lock Early

1. Persistent files use GCS, not local disk.
2. Cloud Run local disk is temporary-only.
3. Alembic runs as a controlled deployment step, not as normal service-start behavior.
4. Public API responses never expose internal storage layout.
5. Compatibility-only runtime logic may be removed if it conflicts with the cloud target.
