# GCP Cloud Run Rollout Documentation Set

## Purpose

This folder now documents the target GCP operating model, the remaining production-readiness gaps, and the deployment/operations workflow.

It is no longer intended to be a step-by-step migration scratchpad.

## Current position

The repository already contains most of the code-level changes needed for:

- frontend on Cloud Run
- backend on Cloud Run
- PostgreSQL on Cloud SQL
- durable application-managed objects on GCS

The main remaining work is now the live-production layer on top of an already-hardened repository:

- real GCP resource wiring and live validation
- cloud-side Identity Platform and issuer rollout
- backup/restore and rollback procedure ownership
- production monitoring, alerting, and routine change management

## What is already treated as settled

- frontend and backend remain separate Cloud Run services
- the frontend calls the backend through an absolute HTTPS base URL ending in `/api`
- `VITE_API_BASE` stays build-time configuration
- Alembic runs outside normal request-serving startup
- persistent application-managed files use GCS
- Cloud SQL uses the connector / Unix socket model
- the first rollout keeps nginx in the frontend container
- repository auth now assumes Bearer JWT identity and already includes Identity Platform email/password UI, JWKS-backed verification, diagnostics gating, and structured domain audit logs
- order import no longer accepts legacy `pdf_link`; `quotation_document_url` is now the only supported contract

## Reading order

1. `target_architecture.md`
2. `migration_checklist.md`
3. `environment_and_runtime_matrix.md`
4. `cloud_run_deployment_runbook.md`
5. `security_and_cost_considerations.md`
6. `github_actions_environment_setup.md`

Use these only as supporting references:

- `implementation_plan.md`
- `implementation_slices.md`
- `task_breakdown_by_file.md`

## File roles

- `target_architecture.md`: canonical target topology and operating boundaries
- `migration_checklist.md`: production-readiness checklist focused on what is still missing
- `environment_and_runtime_matrix.md`: runtime/deployment variable contract
- `cloud_run_deployment_runbook.md`: deployment, update, rollback, and recovery workflow
- `security_and_cost_considerations.md`: security, robustness, and cost guardrails
- `github_actions_environment_setup.md`: GitHub Environment variables/secrets and first-time workflow order
- `implementation_plan.md`: remaining hardening workstreams
- `implementation_slices.md`: compressed execution order split between repo-side follow-up and post-project work
- `task_breakdown_by_file.md`: repository surfaces that still matter if further hardening code changes are needed

## Scope rule

Completed migration cleanup should be referenced only briefly.

If a document drifts back into historical implementation detail, simplify it and keep the focus on:

- what the production target is
- what remains incomplete
- how the system will be operated safely
