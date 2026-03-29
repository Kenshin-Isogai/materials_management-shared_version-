# Security, Robustness, and Cost Considerations

## Scope rule

Backward compatibility is intentionally out of scope for these recommendations.

This document focuses on operating the target GCP deployment safely.

## 1. Security priorities

### Current posture to treat as temporary

- anonymous reads are allowed
- browser/API mutations now rely on verified Bearer JWT identity
- RBAC scaffolding exists in the repository, but live production posture still depends on enforced deployment settings and cloud validation
- the backend remains browser-reachable in the first rollout model

### Main conclusion

The current codebase is cloud-aware and the repo-side trust boundary is now materially hardened.

Treat manual token pasting as a local/test fallback only. The intended production browser path is Google Identity sign-in plus deployed JWKS verification.

### Immediate hardening targets

1. Roll out real Google/OIDC client, issuer, audience, and JWKS settings in cloud environments.
2. Keep manual token entry limited to local/test fallback use.
3. Keep diagnostic/admin endpoint exposure restricted in cloud environments.
4. Keep CORS explicit to the real frontend origin set only.
5. Source all secrets from Secret Manager.
6. Preserve audit visibility for imports, exports, undo, and high-impact mutations.

## 2. Robustness and recoverability

### Current strengths

- runtime posture is explicit for local vs Cloud Run
- durable file flows now route through a storage abstraction
- request-size and concurrency guardrails are documented
- item import jobs have operator-visible metadata and undo/redo support
- manual order import jobs now also persist operator-visible metadata plus safe undo/redo with conflict checks
- the repo now documents the expected Cloud SQL backup/PITR and GCS lifecycle/recovery contract for the first rollout

### Current gaps

- repository-side bearer-token auth, Google Identity UI, JWKS verification, and audit logging now exist; live cloud validation still remains
- live cloud validation is still pending
- Cloud SQL backup/PITR policy is documented, but real per-environment enablement is still pending
- GCS lifecycle/versioning policy is documented, but real per-environment enablement is still pending
- revision rollback and DB recovery are separate concerns and are not yet fully operationalized

### Practical interpretation

The system is reasonably prepared for controlled rollout and staging use.

It is not yet sufficient for confident long-term production operation unless the team also lands:

- backup/restore policy
- rollback rehearsal
- monitoring baseline
- stronger trust boundary

## 3. Cost and scale risk review

### Cloud SQL risk areas

- Cloud Run autoscaling can multiply DB connections quickly.
- Heavy planning endpoints can create expensive repeated reads under load.
- Poorly bounded concurrency can force a larger Cloud SQL instance than expected.

Recommended controls:

- conservative pool sizing
- conservative Cloud Run concurrency
- query/index review for planning and reporting hot paths

### Cloud Run risk areas

- synchronous CSV and planning flows can consume CPU and memory
- long-running heavy requests can tie up instance capacity
- bad rollout settings can create unnecessary instance churn

Recommended controls:

- keep startup lean
- keep request size bounded
- monitor error/latency before increasing concurrency

### GCS risk areas

- artifacts and archives can grow quietly
- failed cleanup of staging-like objects can accumulate cost
- object retention can drift away from policy if never operationalized

Recommended controls:

- lifecycle rules by prefix
- clear owner for retention policy review
- periodic storage growth review

## 4. Minimum production controls

Do not call the rollout robust until all of the following are active:

- Cloud SQL backup and recovery policy
- GCS lifecycle/versioning policy
- revision rollback procedure
- production monitoring and alerts
- explicit ownership for deployment and incident response

## 5. First-rollout operating assumptions

- small-team workload
- conservative backend Cloud Run concurrency around 10 requests per instance
- 32 MB request-size ceiling
- heavy synchronous requests should usually complete within about 60 seconds
- file downloads remain backend-mediated rather than direct object-store URLs
