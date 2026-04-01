param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [string]$Region = "asia-northeast1",

    [string]$Repository = "materials-management",

    [string]$ImageTag = "latest",

    [string]$ServiceName = "materials-management-backend",

    [Parameter(Mandatory = $true)]
    [string]$ServiceAccount,

    [Parameter(Mandatory = $true)]
    [string]$InstanceConnectionName,

    [Parameter(Mandatory = $true)]
    [string]$Bucket,

    [string]$ObjectPrefix = "materials-management",

    [Parameter(Mandatory = $true)]
    [string]$FrontendUrl,

    [Parameter(Mandatory = $true)]
    [string]$BackendUrl,

    [Parameter(Mandatory = $true)]
    [string]$DatabaseUrlSecretName
)

$ErrorActionPreference = "Stop"

$image = "{0}-docker.pkg.dev/{1}/{2}/materials-backend:{3}" -f $Region, $ProjectId, $Repository, $ImageTag

docker build -t $image .\backend
docker push $image

$envVars = @(
    "APP_RUNTIME_TARGET=cloud_run",
    "AUTO_MIGRATE_ON_STARTUP=0",
    "STRUCTURED_LOGGING=1",
    "WEB_CONCURRENCY=2",
    "DB_POOL_SIZE=5",
    "DB_MAX_OVERFLOW=10",
    "DB_POOL_TIMEOUT=30",
    "DB_POOL_RECYCLE_SECONDS=1800",
    "MAX_UPLOAD_BYTES=33554432",
    "HEAVY_REQUEST_TARGET_SECONDS=60",
    "CLOUD_RUN_CONCURRENCY_TARGET=10",
    "STORAGE_BACKEND=gcs",
    "GCS_BUCKET=$Bucket",
    "GCS_OBJECT_PREFIX=$ObjectPrefix",
    "INSTANCE_CONNECTION_NAME=$InstanceConnectionName",
    "CORS_ALLOWED_ORIGINS=$FrontendUrl",
    "BACKEND_PUBLIC_BASE_URL=$BackendUrl",
    "FRONTEND_PUBLIC_BASE_URL=$FrontendUrl",
    "AUTH_MODE=oidc_enforced",
    "RBAC_MODE=rbac_enforced",
    "JWT_VERIFIER=jwks",
    "OIDC_PROVIDER=identity_platform",
    "OIDC_EXPECTED_ISSUER=https://securetoken.google.com/$ProjectId",
    "OIDC_EXPECTED_AUDIENCE=$ProjectId",
    "OIDC_JWKS_URL=https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com",
    "OIDC_REQUIRE_EMAIL_VERIFIED=1",
    "DIAGNOSTICS_AUTH_ROLE=admin"
) -join ","

gcloud run deploy $ServiceName `
    --project $ProjectId `
    --region $Region `
    --image $image `
    --service-account $ServiceAccount `
    --allow-unauthenticated `
    --set-cloudsql-instances $InstanceConnectionName `
    --set-secrets "DATABASE_URL=$DatabaseUrlSecretName:latest" `
    --set-env-vars $envVars `
    --concurrency 10 `
    --cpu 1 `
    --memory 1Gi `
    --timeout 300 `
    --min-instances 0 `
    --max-instances 10
