# GCP Cloud Run Rollout Documentation Set

## Purpose

This folder consolidates the implementation prerequisites for operating this application on Google Cloud Platform with the following target architecture:

- Frontend on Cloud Run
- Backend on Cloud Run
- PostgreSQL on Cloud SQL
- File/object storage on Google Cloud Storage

This documentation set is intended to be the working base for upcoming implementation and rollout tasks.

## Explicit Scope Decision

Backward compatibility is explicitly out of scope for this rollout plan.

That means implementation work may remove compatibility-only behavior, legacy folder migration logic, path translation helpers, and other transitional code if they are not required for the target GCP operating model.

## Contents

- `implementation_plan.md`: phased implementation plan and execution order
- `migration_checklist.md`: actionable checklist for engineering work, validation, and rollout readiness
- `target_architecture.md`: target runtime architecture, boundaries, and design decisions
- `security_and_cost_considerations.md`: security hardening priorities and cost-risk review
- `task_breakdown_by_file.md`: concrete engineering work mapped to repository files and functions
- `environment_and_runtime_matrix.md`: environment variables, service ownership, secrecy, and rollout recommendations
- `implementation_slices.md`: practical end-to-end delivery slices that still finish the full target rollout

## How To Use This Folder

1. Read `target_architecture.md` first.
2. Use `implementation_plan.md` as the source of truth for sequencing.
3. Use `migration_checklist.md` to track delivery readiness.
4. Use `security_and_cost_considerations.md` when defining implementation details, runtime defaults, and monitoring.

## Repository-Specific Context Carried Into This Plan

- The backend already distinguishes `local` vs `cloud_run` runtime posture through `APP_RUNTIME_TARGET`.
- Mutation requests currently require `X-User-Name`.
- The current implementation still depends heavily on filesystem-backed import and export flows under `imports/` and `exports/`.
- Cloud Run runtime safety has started, but persistent storage abstraction is not complete.

## Decision Summary

The target rollout should optimize for:

- stateless Cloud Run services
- managed PostgreSQL on Cloud SQL
- object storage on GCS instead of persistent local filesystem assumptions
- explicit security boundaries
- predictable operational cost

The target rollout should not optimize for preserving old local/shared-server compatibility behavior.
