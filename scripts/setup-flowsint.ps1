# setup-flowsint.ps1 — Clone reconurge/flowsint and prepare .env for WorldBase
# Requires: Git, Docker Desktop (Linux containers)
$ErrorActionPreference = 'Stop'

$Root = Split-Path $PSScriptRoot -Parent
$FlowsintDir = Join-Path $Root 'flowsint'
$Repo = 'https://github.com/reconurge/flowsint.git'

Write-Host '=== Flowsint setup (WorldBase) ===' -ForegroundColor Cyan

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host 'Git not found in PATH.' -ForegroundColor Red
    exit 1
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host 'Docker not found. Install Docker Desktop and enable Linux containers.' -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $FlowsintDir)) {
    Write-Host "Cloning $Repo -> $FlowsintDir"
    git clone --depth 1 $Repo $FlowsintDir
} else {
    Write-Host "Repo exists: $FlowsintDir (git pull skipped; delete folder to re-clone)"
}

Push-Location $FlowsintDir
try {
    if (-not (Test-Path '.env')) {
        Copy-Item '.env.example' '.env'
        Write-Host 'Created flowsint/.env from .env.example' -ForegroundColor Green
    }

    # Allow WorldBase dev UI (5176) in API CORS when using local Vite
    $envPath = Join-Path $FlowsintDir '.env'
    $lines = Get-Content $envPath -Raw
    if ($lines -notmatch 'localhost:5176') {
        $lines = $lines -replace 'ALLOWED_ORIGINS=.*', 'ALLOWED_ORIGINS=http://localhost:5173,http://localhost:5176,http://127.0.0.1:5173,http://127.0.0.1:5176'
        if ($lines -notmatch 'ALLOWED_ORIGINS=') {
            $lines += "`nALLOWED_ORIGINS=http://localhost:5173,http://localhost:5176,http://127.0.0.1:5173,http://127.0.0.1:5176`n"
        }
        Set-Content -Path $envPath -Value $lines -NoNewline
        Write-Host 'Updated ALLOWED_ORIGINS for WorldBase :5176' -ForegroundColor Green
    }

    # Windows git often checks out CRLF; Linux entrypoints fail with "exec format error"
    $entry = Join-Path $FlowsintDir 'flowsint-api\entrypoint.sh'
    if (Test-Path $entry) {
        $raw = [IO.File]::ReadAllText($entry)
        if ($raw -match "`r`n") {
            [IO.File]::WriteAllText($entry, ($raw -replace "`r`n", "`n"))
            Write-Host 'Normalized flowsint-api/entrypoint.sh to LF (fixes Docker exec format error)' -ForegroundColor Green
        }
    }

    Write-Host ''
    Write-Host 'Next: scripts/start-flowsint.ps1  (first build may take 10-20 min)' -ForegroundColor Yellow
    Write-Host 'UI: http://localhost:5173  |  Register at /register' -ForegroundColor DarkGray
}
finally {
    Pop-Location
}
