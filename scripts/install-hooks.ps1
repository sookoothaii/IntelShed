# Install WorldBase git hooks
# Run from repo root: .\scripts\install-hooks.ps1

$hookDir = Join-Path (git rev-parse --show-toplevel) ".git\hooks"
if (-not (Test-Path $hookDir)) {
    New-Item -ItemType Directory -Path $hookDir -Force | Out-Null
}

$src = Join-Path $PSScriptRoot "pre-commit.ps1"
$dst = Join-Path $hookDir "pre-commit"

Copy-Item $src $dst -Force
Write-Host "Installed pre-commit hook to $dst"
