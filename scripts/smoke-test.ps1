# WorldBase smoke test - backend APIs, Ollama, Vite proxy, frontend build
# Usage: .\scripts\smoke-test.ps1

$ErrorActionPreference = 'Continue'
$Root = Split-Path $PSScriptRoot -Parent
$Backend = "http://127.0.0.1:8002"
$Frontend = "http://localhost:5176"
$passed = 0
$failed = 0
$warn = 0

function Get-WorldBaseApiKey {
    $envFile = Join-Path $Root 'backend\.env'
    if (-not (Test-Path -LiteralPath $envFile)) { return $null }
    foreach ($line in Get-Content -LiteralPath $envFile) {
        if ($line -match '^\s*WORLDBASE_API_KEY\s*=\s*(.+)\s*$') {
            $val = $Matches[1].Trim().Trim('"').Trim("'")
            if ($val) { return $val }
        }
    }
    return $null
}

$WorldBaseApiKey = Get-WorldBaseApiKey

function Test-Endpoint {
    param(
        [string]$Name,
        [string]$Url,
        [scriptblock]$Assert,
        [int]$TimeoutSec = 30,
        [switch]$Optional
    )
    try {
        $r = Invoke-RestMethod -Uri $Url -TimeoutSec $TimeoutSec
        & $Assert $r
        Write-Host "  PASS  $Name" -ForegroundColor Green
        $script:passed++
    } catch {
        if ($Optional) {
            Write-Host "  WARN  $Name - $($_.Exception.Message)" -ForegroundColor Yellow
            $script:warn++
        } else {
            Write-Host "  FAIL  $Name - $($_.Exception.Message)" -ForegroundColor Red
            $script:failed++
        }
    }
}

Write-Host ""
Write-Host "WORLDBASE SMOKE TEST" -ForegroundColor Cyan
Write-Host "====================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1] Core backend" -ForegroundColor Cyan
Test-Endpoint "health" "$Backend/api/health" {
    param($d)
    if ($d.status -ne 'ok') { throw "status=$($d.status)" }
    if ($d.feed_count -lt 3) { throw "feed_count=$($d.feed_count) too low" }
} -TimeoutSec 120
Test-Endpoint "models (Ollama)" "$Backend/api/models" {
    param($d)
    if ($d.error) { throw $d.error }
    if (-not $d.models -or $d.models.Count -eq 0) { throw "no chat models" }
    if (-not $d.default) { throw "no default model" }
} -TimeoutSec 90
Test-Endpoint "providers" "$Backend/api/providers" {
    param($d); if (-not $d.providers) { throw "empty providers" }
} -TimeoutSec 90
Test-Endpoint "credentials status" "$Backend/api/credentials/status" {
    param($d); if (-not $d.providers) { throw "no providers" }; if ($d.count -lt 10) { throw "catalog too small" }
} -TimeoutSec 15

Write-Host ""
Write-Host "[2] Phase 2 fusion APIs" -ForegroundColor Cyan
Test-Endpoint "stac collections" "$Backend/api/stac/collections" {
    param($d); if (-not $d.regions) { throw "no regions" }
} -TimeoutSec 90
Test-Endpoint "sanctions status" "$Backend/api/sanctions/status" {
    param($d); if ($null -eq $d.index_rows) { throw "no index_rows" }
} -Optional
Test-Endpoint "fusion heatmap" "$Backend/api/fusion/heatmap?cell_deg=2&top=10&include_geojson=0" {
    param($d); if ($null -eq $d.total_points) { throw "no total_points" }
    if (-not $d.cells -or $d.cells.Count -eq 0) { throw "no cells" }
} -TimeoutSec 120
Test-Endpoint "aircraft trails stats" "$Backend/api/aircraft/trails/stats" {
    param($d); if ($null -eq $d.rows) { throw "no rows field" }
}
Test-Endpoint "pmtiles status" "$Backend/api/pmtiles/status" {
    param($d); if ($null -eq $d.available) { throw "no available field" }
}

Write-Host ""
Write-Host "[3] Scientific feeds (provenance + counts)" -ForegroundColor Cyan
Test-Endpoint "wildfires" "$Backend/api/wildfires" {
    param($d)
    if ($null -eq $d.count) { throw "missing count" }
    if (-not $d.updated) { throw "missing updated ISO timestamp" }
    if (-not $d.source -and -not $d.errors) { throw "missing source attribution" }
} -TimeoutSec 90
Test-Endpoint "gdacs" "$Backend/api/gdacs" {
    param($d)
    if ($null -eq $d.count) { throw "missing count" }
    if (-not $d.source) { throw "missing source" }
} -TimeoutSec 90
Test-Endpoint "outages" "$Backend/api/outages?hours=72&limit=20" {
    param($d)
    if ($null -eq $d.count) { throw "missing count" }
    if ($d.sources -notcontains 'ioda') { throw "ioda source missing" }
} -TimeoutSec 90
Test-Endpoint "energy DE globe" "$Backend/api/energy/de/globe" {
    param($d)
    if (-not $d.updated) { throw "missing updated" }
    if (-not $d.source) { throw "missing source" }
    if ($d.points.Count -eq 0 -and -not $d.error -and -not $d.stale) { throw "empty points without error/stale flag" }
} -TimeoutSec 60
Test-Endpoint "pegel" "$Backend/api/pegel" {
    param($d)
    if ($null -eq $d.count) { throw "missing count" }
} -TimeoutSec 60 -Optional

Write-Host ""
Write-Host "[4] Intelligence feeds (sample)" -ForegroundColor Cyan
@(
    @{ n = 'aircraft'; u = '/api/aircraft' },
    @{ n = 'earthquakes'; u = '/api/earthquakes' },
    @{ n = 'situations'; u = '/api/situations' },
    @{ n = 'hazards'; u = '/api/hazards' },
    @{ n = 'memory stats'; u = '/api/memory/stats' },
    @{ n = 'gdelt pulse local'; u = '/api/gdelt/pulse/local' },
    @{ n = 'gdelt geo local'; u = '/api/gdelt/geo/local?timespan=1d&maxrecords=20' }
) | ForEach-Object {
    Test-Endpoint $_.n "$Backend$($_.u)" { param($d) } -TimeoutSec 60 -Optional
}
Test-Endpoint "traffic cams regional" "$Backend/api/traffic/cams?scope=regional" {
    param($d); if ($d.count -lt 1) { throw "no cameras" }
} -TimeoutSec 45 -Optional

Write-Host ""
Write-Host "[5] Vite dev proxy" -ForegroundColor Cyan
Test-Endpoint "proxy /api/health" "$Frontend/api/health" {
    param($d); if ($d.status -ne 'ok') { throw "proxy broken" }
} -TimeoutSec 15
Test-Endpoint "proxy /api/models" "$Frontend/api/models" {
    param($d); if ($d.error) { throw $d.error }
} -TimeoutSec 20

Write-Host ""
Write-Host "[6] Ollama chat (short)" -ForegroundColor Cyan
try {
    $body = @{
        model    = 'qwen3:8b'
        messages = @(@{ role = 'user'; content = 'Antworte nur: OK' })
        stream   = $false
        context  = $false
    } | ConvertTo-Json -Depth 5
    $chatHeaders = @{}
    if ($WorldBaseApiKey) {
        $chatHeaders['X-API-Key'] = $WorldBaseApiKey
    }
    $chat = Invoke-RestMethod -Uri "$Backend/api/chat" -Method Post -Body $body -ContentType 'application/json' -Headers $chatHeaders -TimeoutSec 120
    $reply = $chat.message.content
    if (-not $reply) { throw 'empty reply' }
    Write-Host "  PASS  chat reply: $($reply.Substring(0, [Math]::Min(40, $reply.Length)))" -ForegroundColor Green
    $passed++
} catch {
    Write-Host "  FAIL  chat - $($_.Exception.Message)" -ForegroundColor Red
    $failed++
}

Write-Host ""
Write-Host '[7] Briefing (cached - autopilot fills; skip slow POST)' -ForegroundColor Cyan
Test-Endpoint "briefing latest" "$Backend/api/briefing" {
    param($d)
    if ($null -eq $d.text) { throw 'no text field' }
} -TimeoutSec 15 -Optional

Write-Host ""
Write-Host "[8] Frontend build" -ForegroundColor Cyan
Push-Location (Join-Path $Root 'frontend')
try {
    npm run build 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  PASS  tsc + vite build" -ForegroundColor Green
        $passed++
    } else {
        Write-Host "  FAIL  tsc + vite build (exit $LASTEXITCODE)" -ForegroundColor Red
        $failed++
    }
} catch {
    Write-Host "  FAIL  tsc + vite build - $_" -ForegroundColor Red
    $failed++
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "====================" -ForegroundColor Cyan
$summaryColor = if ($failed -eq 0) { 'Green' } else { 'Red' }
Write-Host "PASS: $passed  FAIL: $failed  WARN: $warn" -ForegroundColor $summaryColor
Write-Host ""
if ($failed -gt 0) { exit 1 }
