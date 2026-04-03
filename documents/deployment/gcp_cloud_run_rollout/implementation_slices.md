# Remaining Execution Slices

## Purpose

This is the compressed execution order for the work that still matters.

Most code-migration slices are already complete and are intentionally omitted here.

## Slice 1: Finish repo-side trust-boundary follow-up

Goal:

- complete the remaining code/documentation work that does not require a live GCP project

Current status:

- repo-side implementation is now in place for Identity Platform login UI, JWKS-backed verification, domain audit logging, and diagnostics exposure policy
- remaining follow-up is live cloud-side configuration and validation, not additional repository scaffolding

Main work:

- add Identity Platform frontend login UI/state flow
- add deployed-environment JWKS/OIDC verification
- add domain audit logging for high-impact mutations
- review public diagnostics posture for cloud deployments

## Slice 2: Provision and validate real cloud resources

Goal:

- move from repository readiness to actual environment validation

Main work:

- create Cloud Run, Cloud SQL, GCS, and Secret Manager resources
- validate the runtime contract in `dev`

## Slice 3: Establish operational safety baseline

Goal:

- make the service recoverable and observable before serious production use

Main work:

- backup/PITR policy
- GCS retention/versioning policy
- monitoring and alerts
- rollback rehearsal

## Slice 4: Formalize release workflow

Goal:

- make routine bug-fix and update rollout low-risk

Main work:

- image-tagged release flow
- `dev` -> `staging` -> `prod`
- explicit migration step
- revision-based rollback

## Slice 5: Promote to staged rollout

Goal:

- move from validated `dev` infrastructure to routine staged operation

Main work:

- `dev` -> `staging` -> `prod`
- revision-based rollback rehearsal
- production monitoring ownership
