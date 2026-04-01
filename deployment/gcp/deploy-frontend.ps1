param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [string]$Region = "asia-northeast1",

    [string]$Repository = "materials-management",

    [string]$ImageTag = "latest",

    [string]$ServiceName = "materials-management-frontend",

    [Parameter(Mandatory = $true)]
    [string]$ServiceAccount,

    [Parameter(Mandatory = $true)]
    [string]$BackendUrl,

    [Parameter(Mandatory = $true)]
    [string]$IdentityPlatformApiKey
)

$ErrorActionPreference = "Stop"

$image = "{0}-docker.pkg.dev/{1}/{2}/materials-frontend:{3}" -f $Region, $ProjectId, $Repository, $ImageTag

docker build `
    -t $image `
    --build-arg "VITE_API_BASE=$BackendUrl/api" `
    --build-arg "VITE_IDENTITY_PLATFORM_API_KEY=$IdentityPlatformApiKey" `
    .\frontend

docker push $image

gcloud run deploy $ServiceName `
    --project $ProjectId `
    --region $Region `
    --image $image `
    --service-account $ServiceAccount `
    --allow-unauthenticated `
    --concurrency 50 `
    --cpu 1 `
    --memory 512Mi `
    --timeout 60 `
    --min-instances 0 `
    --max-instances 10
