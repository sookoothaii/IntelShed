# pc-security-audit.ps1 — Lenovo Legion / WorldBase security posture check

$ErrorActionPreference = 'Continue'
$Root = Split-Path $PSScriptRoot -Parent
$issues = @()
$ok = @()

function Add-Issue($sev, $msg) { $script:issues += "[$sev] $msg" }
function Add-Ok($msg) { $script:ok += $msg }

Write-Host '=== WorldBase PC Security Audit ===' -ForegroundColor Cyan
Write-Host "Host: $env:COMPUTERNAME  $(Get-Date -Format o)"
Write-Host ''

# .env secrets
$envPath = Join-Path $Root 'backend\.env'
if (Test-Path $envPath) {
    $envText = Get-Content $envPath -Raw
    if ($envText -match 'NODE_INGEST_TOKEN=\s*$' -or $envText -notmatch 'NODE_INGEST_TOKEN=') {
        Add-Issue 'HIGH' 'NODE_INGEST_TOKEN not set — Pi/node API open if backend listens on LAN'
    } else {
        Add-Ok 'NODE_INGEST_TOKEN configured'
    }
    foreach ($pat in @('sk-', 'api_key', 'password=', 'secret=')) {
        if ($envText -match $pat) { Add-Ok "backend/.env exists (review for leaked $pat in git)" }
    }
} else {
    Add-Issue 'MED' 'backend/.env missing — copy from .env.example'
}

# Git tracked secrets
$gitEnv = git -C $Root ls-files backend/.env 2>$null
if ($gitEnv) { Add-Issue 'CRITICAL' 'backend/.env is tracked by git — remove immediately' }

# Listening ports
try {
    $listeners = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalAddress -notin @('::', '::1') -or $_.LocalPort -in 8002, 5173, 5176, 5001, 5173 } |
        Select-Object LocalAddress, LocalPort -Unique
    $ports = $listeners | ForEach-Object { "$($_.LocalAddress):$($_.LocalPort)" }
    Write-Host 'Listening (sample):' ($ports | Select-Object -First 20) -join ', '
    foreach ($p in @(8002, 5001, 6379, 5433, 7474)) {
        $any = $listeners | Where-Object { $_.LocalPort -eq $p -and $_.LocalAddress -eq '0.0.0.0' }
        if ($any) { Add-Issue 'MED' "Port $p bound to 0.0.0.0 (LAN/WAN reachable)" }
    }
} catch {
    Add-Issue 'LOW' 'Could not enumerate TCP listeners'
}

# Docker
if (Get-Command docker -ErrorAction SilentlyContinue) {
    try {
        $ps = docker ps --format '{{.Names}} {{.Ports}}' 2>$null
        if ($ps) {
            Write-Host ''
            Write-Host 'Docker:' -ForegroundColor DarkGray
            $ps | ForEach-Object { Write-Host "  $_" }
        }
    } catch {}
}

# Firewall (Windows)
try {
    $fw = Get-NetFirewallProfile | Select-Object Name, Enabled
    foreach ($f in $fw) {
        if (-not $f.Enabled) { Add-Issue 'MED' "Windows Firewall profile $($f.Name) disabled" }
        else { Add-Ok "Firewall $($f.Name) on" }
    }
} catch {}

# Flowsint / WorldBase health
foreach ($url in @(
    'http://127.0.0.1:8002/api/health',
    'http://127.0.0.1:8002/api/flowsint/health'
)) {
    try {
        $r = Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 4
        Add-Ok "$url -> $($r.StatusCode)"
    } catch {
        Add-Issue 'LOW' "$url unreachable (service down?)"
    }
}

Write-Host ''
Write-Host '--- OK ---' -ForegroundColor Green
$ok | ForEach-Object { Write-Host "  $_" }
Write-Host ''
Write-Host '--- FINDINGS ---' -ForegroundColor $(if ($issues.Count) { 'Yellow' } else { 'Green' })
if (-not $issues.Count) {
    Write-Host '  No automated findings.' -ForegroundColor Green
} else {
    $issues | ForEach-Object { Write-Host "  $_" }
}
Write-Host ''
Write-Host 'Pi checklist: offgrid security-harden, portal auth, mqtt-harden — see LLM_HANDOFF.md' -ForegroundColor DarkGray
