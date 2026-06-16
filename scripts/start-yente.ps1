# start-yente.ps1 — Start the Yente Docker stack
$ErrorActionPreference = 'Stop'

$Root = Split-Path $PSScriptRoot -Parent
$YenteDir = Join-Path $Root 'yente'

if (-not (Test-Path $YenteDir)) {
    Write-Host "Yente not setup. Run setup-yente.ps1 first." -ForegroundColor Red
    exit 1
}

Write-Host "Starting Yente on port 8003..." -ForegroundColor Cyan
Push-Location $YenteDir
try {
    docker compose up -d
} finally {
    Pop-Location
}

Write-Host "Started. WorldBase backend will automatically switch to Yente if OPENSANCTIONS_YENTE_URL is set in backend/.env." -ForegroundColor Green
