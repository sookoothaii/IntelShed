# B-06 — fusion compare baseline progress (snapshots stored vs 7-day target)

param(
    [switch]$Json,
    [string]$ApiBase = "http://127.0.0.1:8002"
)

$ErrorActionPreference = "Stop"
$targetSnapshots = 28  # 7 days x 4 snapshots/day at 6h interval

try {
    $trust = Invoke-RestMethod -Uri "$ApiBase/api/trust" -TimeoutSec 12
} catch {
    Write-Error "API unreachable at $ApiBase — start stack first."
}

$fc = $trust.fusion_compare
if (-not $fc) {
    $fc = @{}
}

$stored = 0
if ($null -ne $fc.snapshots_stored) { $stored = [int]$fc.snapshots_stored }
$available = $false
if ($null -ne $fc.available) { $available = [bool]$fc.available }
$pct = 0.0
if ($targetSnapshots -gt 0) { $pct = [math]::Round(100.0 * $stored / $targetSnapshots, 1) }

$report = [ordered]@{
    snapshots_stored = $stored
    target_snapshots = $targetSnapshots
    progress_pct       = $pct
    compare_available  = $available
    baseline_at        = $fc.baseline_at
    top_delta          = $fc.top_delta
    detail             = $fc.detail
}

if ($Json) {
    $report | ConvertTo-Json -Depth 4
} else {
    Write-Output "Fusion baseline (B-06)"
    Write-Output ("  snapshots_stored={0} / {1} ({2} percent)" -f $stored, $targetSnapshots, $pct)
    Write-Output ("  fusion_compare.available={0}" -f $available)
    if ($fc.detail) { Write-Output ("  detail={0}" -f $fc.detail) }
    if ($available -and $fc.top_delta) {
        Write-Output ("  top_delta={0} delta={1}" -f $fc.top_delta.cell_id, $fc.top_delta.delta_score)
    }
}
