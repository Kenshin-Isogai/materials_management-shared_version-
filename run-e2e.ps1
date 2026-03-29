[CmdletBinding()]
param(
    [switch]$NoBuild,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PlaywrightArgs
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[materials-management:e2e] $Message"
}

function Wait-ForContainerHealthy {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ContainerName,
        [int]$TimeoutSeconds = 120
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $inspect = docker inspect $ContainerName 2>$null
        if ($LASTEXITCODE -eq 0 -and $inspect) {
            $payload = $inspect | ConvertFrom-Json
            $container = $payload[0]
            $healthStatus = $container.State.Health.Status
            if ($healthStatus -eq "healthy") {
                return
            }
            if ($container.State.Status -eq "exited") {
                throw "Container $ContainerName exited before becoming healthy."
            }
        }
        Start-Sleep -Seconds 2
    }

    throw "Container $ContainerName did not become healthy within $TimeoutSeconds seconds."
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptRoot

$baseCompose = Join-Path $scriptRoot "docker-compose.yml"
$projectName = "materials-e2e"
$composeArgs = @("compose", "-p", $projectName, "-f", $baseCompose)
$downArgs = @("down", "-v", "--remove-orphans")
$playwrightExitCode = 0
$previousNginxHostPort = $env:NGINX_HOST_PORT

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is not available on PATH."
}

if (-not (Get-Command npx -ErrorAction SilentlyContinue)) {
    throw "npx is not available on PATH."
}

try {
    $env:NGINX_HOST_PORT = "8088"
    Write-Step "Removing any previous isolated E2E stack..."
    & docker @composeArgs @downArgs
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose down failed with exit code $LASTEXITCODE."
    }

    $upArgs = @("up", "-d")
    if (-not $NoBuild) {
        $upArgs += "--build"
    }
    $upArgs += @("db", "backend")

    Write-Step "Starting isolated E2E backend stack..."
    & docker @composeArgs @upArgs
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose up failed with exit code $LASTEXITCODE."
    }

    Wait-ForContainerHealthy -ContainerName "$projectName-backend-1"

    $nginxUpArgs = @("up", "-d")
    if (-not $NoBuild) {
        $nginxUpArgs += "--build"
    }
    $nginxUpArgs += "nginx"

    Write-Step "Starting isolated E2E frontend gateway at http://127.0.0.1:8088 ..."
    & docker @composeArgs @nginxUpArgs
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose up nginx failed with exit code $LASTEXITCODE."
    }

    $ready = $false
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:8088/api/health" -UseBasicParsing -TimeoutSec 5
            if ($response.StatusCode -eq 200) {
                $ready = $true
                break
            }
        } catch {
            Start-Sleep -Seconds 2
        }
    }

    if (-not $ready) {
        throw "Isolated E2E stack did not become ready at http://127.0.0.1:8088/api/health."
    }

    Push-Location (Join-Path $scriptRoot "frontend")
    try {
        $env:PLAYWRIGHT_BASE_URL = "http://127.0.0.1:8088"
        Write-Step "Running Playwright against isolated stack..."
        & npx playwright test @PlaywrightArgs
        $playwrightExitCode = $LASTEXITCODE
    } finally {
        Remove-Item Env:PLAYWRIGHT_BASE_URL -ErrorAction SilentlyContinue
        Pop-Location
    }

    if ($playwrightExitCode -ne 0) {
        throw "Playwright failed with exit code $playwrightExitCode."
    }
} finally {
    Write-Step "Tearing down isolated E2E stack..."
    & docker @composeArgs @downArgs
    if ($null -eq $previousNginxHostPort) {
        Remove-Item Env:NGINX_HOST_PORT -ErrorAction SilentlyContinue
    } else {
        $env:NGINX_HOST_PORT = $previousNginxHostPort
    }
}

Write-Step "E2E run completed with isolated Docker state cleanup."
