[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$IncludeDevOverride,
    [switch]$NoBuild
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[materials-management] $Message"
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptRoot

$envFile = Join-Path $scriptRoot ".env"
$baseCompose = Join-Path $scriptRoot "docker-compose.yml"
$devCompose = Join-Path $scriptRoot "docker-compose.override.yml"

if (-not (Test-Path $envFile)) {
    throw "Missing .env. Copy .env.example to .env and set the required values before starting the app."
}

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

$upArgs = @("up", "-d")
if (-not $NoBuild) {
    $upArgs += "--build"
}

Write-Step "Starting Docker services..."
if ($PSCmdlet.ShouldProcess("docker compose", (($composeArgs + $upArgs) -join " "))) {
    & docker @composeArgs @upArgs
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose up failed with exit code $LASTEXITCODE."
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

if ($IncludeDevOverride) {
    Write-Step "Dev override enabled. Frontend dev URL: http://127.0.0.1:5173/  API URL: http://127.0.0.1:8000/api"
} else {
    Write-Step "App URL: http://127.0.0.1/  API URL: http://127.0.0.1/api  Swagger: http://127.0.0.1/docs"
}
