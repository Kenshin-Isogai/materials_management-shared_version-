# Remaining Repository Surfaces

## Purpose

This file lists the repository surfaces that still matter if additional hardening work is needed.

Most migration-oriented file-by-file cleanup has already been completed and is intentionally not repeated here.

## Runtime and deployment surfaces

| File | Why it still matters |
|---|---|
| `backend\app\api.py` | Health/auth signaling, middleware posture, and request guardrails |
| `backend\app\config.py` | Runtime target, DB pool, CORS, upload, and storage settings |
| `backend\app\auth.py` | Bearer-token identity resolution, JWT verification hooks, and endpoint role policy |
| `backend\app\storage.py` | Durable object boundary for GCS-backed operation |
| `backend\app\db.py` | engine configuration and migration/bootstrap behavior |
| `frontend\src\components\AppShell.tsx` | Current token-entry UX that should later be replaced with Google Identity login |
| `frontend\src\lib\api.ts` | Browser token storage and Authorization header injection |
| `backend\Dockerfile` | backend process model and Cloud Run image behavior |
| `frontend\Dockerfile` | build-time API base handling |
| `frontend\nginx.conf` | static delivery contract for the Cloud Run frontend image |
| `docker-compose.yml` | local convenience stack; must remain clearly distinct from cloud production assumptions |

## Recovery and operator-flow surfaces

| File | Why it still matters |
|---|---|
| `backend\app\service.py` | import-job recovery behavior, artifact/archive handling, and business-rule rollback limits |
| `backend\tests\test_runtime_config.py` | runtime contract regression coverage |
| `backend\tests\test_storage.py` | GCS/local storage boundary regression coverage |

## Documentation surfaces

| File | Why it still matters |
|---|---|
| `documents\gcp_cloud_run_rollout\migration_checklist.md` | production-readiness status |
| `documents\gcp_cloud_run_rollout\cloud_run_deployment_runbook.md` | deployment/update/rollback/recovery procedure |
| `documents\gcp_cloud_run_rollout\environment_and_runtime_matrix.md` | environment contract |
| `documents\gcp_cloud_run_rollout\security_and_cost_considerations.md` | risk and operating guardrails |

## If more code hardening is needed

The most likely remaining code work would be in these areas:

- stronger production authentication
- replacing manual token entry with Google Identity sign-in
- JWKS/OIDC-backed deployed verification
- restricting diagnostic/admin endpoint exposure
- extending domain audit logging
- extending operational telemetry
