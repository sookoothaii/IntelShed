# WorldBase Windows Starter (Docker-free)
# Requires: Python 3.11+, Node.js 20+, Ollama (optional)
$ErrorActionPreference = 'Stop'

$host.ui.RawUI.WindowTitle = 'WorldBase Starter'

Write-Host ''
Write-Host '=====================================' -ForegroundColor Cyan
Write-Host '  WORLDBASE — Spatial Workstation' -ForegroundColor Cyan
Write-Host '=====================================' -ForegroundColor Cyan
Write-Host ''

# Check Python
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host 'ERROR: Python not found. Install from https://python.org' -ForegroundColor Red
    exit 1
}
Write-Host 'Python: ' -NoNewline
Write-Host $py.Source -ForegroundColor Green

# Check Node
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    Write-Host 'ERROR: Node.js not found. Install from https://nodejs.org' -ForegroundColor Red
    exit 1
}
Write-Host 'Node:   ' -NoNewline
Write-Host $node.Source -ForegroundColor Green

# Ollama status
Write-Host 'Ollama: ' -NoNewline
try {
    $r = Invoke-RestMethod -Uri 'http://localhost:11434/api/tags' -TimeoutSec 2
    $count = $r.models.Count
    $msg = 'running ({0} models)' -f $count
    Write-Host $msg -ForegroundColor Green
} catch {
    Write-Host 'not running (install from ollama.com)' -ForegroundColor Yellow
}

# Backend
Write-Host ''
Write-Host '[1/3] Backend setup...' -ForegroundColor Cyan
$backendPath = Join-Path $PSScriptRoot 'backend'
Set-Location $backendPath

if (-not (Test-Path 'venv')) {
    Write-Host '  Creating venv...' -ForegroundColor DarkGray
    python -m venv venv
}

.\venv\Scripts\Activate.ps1
Write-Host '  Installing dependencies...' -ForegroundColor DarkGray
pip install -q -r requirements.txt

# Init DB if missing
if (-not (Test-Path 'worldbase.db')) {
    Write-Host '  Initializing SQLite DB...' -ForegroundColor DarkGray
    python -c 'from main import init_db; init_db()'
}

Write-Host '  Starting uvicorn on :8000...' -ForegroundColor DarkGray
Start-Process powershell -ArgumentList '-NoExit', '-Command', '.\venv\Scripts\Activate.ps1; uvicorn main:app --host 0.0.0.0 --port 8000 --reload'

Set-Location $PSScriptRoot

# Frontend
Write-Host ''
Write-Host '[2/3] Frontend setup...' -ForegroundColor Cyan
$frontendPath = Join-Path $PSScriptRoot 'frontend'
Set-Location $frontendPath

if (-not (Test-Path 'node_modules')) {
    Write-Host '  npm install...' -ForegroundColor DarkGray
    npm install
}

Write-Host '  Starting Vite on :5173...' -ForegroundColor DarkGray
Start-Process powershell -ArgumentList '-NoExit', '-Command', 'npm run dev'

Set-Location $PSScriptRoot

# Summary
Write-Host ''
Write-Host '=====================================' -ForegroundColor Cyan
Write-Host '  WorldBase is starting...' -ForegroundColor Cyan
Write-Host '=====================================' -ForegroundColor Cyan
Write-Host ''
Write-Host '  Frontend:  http://localhost:5173' -ForegroundColor Green
Write-Host '  Backend:   http://localhost:8000' -ForegroundColor Green
Write-Host '  API Docs:  http://localhost:8000/docs' -ForegroundColor Green
Write-Host '  Ollama:    http://localhost:11434' -ForegroundColor Green
Write-Host ''
Write-Host '  Press Ctrl+C in the terminal windows to stop.' -ForegroundColor DarkGray
Write-Host ''
