# GitHub Actions Environment Setup

## Purpose

This file records the GitHub Environment values needed by `.github/workflows/deploy-gcp.yml`.

The workflow now supports staged rollout:

- `deploy_target=backend`
- `deploy_target=frontend`
- `deploy_target=full`

Use `backend` first when a new environment does not yet have a known frontend URL.
After the first backend deployment, record the backend URL in the GitHub Environment and run `frontend`.
After the first frontend deployment, record the frontend URL in the GitHub Environment and then use `full` for normal updates.

## Environment Variables

Set these for every environment.

| Variable | dev | staging | prod | Notes |
|---|---|---|---|---|
| `GCP_PROJECT_ID` | `production-management-491908` | `production-management-491908` | `production-management-491908` | Shared project |
| `GCP_REGION` | `asia-northeast1` | `asia-northeast1` | `asia-northeast1` | Shared region |
| `GCP_ARTIFACT_REGISTRY` | `materials-management` | `materials-management` | `materials-management` | Artifact Registry repository |
| `BACKEND_SERVICE_NAME` | `materials-management-backend` | `materials-management-backend` | `materials-management-backend` | Cloud Run backend service |
| `FRONTEND_SERVICE_NAME` | `materials-management-frontend` | `materials-management-frontend` | `materials-management-frontend` | Cloud Run frontend service |
| `INSTANCE_CONNECTION_NAME` | `production-management-491908:asia-northeast1:component-management` | `production-management-491908:asia-northeast1:component-management` | `production-management-491908:asia-northeast1:component-management` | Current Cloud SQL instance |
| `GCS_OBJECT_PREFIX` | `materials-management` | `materials-management` | `materials-management` | Shared prefix root |
| `JWT_SIGNING_ALGORITHMS` | `RS256` | `RS256` | `RS256` | Required for Identity Platform tokens |
| `DATABASE_URL_SECRET_NAME` | `materials-backend-database-url-dev` | `materials-backend-database-url-staging` | `materials-backend-database-url-prod` | Secret Manager name |
| `GCS_BUCKET` | `component_management_dev` | `component_management_staging` | `component_management_prod` | Per-environment bucket |
| `BACKEND_URL` | `https://materials-management-backend-mh7z4xjsvq-an.a.run.app` | set after first backend deploy | set after first backend deploy | Required for frontend builds |
| `FRONTEND_URL` | `https://materials-management-frontend-mh7z4xjsvq-an.a.run.app` | set after first frontend deploy | set after first frontend deploy | Required for backend CORS/public URL metadata |
| `OIDC_REQUIRE_EMAIL_VERIFIED` | `0` | `0` or `1` | `1` recommended | `0` keeps current dev-friendly posture |

## Environment Secrets

Set these for every environment.

| Secret | Notes |
|---|---|
| `GOOGLE_WORKLOAD_IDENTITY_PROVIDER` | GitHub Actions federation provider resource name |
| `GOOGLE_SERVICE_ACCOUNT` | Deployer service account used by GitHub Actions |
| `BACKEND_RUNTIME_SERVICE_ACCOUNT` | Cloud Run backend runtime service account |
| `FRONTEND_RUNTIME_SERVICE_ACCOUNT` | Cloud Run frontend runtime service account |
| `MIGRATE_RUNTIME_SERVICE_ACCOUNT` | Cloud Run Job migration service account |
| `IDENTITY_PLATFORM_API_KEY` | Frontend build-time Identity Platform web API key |

## First-time rollout flow

### New environment: backend first

1. Leave `FRONTEND_URL` empty.
2. Set `BACKEND_URL` empty if the backend service does not exist yet.
3. Run the workflow with:
   - `environment=<env>`
   - `image_tag=<new-tag>`
   - `deploy_target=backend`
4. Read the created backend Cloud Run URL.
5. Save that URL into the environment variable `BACKEND_URL`.

### Then frontend

1. Ensure `BACKEND_URL` is set.
2. Run the workflow with:
   - `environment=<env>`
   - `image_tag=<new-tag>`
   - `deploy_target=frontend`
3. Read the created frontend Cloud Run URL.
4. Save that URL into the environment variable `FRONTEND_URL`.

### Then normal updates

Once both URLs are saved, use:

- `deploy_target=full`

for normal image rollouts.
