# B-04 — corroboration ground-truth pilot (offline fixtures or live briefing meta)

param(
    [switch]$Live,
    [switch]$Json,
    [string]$ApiBase = "http://127.0.0.1:8002"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"

Push-Location -LiteralPath $backend
try {
    $args = @("corroboration_ground_truth.py")
    if ($Live) { $args += "--live" } else { $args += "--fixtures" }
    if ($Json) { $args += "--json" }
    if ($ApiBase) { $args += @("--api-base", $ApiBase) }

    if (Test-Path -LiteralPath ".\venv\Scripts\python.exe") {
        & ".\venv\Scripts\python.exe" @args
    } else {
        python @args
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}
