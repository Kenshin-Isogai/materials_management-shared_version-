param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [Parameter(Mandatory = $true)]
    [string]$SecretName,

    [Parameter(Mandatory = $true)]
    [string]$SecretValue
)

$ErrorActionPreference = "Stop"

gcloud secrets describe $SecretName --project $ProjectId | Out-Null 2>$null
if ($LASTEXITCODE -ne 0) {
    gcloud secrets create $SecretName --replication-policy="automatic" --project $ProjectId | Out-Null
}

$SecretValue | gcloud secrets versions add $SecretName --data-file=- --project $ProjectId
