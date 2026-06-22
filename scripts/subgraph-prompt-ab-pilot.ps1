# B-05 — subgraph prompt A/B pilot (flat INTEL ENTITIES vs INTEL SUBGRAPH)
# Offline fixtures or live briefing intel metrics comparison (no second LLM run).

param(
    [switch]$Live,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"

Push-Location -LiteralPath $backend
try {
    $args = @("subgraph_prompt_ground_truth.py")
    if ($Live) { $args += "--live" }
    else { $args += "--fixtures" }
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
