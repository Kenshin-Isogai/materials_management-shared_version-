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

function ConvertTo-Base64Url {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)

    return [Convert]::ToBase64String($Bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function New-TestJwt {
    param(
        [Parameter(Mandatory = $true)][string]$Secret,
        [Parameter(Mandatory = $true)][string]$Subject,
        [Parameter(Mandatory = $true)][string]$Email,
        [Parameter(Mandatory = $true)][string]$Issuer,
        [Parameter(Mandatory = $true)][string]$Audience
    )

    $headerJson = @{ alg = "HS256"; typ = "JWT" } | ConvertTo-Json -Compress
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $payloadJson = @{
        sub = $Subject
        email = $Email
        email_verified = $true
        iss = $Issuer
        aud = $Audience
        iat = $now
        exp = $now + 3600
    } | ConvertTo-Json -Compress

    $headerEncoded = ConvertTo-Base64Url -Bytes ([Text.Encoding]::UTF8.GetBytes($headerJson))
    $payloadEncoded = ConvertTo-Base64Url -Bytes ([Text.Encoding]::UTF8.GetBytes($payloadJson))
    $unsignedToken = "$headerEncoded.$payloadEncoded"

    $hmac = [System.Security.Cryptography.HMACSHA256]::new([Text.Encoding]::UTF8.GetBytes($Secret))
    try {
        $signature = $hmac.ComputeHash([Text.Encoding]::UTF8.GetBytes($unsignedToken))
    } finally {
        $hmac.Dispose()
    }

    return "$unsignedToken.$(ConvertTo-Base64Url -Bytes $signature)"
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
$previousAuthMode = $env:AUTH_MODE
$previousRbacMode = $env:RBAC_MODE
$previousJwtSecret = $env:JWT_SHARED_SECRET
$previousJwtAlgorithms = $env:JWT_SIGNING_ALGORITHMS
$previousOidcProvider = $env:OIDC_PROVIDER
$previousOidcIssuer = $env:OIDC_EXPECTED_ISSUER
$previousOidcAudience = $env:OIDC_EXPECTED_AUDIENCE
$previousIdentityPlatformKey = $env:VITE_IDENTITY_PLATFORM_API_KEY
$previousPlaywrightToken = $env:PLAYWRIGHT_E2E_BEARER_TOKEN
$e2eJwtSecret = "playwright-e2e-shared-secret-for-materials-management"
$e2eOidcProvider = "test-oidc"
$e2eOidcIssuer = "https://playwright.e2e.local"
$e2eOidcAudience = "materials-management-playwright-e2e"
$e2eEmail = "e2e.admin@example.test"
$e2eSubject = "sub-e2e-admin"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is not available on PATH."
}

if (-not (Get-Command npx -ErrorAction SilentlyContinue)) {
    throw "npx is not available on PATH."
}

try {
    $env:NGINX_HOST_PORT = "8088"
    $env:AUTH_MODE = "oidc_enforced"
    $env:RBAC_MODE = "rbac_enforced"
    $env:JWT_SHARED_SECRET = $e2eJwtSecret
    $env:JWT_SIGNING_ALGORITHMS = "HS256"
    $env:OIDC_PROVIDER = $e2eOidcProvider
    $env:OIDC_EXPECTED_ISSUER = $e2eOidcIssuer
    $env:OIDC_EXPECTED_AUDIENCE = $e2eOidcAudience
    $env:VITE_IDENTITY_PLATFORM_API_KEY = "playwright-local"
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

    $env:PLAYWRIGHT_E2E_BEARER_TOKEN = New-TestJwt `
        -Secret $e2eJwtSecret `
        -Subject $e2eSubject `
        -Email $e2eEmail `
        -Issuer $e2eOidcIssuer `
        -Audience $e2eOidcAudience

    Write-Step "Bootstrapping isolated E2E admin user..."
    $bootstrapBody = @{
        username = "e2e.admin"
        display_name = "E2E Admin"
        email = $e2eEmail
        external_subject = $e2eSubject
        identity_provider = $e2eOidcProvider
        role = "admin"
        is_active = $true
    } | ConvertTo-Json
    $bootstrapResponse = Invoke-WebRequest `
        -Uri "http://127.0.0.1:8088/api/users" `
        -Method Post `
        -UseBasicParsing `
        -ContentType "application/json" `
        -Body $bootstrapBody
    if ($bootstrapResponse.StatusCode -ne 200) {
        throw "Bootstrap admin creation failed with status $($bootstrapResponse.StatusCode)."
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
    if ($null -eq $previousAuthMode) { Remove-Item Env:AUTH_MODE -ErrorAction SilentlyContinue } else { $env:AUTH_MODE = $previousAuthMode }
    if ($null -eq $previousRbacMode) { Remove-Item Env:RBAC_MODE -ErrorAction SilentlyContinue } else { $env:RBAC_MODE = $previousRbacMode }
    if ($null -eq $previousJwtSecret) { Remove-Item Env:JWT_SHARED_SECRET -ErrorAction SilentlyContinue } else { $env:JWT_SHARED_SECRET = $previousJwtSecret }
    if ($null -eq $previousJwtAlgorithms) { Remove-Item Env:JWT_SIGNING_ALGORITHMS -ErrorAction SilentlyContinue } else { $env:JWT_SIGNING_ALGORITHMS = $previousJwtAlgorithms }
    if ($null -eq $previousOidcProvider) { Remove-Item Env:OIDC_PROVIDER -ErrorAction SilentlyContinue } else { $env:OIDC_PROVIDER = $previousOidcProvider }
    if ($null -eq $previousOidcIssuer) { Remove-Item Env:OIDC_EXPECTED_ISSUER -ErrorAction SilentlyContinue } else { $env:OIDC_EXPECTED_ISSUER = $previousOidcIssuer }
    if ($null -eq $previousOidcAudience) { Remove-Item Env:OIDC_EXPECTED_AUDIENCE -ErrorAction SilentlyContinue } else { $env:OIDC_EXPECTED_AUDIENCE = $previousOidcAudience }
    if ($null -eq $previousIdentityPlatformKey) { Remove-Item Env:VITE_IDENTITY_PLATFORM_API_KEY -ErrorAction SilentlyContinue } else { $env:VITE_IDENTITY_PLATFORM_API_KEY = $previousIdentityPlatformKey }
    if ($null -eq $previousPlaywrightToken) { Remove-Item Env:PLAYWRIGHT_E2E_BEARER_TOKEN -ErrorAction SilentlyContinue } else { $env:PLAYWRIGHT_E2E_BEARER_TOKEN = $previousPlaywrightToken }
}

Write-Step "E2E run completed with isolated Docker state cleanup."
