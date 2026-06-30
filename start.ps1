# intelshed Windows Starter
# Kills alte Prozesse, startet Backend + Frontend frisch
# Paths with spaces (e.g. D:\MCP Mods\worldbase) are handled via -LiteralPath / WorkingDirectory
param(
    [switch]$SkipSmoke
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot
$BackendUrl = 'http://127.0.0.1:8002'

function Start-LoggedPowerShell {
    param(
        [string]$Title,
        [string]$WorkingDirectory,
        [string]$Command
    )
    $escapedDir = $WorkingDirectory.Replace("'", "''")
    $fullCommand = "Set-Location -LiteralPath '$escapedDir'; $Command"
    Start-Process -FilePath 'powershell.exe' -WindowStyle Normal -ArgumentList @(
        '-NoExit',
        '-ExecutionPolicy', 'Bypass',
        '-Command', $fullCommand
    ) | Out-Null
    Write-Host "  Started: $Title" -ForegroundColor Green
}

function Stop-OldWorldBaseJobs {
    $py = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'uvicorn\s+main:app' }
    foreach ($p in $py) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    $node = Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'vite' }
    foreach ($p in $node) {
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Test-BackendReady {
    try {
        $r = Invoke-RestMethod -Uri "$BackendUrl/api/health/ping" -TimeoutSec 4
        return ($r.status -eq 'ok')
    } catch {
        return $false
    }
}

function Wait-BackendReady {
    param(
        [int]$MaxAttempts = 30,
        [int]$SleepSec = 2
    )
    Write-Host "  Waiting for backend ($BackendUrl/api/health/ping)..." -ForegroundColor DarkGray
    foreach ($i in 1..$MaxAttempts) {
        if (Test-BackendReady) {
            Write-Host "  Backend ready (${i}s)." -ForegroundColor Green
            return $true
        }
        Start-Sleep -Seconds $SleepSec
    }
    Write-Host '  Backend not ready — check the Backend :8002 window for errors.' -ForegroundColor Yellow
    return $false
}

Write-Host ''
Write-Host '=====================================' -ForegroundColor Cyan
Write-Host '  WORLDBASE' -ForegroundColor Cyan
Write-Host '=====================================' -ForegroundColor Cyan
Write-Host ''

# Kill alte Prozesse
Write-Host '[0/4] Cleaning up...' -ForegroundColor Yellow
Stop-OldWorldBaseJobs
Start-Sleep 2

# Backend
Write-Host '[1/4] Backend...' -ForegroundColor Cyan
$backendPath = Join-Path $Root 'backend'
$venvPython = Join-Path $backendPath 'venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host '  venv not found. Run in backend: python -m venv venv' -ForegroundColor Red
    exit 1
}

if (-not (Test-Path -LiteralPath (Join-Path $backendPath 'worldbase.db'))) {
    Write-Host '  Init DB...' -ForegroundColor DarkGray
    Push-Location -LiteralPath $backendPath
    & $venvPython -c 'from main import init_db; init_db()'
    Pop-Location
}

$bindHost = '127.0.0.1'
$envFile = Join-Path $backendPath '.env'
if (Test-Path -LiteralPath $envFile) {
    Get-Content -LiteralPath $envFile | ForEach-Object {
        if ($_ -match '^\s*WORLDBASE_BIND_HOST\s*=\s*(.+)\s*$') {
            $bindHost = $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
}

$py = $venvPython.Replace("'", "''")
# Exclude SQLite/DuckDB runtime files — RAG + briefing writes trigger reload storms otherwise.
$uvicornArgs = @(
    '-m', 'uvicorn', 'main:app',
    '--host', $bindHost,
    '--port', '8002',
    '--reload',
    '--reload-exclude', 'worldbase.db',
    '--reload-exclude', 'worldbase.db-wal',
    '--reload-exclude', 'worldbase.db-shm',
    '--reload-exclude', 'data/entities.duckdb',
    '--reload-exclude', 'data/entities.duckdb.wal',
    '--reload-exclude', 'data/ais_trajectory.db',
    '--reload-exclude', 'data/ais_trajectory.db-wal',
    '--reload-exclude', 'data/ais_trajectory.db-shm',
    '--reload-exclude', 'data/intel_subgraph_latest.json',
    '--reload-exclude', 'data/tle/active.tle'
) -join ' '
Start-LoggedPowerShell -Title 'Backend :8002' -WorkingDirectory $backendPath -Command (
    "& '$py' $uvicornArgs"
)

$backendReady = Wait-BackendReady
if (-not $backendReady) {
    Write-Host '  Continuing anyway — Vite proxy will fail until backend is up.' -ForegroundColor Yellow
}

# Frontend — only after backend warm-up (avoids ECONNREFUSED on first HUD load)
Write-Host '[2/4] Frontend...' -ForegroundColor Cyan
$frontendPath = Join-Path $Root 'frontend'
if (-not (Test-Path -LiteralPath (Join-Path $frontendPath 'node_modules'))) {
    Write-Host '  npm install...' -ForegroundColor DarkGray
    Push-Location -LiteralPath $frontendPath
    npm install
    Pop-Location
}

Start-LoggedPowerShell -Title 'Frontend :5176' -WorkingDirectory $frontendPath -Command 'npm run dev -- --port 5176'
Start-Sleep 3

if (-not $SkipSmoke) {
    Write-Host '[3/4] Smoke test...' -ForegroundColor Cyan
    if ($backendReady -or (Wait-BackendReady -MaxAttempts 5 -SleepSec 2)) {
        $smoke = Join-Path $Root 'scripts\smoke-test.ps1'
        & $smoke
        if ($LASTEXITCODE -ne 0) {
            Write-Host '  Smoke test failed - stack is running; fix before release.' -ForegroundColor Yellow
        }
    } else {
        Write-Host '  Backend not ready - skip smoke (run .\scripts\smoke-test.ps1 manually)' -ForegroundColor Yellow
    }
} else {
    Write-Host '[3/4] Smoke test skipped (-SkipSmoke)' -ForegroundColor DarkGray
}

# Browser
Write-Host '[4/4] Browser...' -ForegroundColor Cyan
Start-Process 'http://localhost:5176'

Write-Host ''
Write-Host '=====================================' -ForegroundColor Green
Write-Host '  RUNNING' -ForegroundColor Green
Write-Host '=====================================' -ForegroundColor Green
Write-Host '  http://localhost:5176' -ForegroundColor Green
Write-Host '  http://localhost:8002/docs' -ForegroundColor Green
Write-Host ''
Write-Host "  Backend bind: $bindHost" -ForegroundColor DarkGray
Write-Host '  Tip: if Vite shows proxy ECONNREFUSED, backend is still starting or reloading.' -ForegroundColor DarkGray
Write-Host '  Security: .\scripts\pc-security-audit.ps1' -ForegroundColor DarkGray
Write-Host ''
