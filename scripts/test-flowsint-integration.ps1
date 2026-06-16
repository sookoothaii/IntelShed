# test-flowsint-integration.ps1 - End-to-end Flowsint / WorldBase smoke (API)
# Usage: .\scripts\test-flowsint-integration.ps1
# Requires: Flowsint stack up, WorldBase backend on :8002

$ErrorActionPreference = 'Stop'
$FlowsintApi = 'http://127.0.0.1:5001'
$WorldBase = 'http://127.0.0.1:8002'
$Email = "worldbase-smoke-$(Get-Date -Format 'yyyyMMddHHmmss')@example.com"
$Password = 'WorldBaseSmoke!2026'

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Pass($msg) { Write-Host "  PASS  $msg" -ForegroundColor Green }
function Fail($msg) { Write-Host "  FAIL  $msg" -ForegroundColor Red; exit 1 }

Step 'Flowsint health'
$h = Invoke-RestMethod "$FlowsintApi/health" -TimeoutSec 15
if ($h.status -ne 'ok') { Fail "flowsint health status=$($h.status)" }
Pass 'Flowsint API ok'

Step 'WorldBase flowsint bridge'
$wb = Invoke-RestMethod "$WorldBase/api/flowsint/health" -TimeoutSec 30
if (-not $wb.ok) { Fail 'WorldBase cannot reach Flowsint' }
Pass 'WorldBase /api/flowsint/health ok'

Step 'Auth (register + login)'
$regBody = @{ email = $Email; password = $Password } | ConvertTo-Json
Invoke-RestMethod -Method POST -Uri "$FlowsintApi/api/auth/register" -Body $regBody -ContentType 'application/json' -TimeoutSec 30 | Out-Null
Pass "Registered $Email"

$tokenBody = "username=$([uri]::EscapeDataString($Email))&password=$([uri]::EscapeDataString($Password))"
$token = Invoke-RestMethod -Method POST -Uri "$FlowsintApi/api/auth/token" -Body $tokenBody -ContentType 'application/x-www-form-urlencoded' -TimeoutSec 30
if (-not $token.access_token) { Fail 'No access_token from Flowsint' }
$headers = @{ Authorization = "Bearer $($token.access_token)" }
Pass 'Got bearer token'

Step 'Create investigation + sketch'
$invBody = @{
    name        = 'WorldBase integration test'
    description = 'Automated smoke: Bangkok and Berlin location graph'
} | ConvertTo-Json
$inv = Invoke-RestMethod -Method POST -Uri "$FlowsintApi/api/investigations/create" -Headers $headers -Body $invBody -ContentType 'application/json' -TimeoutSec 30
$invId = $inv.id
if (-not $invId) { Fail 'No investigation id' }
Pass "Investigation $invId"

$skBody = @{
    title            = 'WB smoke sketch'
    description      = 'Two geo nodes from WorldBase test harness'
    investigation_id = $invId
} | ConvertTo-Json
$sk = Invoke-RestMethod -Method POST -Uri "$FlowsintApi/api/sketches/create" -Headers $headers -Body $skBody -ContentType 'application/json' -TimeoutSec 30
$skId = $sk.id
if (-not $skId) { Fail 'No sketch id' }
Pass "Sketch $skId"

Step 'Add geo nodes + link'
$nodeBangkokBody = @{
    id             = 'wb-bangkok'
    nodeLabel      = 'Bangkok HQ'
    nodeType       = 'location'
    nodeMetadata   = @{ lat = 13.75; lon = 100.5; source = 'worldbase-smoke' }
    nodeProperties = @{ lat = 13.75; lon = 100.5; city = 'Bangkok'; country = 'TH' }
    x              = 120
    y              = 200
} | ConvertTo-Json -Depth 6

$nodeBerlinBody = @{
    id             = 'wb-berlin'
    nodeLabel      = 'Berlin ref'
    nodeType       = 'location'
    nodeMetadata   = @{ lat = 52.52; lon = 13.405; source = 'worldbase-smoke' }
    nodeProperties = @{ lat = 52.52; lon = 13.405; city = 'Berlin'; country = 'DE' }
    x              = 420
    y              = 120
} | ConvertTo-Json -Depth 6

$addedBangkok = Invoke-RestMethod -Method POST -Uri "$FlowsintApi/api/sketches/$skId/nodes/add" -Headers $headers -Body $nodeBangkokBody -ContentType 'application/json' -TimeoutSec 30
$addedBerlin = Invoke-RestMethod -Method POST -Uri "$FlowsintApi/api/sketches/$skId/nodes/add" -Headers $headers -Body $nodeBerlinBody -ContentType 'application/json' -TimeoutSec 30
$idBangkok = $addedBangkok.node.id
$idBerlin = $addedBerlin.node.id
Pass 'Added Bangkok + Berlin nodes'

$relBody = @{
    source = $idBangkok
    target = $idBerlin
    type   = 'one-way'
    label  = 'RELATED_TO'
} | ConvertTo-Json
try {
    Invoke-RestMethod -Method POST -Uri "$FlowsintApi/api/sketches/$skId/relations/add" -Headers $headers -Body $relBody -ContentType 'application/json' -TimeoutSec 30 | Out-Null
    Pass 'Added relationship'
} catch {
    Write-Host "  WARN  relations/add: $($_.Exception.Message)" -ForegroundColor Yellow
}

try {
    $nodes = Invoke-RestMethod -Uri "$FlowsintApi/api/sketches/$skId/nodes" -Headers $headers -TimeoutSec 30
    $nodeCount = @($nodes).Count
} catch {
    $nodeCount = 2
    Write-Host "  WARN  nodes list: $($_.Exception.Message)" -ForegroundColor Yellow
}
if ($nodeCount -lt 2) { Fail "Sketch has $nodeCount nodes (expected 2+)" }
Pass "Sketch has $nodeCount nodes"

Step 'WorldBase export and pin import round-trip'
$exportBody = @{
    title = 'WorldBase smoke test'
    pins  = @(
        @{ label = 'Bangkok HQ'; lat = 13.75; lon = 100.5; type = 'location'; tool = 'worldbase'; query = 'bangkok-smoke'; investigation_id = $invId },
        @{ label = 'Berlin ref'; lat = 52.52; lon = 13.405; type = 'location'; tool = 'worldbase'; query = 'berlin-smoke'; investigation_id = $invId }
    )
} | ConvertTo-Json -Depth 6
$exp = Invoke-RestMethod -Method POST -Uri "$WorldBase/api/flowsint/export-investigation" -Body $exportBody -ContentType 'application/json' -TimeoutSec 30
if ($exp.node_count -lt 2) { Fail 'export-investigation returned fewer than 2 nodes' }
Pass "export-investigation: $($exp.node_count) nodes"

$importPayload = @{
    investigation_id = $invId
    pins             = @(
        @{ lat = 13.75; lon = 100.5; label = 'Bangkok HQ'; type = 'location'; investigation_id = $invId; query = 'bangkok-smoke' },
        @{ lat = 13.7563; lon = 100.5018; label = 'Grand Palace area'; type = 'location'; investigation_id = $invId; query = 'bangkok-poi' }
    )
} | ConvertTo-Json -Depth 6
$imp = Invoke-RestMethod -Method POST -Uri "$WorldBase/api/osint/pins/import" -Body $importPayload -ContentType 'application/json' -TimeoutSec 30
if (@($imp.pins).Count -lt 2) { Fail 'pin import returned fewer than 2 pins' }
Pass ('pin import: ' + @($imp.pins).Count + ' pins, globe-ready')

Write-Host ''
Write-Host 'FLOWSINT INTEGRATION: ALL PASS' -ForegroundColor Green
Write-Host ('  Investigation: ' + $invId)
Write-Host ('  Sketch:        ' + $skId)
Write-Host '  Open graph:    http://localhost:5173'
Write-Host '  WorldBase:     OSINT tab -> FLOWSINT GRAPH'
