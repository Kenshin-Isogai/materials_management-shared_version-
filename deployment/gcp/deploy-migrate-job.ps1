param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [string]$Region = "asia-northeast1",

    [string]$Repository = "materials-management",

    [string]$ImageTag = "latest",

    [string]$JobName = "materials-management-backend-migrate",

    [Parameter(Mandatory = $true)]
    [string]$ServiceAccount,

    [Parameter(Mandatory = $true)]
    [string]$InstanceConnectionName,

    [Parameter(Mandatory = $true)]
    [string]$DatabaseUrlSecretName
)

$ErrorActionPreference = "Stop"

$image = "{0}-docker.pkg.dev/{1}/{2}/materials-backend:{3}" -f $Region, $ProjectId, $Repository, $ImageTag
$databaseSecretRef = "DATABASE_URL={0}:latest" -f $DatabaseUrlSecretName

gcloud run jobs deploy $JobName `
    --project $ProjectId `
    --region $Region `
    --image $image `
    --service-account $ServiceAccount `
    --set-cloudsql-instances $InstanceConnectionName `
    --set-secrets $databaseSecretRef `
    --set-env-vars "APP_RUNTIME_TARGET=cloud_run,AUTO_MIGRATE_ON_STARTUP=0" `
    --command uv `
    --args run `
    --args alembic `
    --args upgrade `
    --args head

gcloud run jobs execute $JobName --project $ProjectId --region $Region --wait
