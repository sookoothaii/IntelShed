# setup-yente.ps1 — Setup Yente (OpenSanctions) Docker Stack for WorldBase
# Requires: Docker Desktop (Linux containers)
$ErrorActionPreference = 'Stop'

$Root = Split-Path $PSScriptRoot -Parent
$YenteDir = Join-Path $Root 'yente'

Write-Host '=== Yente (OpenSanctions) setup (WorldBase) ===' -ForegroundColor Cyan

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host 'Docker not found. Install Docker Desktop and enable Linux containers.' -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $YenteDir)) {
    Write-Host "Creating $YenteDir"
    New-Item -ItemType Directory -Path $YenteDir | Out-Null
}

Push-Location $YenteDir
try {
    # Generate an enterprise-ready docker-compose.yml for Yente
    $composeFile = 'docker-compose.yml'
    $composeContent = @"
version: '3.8'

services:
  yente:
    image: ghcr.io/opensanctions/yente:latest
    ports:
      - "8003:8000"
    environment:
      # Automatically download the default dataset on boot
      - YENTE_DATASTORE_URL=https://data.opensanctions.org/datasets/latest/default/targets.simple.json
    restart: unless-stopped
    mem_limit: 2g # Cap memory usage to leave room for Ollama/Cesium
"@
    [IO.File]::WriteAllText($composeFile, $composeContent)
    Write-Host 'Created yente/docker-compose.yml' -ForegroundColor Green

    # Automatically update WorldBase .env to point to the new Yente instance
    $backendEnv = Join-Path $Root 'backend\.env'
    if (Test-Path $backendEnv) {
        $lines = Get-Content $backendEnv -Raw
        if ($lines -notmatch 'OPENSANCTIONS_YENTE_URL=') {
            $lines += "`nOPENSANCTIONS_YENTE_URL=http://localhost:8003`n"
            Set-Content -Path $backendEnv -Value $lines -NoNewline
            Write-Host 'Added OPENSANCTIONS_YENTE_URL to backend/.env' -ForegroundColor Green
        } elseif ($lines -match 'OPENSANCTIONS_YENTE_URL=\s*(?:#|$)') {
            $lines = $lines -replace '(?m)^#?\s*OPENSANCTIONS_YENTE_URL=.*$', 'OPENSANCTIONS_YENTE_URL=http://localhost:8003'
            Set-Content -Path $backendEnv -Value $lines -NoNewline
            Write-Host 'Updated OPENSANCTIONS_YENTE_URL in backend/.env' -ForegroundColor Green
        } else {
            Write-Host 'OPENSANCTIONS_YENTE_URL already configured in backend/.env' -ForegroundColor DarkGray
        }
    } else {
        Write-Host "backend/.env not found. Please set OPENSANCTIONS_YENTE_URL=http://localhost:8003 manually." -ForegroundColor Yellow
    }

    Write-Host ''
    Write-Host 'Next: scripts/start-yente.ps1  (Will download ~30MB JSON on first boot)' -ForegroundColor Yellow
    Write-Host 'API: http://localhost:8003' -ForegroundColor DarkGray
}
finally {
    Pop-Location
}
