# Install WorldBase git hooks via pre-commit framework
# Run from repo root: .\scripts\install-hooks.ps1
# Requires: pip install pre-commit (or pip install -r backend/requirements-dev.txt)

$root = git rev-parse --show-toplevel 2>$null
if (-not $root) {
    Write-Host "Not in a git repository." -ForegroundColor Red
    exit 1
}

# Remove old manual hook if present
$oldHook = Join-Path $root ".git\hooks\pre-commit"
if (Test-Path $oldHook) {
    $content = Get-Content $oldHook -Raw -ErrorAction SilentlyContinue
    if ($content -match "pre-commit\.ps1|pwsh") {
        Remove-Item $oldHook -Force
        Write-Host "Removed old manual pre-commit hook." -ForegroundColor Yellow
    }
}

Push-Location $root
try {
    pre-commit install
    if ($LASTEXITCODE -eq 0) {
        Write-Host "pre-commit hooks installed successfully." -ForegroundColor Green
        Write-Host "Run 'pre-commit run --all-files' to check the entire codebase."
    } else {
        Write-Host "pre-commit install failed. Ensure 'pip install pre-commit' has been run." -ForegroundColor Red
        exit 1
    }
} finally {
    Pop-Location
}
