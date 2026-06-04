# start-flowsint.ps1 — Start Flowsint production stack (Docker)
param(
    [switch]$Build
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$FlowsintDir = Join-Path $Root 'flowsint'

if (-not (Test-Path $FlowsintDir)) {
    Write-Host 'flowsint/ missing. Run: scripts/setup-flowsint.ps1' -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $FlowsintDir '.env'))) {
    & (Join-Path $PSScriptRoot 'setup-flowsint.ps1')
}

Write-Host '=== Starting Flowsint (docker compose prod) ===' -ForegroundColor Cyan
Push-Location $FlowsintDir
try {
    if ($Build) {
        docker compose -f docker-compose.prod.yml build
    }
    docker compose -f docker-compose.prod.yml up -d
    Write-Host 'Waiting for API health (up to 120s)...' -ForegroundColor DarkGray
    $deadline = (Get-Date).AddSeconds(120)
    $ok = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5001/health' -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -eq 200) { $ok = $true; break }
        } catch { Start-Sleep -Seconds 3 }
    }
    if ($ok) {
        Write-Host 'Flowsint API: OK (http://127.0.0.1:5001)' -ForegroundColor Green
    } else {
        Write-Host 'API not ready yet. Check: docker compose -f docker-compose.prod.yml logs -f api' -ForegroundColor Yellow
    }
    Write-Host 'Flowsint UI: http://localhost:5173' -ForegroundColor Green
    Write-Host 'Neo4j browser: http://localhost:7474' -ForegroundColor DarkGray
    Write-Host 'Embed in WorldBase OSINT tab -> FLOWSINT GRAPH' -ForegroundColor Cyan
}
finally {
    Pop-Location
}
