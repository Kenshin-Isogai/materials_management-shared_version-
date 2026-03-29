# GCP Cloud Run Rollout Documentation Set

## Purpose

This folder is the working document set for running this application on:

- Frontend on Cloud Run
- Backend on Cloud Run
- PostgreSQL on Cloud SQL
- Persistent application-managed files on GCS

The file set is intentionally kept in place, but each file now has one primary role so the folder is easier to use.

## Locked decisions

These decisions are now treated as fixed unless the rollout direction changes:

- frontend and backend remain separate Cloud Run services
- the frontend calls the backend through an absolute HTTPS base URL ending in `/api`
- `VITE_API_BASE` is build-time configuration, not runtime-injected configuration
- Alembic runs as an external deployment step, not as normal Cloud Run service startup
- the first rollout keeps nginx in the frontend container
- persistent application-managed files use GCS
- mutation requests temporarily continue using `X-User-Name`
- cloud-unfriendly local compatibility code may be removed when it conflicts with the target model

## Current repository status

Already present in the repository:

- backend runtime posture supports `APP_RUNTIME_TARGET=cloud_run`
- backend config already supports Cloud SQL Unix-socket style `DATABASE_URL`
- backend durable storage already supports `STORAGE_BACKEND=gcs`
- health/runtime metadata already exposes cloud-oriented settings
- frontend already resolves API traffic from `VITE_API_BASE`

Still needing repository work before a real GCP deployment:

- tighten the rollout docs so each file has one clear responsibility
- stronger end-user authentication is still outside this cleanup track

Still blocked on having an actual GCP project:

- real service URLs
- real `INSTANCE_CONNECTION_NAME`
- real bucket names and prefixes
- Secret Manager wiring
- actual Cloud Run, Cloud SQL, and GCS deployment validation

## Reading order

1. `target_architecture.md`
2. `implementation_plan.md`
3. `task_breakdown_by_file.md`
4. `environment_and_runtime_matrix.md`
5. `migration_checklist.md`
6. `cloud_run_deployment_runbook.md`

Use `security_and_cost_considerations.md` alongside the above when deciding defaults, limits, and rollout guardrails.

## File roles

- `target_architecture.md`: canonical architecture decisions and operating boundaries
- `implementation_plan.md`: current workstreams, especially what can be done before a GCP project exists
- `task_breakdown_by_file.md`: repository files to change and why
- `environment_and_runtime_matrix.md`: variable contract and which values are placeholders until GCP exists
- `implementation_slices.md`: practical execution grouping
- `migration_checklist.md`: status tracker for repository readiness and project-dependent rollout steps
- `cloud_run_deployment_runbook.md`: concrete deployment steps to use once a GCP project exists
- `security_and_cost_considerations.md`: cloud guardrails, risk areas, and operating assumptions

## Scope rule

Backward compatibility is not the priority for this rollout.

If a compatibility-only path conflicts with Cloud Run, Cloud SQL, or GCS operation, prefer replacing or removing it.
