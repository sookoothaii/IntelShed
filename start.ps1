# WorldBase Windows Starter
# Kills alte Prozesse, startet Backend + Frontend frisch
# Paths with spaces (e.g. D:\MCP Mods\worldbase) are handled via -LiteralPath / WorkingDirectory
param(
    [switch]$SkipSmoke
)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot

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

Write-Host ''
Write-Host '=====================================' -ForegroundColor Cyan
Write-Host '  WORLDBASE' -ForegroundColor Cyan
Write-Host '=====================================' -ForegroundColor Cyan
Write-Host ''

# Kill alte Prozesse
Write-Host '[0/4] Cleaning up...' -ForegroundColor Yellow
Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*uvicorn*main:app*' } | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process node -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*vite*' } | Stop-Process -Force -ErrorAction SilentlyContinue
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
Start-LoggedPowerShell -Title 'Backend :8002' -WorkingDirectory $backendPath -Command (
    "& '$py' -m uvicorn main:app --host $bindHost --port 8002 --reload"
)
Start-Sleep 3

# Frontend
Write-Host '[2/4] Frontend...' -ForegroundColor Cyan
$frontendPath = Join-Path $Root 'frontend'
if (-not (Test-Path -LiteralPath (Join-Path $frontendPath 'node_modules'))) {
    Write-Host '  npm install...' -ForegroundColor DarkGray
    Push-Location -LiteralPath $frontendPath
    npm install
    Pop-Location
}

Start-LoggedPowerShell -Title 'Frontend :5176' -WorkingDirectory $frontendPath -Command 'npm run dev -- --port 5176'
Start-Sleep 2

if (-not $SkipSmoke) {
    Write-Host '[3/4] Smoke test (backend warm-up ~45s)...' -ForegroundColor Cyan
    $ready = $false
    foreach ($i in 1..18) {
        try {
            $h = Invoke-RestMethod -Uri 'http://127.0.0.1:8002/api/health' -TimeoutSec 5
            if ($h.status -eq 'ok') { $ready = $true; break }
        } catch { }
        Start-Sleep 3
    }
    if ($ready) {
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
Write-Host '  Security: .\scripts\pc-security-audit.ps1' -ForegroundColor DarkGray
Write-Host ''
