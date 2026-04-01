# First-time Environment Bootstrap

## Purpose

This document records the first-time rollout sequence for a new environment such as `dev`, `staging`, or `prod`.

It assumes:

- one shared GCP project: `production-management-491908`
- one shared Cloud SQL instance: `component-management`
- one database per environment
- one GCS bucket per environment
- Cloud Run services named per environment

This sequence is written so the same pattern can be reused for `dev`, `staging`, and `prod`.

## Recommended naming

### Cloud Run services

- backend: `materials-management-backend-<env>`
- frontend: `materials-management-frontend-<env>`

Examples:

- `materials-management-backend-dev`
- `materials-management-frontend-dev`
- `materials-management-backend-staging`
- `materials-management-frontend-staging`

### Cloud SQL databases

- `Wega_dev`
- `Wega_staging`
- `Wega_prod`

### Secret Manager names

- `materials-backend-database-url-dev`
- `materials-backend-database-url-staging`
- `materials-backend-database-url-prod`

### GCS buckets

- `component_management_dev`
- `component_management_staging`
- `component_management_prod`

## Migration job note

The repository currently uses one shared Cloud Run Job name:

- `materials-management-backend-migrate`

This is acceptable because the job is only a deployment-time Alembic runner. It is reconfigured per execution/deploy and does not serve traffic.

You do not need a separate migration job per environment unless your operational model requires stricter isolation of job names.

## Step 1: Create the environment database

Example for `dev`:

```powershell
gcloud sql databases create Wega_dev `
  --instance=component-management `
  --project=production-management-491908
```

Repeat with `Wega_staging` / `Wega_prod` for later environments.

## Step 2: Put DATABASE_URL into Secret Manager

Example `dev` connection string:

```text
postgresql+psycopg://DBmanager:<PASSWORD>@/Wega_dev?host=/cloudsql/production-management-491908:asia-northeast1:component-management
```

Example command:

```powershell
.\deployment\gcp\upsert-secret.ps1 `
  -ProjectId production-management-491908 `
  -SecretName materials-backend-database-url-dev `
  -SecretValue 'postgresql+psycopg://DBmanager:<PASSWORD>@/Wega_dev?host=/cloudsql/production-management-491908:asia-northeast1:component-management'
```

## Step 3: Prepare GitHub Environment variables

Before the first deployment, configure the GitHub Environment using:

- [github_actions_environment_setup.md](C:/Users/IsogaiKenshin/Documents/Yaqumo/applications/materials_menagement(shared_version)/documents/gcp_cloud_run_rollout/github_actions_environment_setup.md)

For a brand-new environment:

- set `BACKEND_SERVICE_NAME` / `FRONTEND_SERVICE_NAME` to environment-specific names
- leave `BACKEND_URL` empty
- leave `FRONTEND_URL` empty

## Step 4: Run backend-only GitHub Actions deployment

Workflow inputs:

- `environment=<env>`
- `image_tag=<new-tag>`
- `deploy_target=backend`

This does:

1. build backend image
2. push backend image
3. deploy and run the shared migration job
4. deploy the backend Cloud Run service

## Step 5: Read the backend URL

Example for `dev`:

```powershell
gcloud run services describe materials-management-backend-dev `
  --region asia-northeast1 `
  --project production-management-491908 `
  --format="value(status.url)"
```

Save the returned URL into the GitHub Environment variable:

- `BACKEND_URL`

## Step 6: Run frontend-only GitHub Actions deployment

Workflow inputs:

- `environment=<env>`
- `image_tag=<same-or-new-tag>`
- `deploy_target=frontend`

This uses `BACKEND_URL` during the frontend build for:

- `VITE_API_BASE=https://<backend-service-url>/api`

## Step 7: Read the frontend URL

Example for `dev`:

```powershell
gcloud run services describe materials-management-frontend-dev `
  --region asia-northeast1 `
  --project production-management-491908 `
  --format="value(status.url)"
```

Save the returned URL into the GitHub Environment variable:

- `FRONTEND_URL`

## Step 8: Run a full deployment once

Workflow inputs:

- `environment=<env>`
- `image_tag=<new-tag>`
- `deploy_target=full`

This finalizes:

- backend `CORS_ALLOWED_ORIGINS`
- backend `FRONTEND_PUBLIC_BASE_URL`
- backend `BACKEND_PUBLIC_BASE_URL`
- frontend build against the saved backend URL

## Step 9: Smoke validation

Example backend checks:

```powershell
$env:BACKEND_URL="https://<backend-service-url>"

curl.exe "${env:BACKEND_URL}/readyz"
curl.exe -i `
  -H "Origin: https://<frontend-service-url>" `
  "${env:BACKEND_URL}/readyz"
```

Expected:

- `/readyz` returns `status=ok`
- the CORS test returns `access-control-allow-origin: https://<frontend-service-url>`

## Step 10: Bootstrap the first admin user

This application allows anonymous `POST /api/users` only while there are zero active users.

Example:

```powershell
$env:BACKEND_URL="https://<backend-service-url>"

$body = @{
  username = "admin_isogai"
  display_name = "admin_isogai"
  role = "admin"
  is_active = $true
  email = "kenshin.isogai@yaqumo.com"
} | ConvertTo-Json

curl.exe `
  -X POST `
  -H "Content-Type: application/json" `
  -d $body `
  "${env:BACKEND_URL}/api/users"
```

Important:

- use `email` for the first bootstrap mapping
- do not send `identity_provider` without `external_subject`

## Step 11: Sign in through Identity Platform

1. Create the same email address in Identity Platform email/password users.
2. Open the frontend.
3. Sign in with that email/password.
4. Confirm normal list pages load.
5. Confirm at least one mutation succeeds.

## Current dev-specific notes

The current working `dev` posture uses:

- `JWT_SIGNING_ALGORITHMS=RS256`
- `OIDC_REQUIRE_EMAIL_VERIFIED=0`

`OIDC_REQUIRE_EMAIL_VERIFIED=0` is acceptable for the current dev rollout because the bootstrap Identity Platform users are not yet guaranteed to have verified email state.

For production-oriented environments, prefer switching that value to `1` only after verified-email behavior is confirmed.
