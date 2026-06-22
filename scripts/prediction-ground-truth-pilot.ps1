# B-03 — prediction ledger ground-truth pilot
# Offline fixtures (10 cases) or live resolve against current feeds.

param(
    [switch]$Live,
    [switch]$ForceSnapshot,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"

Push-Location -LiteralPath $backend
try {
    $args = @("prediction_ground_truth.py")
    if ($Live) { $args += "--live" }
    else { $args += "--fixtures" }
    if ($ForceSnapshot) { $args += "--force-snapshot" }
    if ($Json) { $args += "--json" }

    if (Test-Path -LiteralPath ".\venv\Scripts\python.exe") {
        & ".\venv\Scripts\python.exe" @args
    } else {
        python @args
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}
