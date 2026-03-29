# Remaining Production Hardening Plan

## Objective

Most Cloud Run migration-oriented code changes are already in place.

The remaining plan is to close the gap between "deployable" and "operationally safe".

## Main conclusion

The current repository is close to infrastructure-ready, but not yet production-ready.

The largest remaining risks are:

- live cloud validation has not yet happened
- cloud-side Google/OIDC client and issuer rollout is not yet finished
- rollback and restore procedures are not yet institutionalized
- monitoring and alert ownership are not yet spelled out

## Workstream 1: Identity and trust boundary

Goal:

- finish live production rollout on top of the now-complete repo-side bearer-token auth foundation

Needed outcome:

- a real Google Identity sign-in flow exists for browser mutations
- deployed environments use the `jwks` verifier path with real issuer/audience/JWKS settings
- admin/operator/viewer boundaries are explicit and enforced
- production does not rely on manual token pasting as its long-term browser login model

Notes:

- this is the highest-priority functional hardening item
- repo-side auth plumbing is already in place; the remaining work is the live identity/login configuration and deployed-verifier validation slice

## Workstream 2: Real-environment deployment validation

Goal:

- prove the runtime contract against actual Cloud Run, Cloud SQL, and GCS resources

Needed outcome:

- backend health confirms the expected cloud posture
- frontend-to-backend CORS behaves correctly
- durable artifact/archive flows work against GCS
- request latency and Cloud SQL connection behavior are observed under real settings

Notes:

- this cannot be completed in a doc-only state
- the repository already appears prepared for this step, but that is not equivalent to validation

## Workstream 3: Change management and rollback

Goal:

- make bug-fix and update deployment routine, reversible, and low-risk

Needed outcome:

- deploys are image-tagged and revision-based
- schema migration is run explicitly before or during rollout in a controlled step
- staged rollout exists through `dev` -> `staging` -> `prod`
- rollback means both application rollback and database recovery decision paths are documented

Notes:

- application rollback and database rollback are different operations and must not be conflated
- reversible app deploys do not remove the need for Cloud SQL backup/PITR planning

## Workstream 4: Backup, restore, and recoverability

Goal:

- define how the service is recovered after bad deploys, operator mistakes, or infrastructure incidents

Needed outcome:

- Cloud SQL backup and point-in-time recovery expectations are documented and enabled
- GCS lifecycle/versioning expectations are documented and enabled where appropriate
- operators know when to use item-import undo/redo, when to restore from DB backup, and when to redeploy an older revision

Notes:

- import-job undo/redo exists only for some flows
- that is helpful, but it is not a substitute for full system recovery planning

## Workstream 5: Monitoring and operational ownership

Goal:

- make failures visible before they become data or service incidents

Needed outcome:

- request latency, error rate, instance count, and DB connection pressure are monitored
- storage growth and failed artifact/archive flows are visible
- deployment, migration, and recovery ownership is assigned

## Suggested execution order

1. complete repo-side follow-up for Google Identity/JWKS, audit logging, and diagnostics posture
2. real GCP resource provisioning
3. live validation in `dev`
4. monitoring and backup baseline
5. staged deployment workflow (`dev` -> `staging` -> `prod`)

## Definition of operational readiness

Treat the rollout as operationally ready only when all of the following are true:

- live Cloud Run, Cloud SQL, and GCS validation has been completed
- backup and restore expectations are active, not just documented
- rollback procedure is rehearsed
- production monitoring exists
- the current bearer-token posture is backed by real Google Identity/JWKS or is explicitly accepted with time-bounded risk ownership
