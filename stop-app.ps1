[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$IncludeDevOverride,
    [switch]$RemoveVolumes
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[materials-management] $Message"
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptRoot

$baseCompose = Join-Path $scriptRoot "docker-compose.yml"
$devCompose = Join-Path $scriptRoot "docker-compose.override.yml"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is not available on PATH."
}

$composeArgs = @("compose", "-f", $baseCompose)
if ($IncludeDevOverride) {
    if (-not (Test-Path $devCompose)) {
        throw "Requested -IncludeDevOverride, but docker-compose.override.yml was not found."
    }
    $composeArgs += @("-f", $devCompose)
}

$downArgs = @("down")
if ($RemoveVolumes) {
    $downArgs += "-v"
}

Write-Step "Stopping Docker services..."
if ($PSCmdlet.ShouldProcess("docker compose", (($composeArgs + $downArgs) -join " "))) {
    & docker @composeArgs @downArgs
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose down failed with exit code $LASTEXITCODE."
    }
}

Write-Step "Current container status:"
if ($WhatIfPreference) {
    Write-Step "WhatIf: skipping 'docker compose ps'."
} else {
    & docker @composeArgs ps
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose ps failed with exit code $LASTEXITCODE."
    }
}
