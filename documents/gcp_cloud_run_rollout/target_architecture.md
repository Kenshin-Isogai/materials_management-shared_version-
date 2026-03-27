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

## Proposed Runtime Boundaries

### Frontend Cloud Run service

Responsibilities:

- serve the built SPA
- call the backend over HTTPS
- avoid embedding environment-specific secrets

Notes:

- If the frontend and backend are on different Cloud Run services, explicit CORS policy is required on the backend.
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

This requires explicit CORS, explicit secret management, and an authentication strategy that is stronger than the current mutation header model.

## Suggested Architecture Decisions to Lock Early

1. Persistent files use GCS, not local disk.
2. Cloud Run local disk is temporary-only.
3. Alembic runs as a controlled deployment step, not as normal service-start behavior.
4. Public API responses never expose internal storage layout.
5. Compatibility-only runtime logic may be removed if it conflicts with the cloud target.
