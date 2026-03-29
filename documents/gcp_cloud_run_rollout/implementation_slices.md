# Remaining Execution Slices

## Purpose

This is the compressed execution order for the work that still matters.

Most code-migration slices are already complete and are intentionally omitted here.

## Slice 1: Provision and validate real cloud resources

Goal:

- move from repository readiness to actual environment validation

Main work:

- create Cloud Run, Cloud SQL, GCS, and Secret Manager resources
- validate the runtime contract in `dev`

## Slice 2: Establish operational safety baseline

Goal:

- make the service recoverable and observable before serious production use

Main work:

- backup/PITR policy
- GCS retention/versioning policy
- monitoring and alerts
- rollback rehearsal

## Slice 3: Formalize release workflow

Goal:

- make routine bug-fix and update rollout low-risk

Main work:

- image-tagged release flow
- `dev` -> `staging` -> `prod`
- explicit migration step
- revision-based rollback

## Slice 4: Close the trust-boundary gap

Goal:

- replace the temporary mutation identity model

Main work:

- stronger auth
- explicit role enforcement
- endpoint exposure review
