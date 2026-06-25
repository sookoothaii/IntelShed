#!/usr/bin/env pwsh
# WorldBase pre-commit hook — runs ruff (backend) + tsc (frontend) before commit.
# Install: copy this file to .git/hooks/pre-commit (or run scripts/install-hooks.ps1)

$root = git rev-parse --show-toplevel 2>$null
if (-not $root) {
    Write-Host "Not in a git repository — skipping pre-commit checks."
    exit 0
}

$exitCode = 0

# --- Backend: ruff check ---
$backendDir = Join-Path $root "backend"
if (Test-Path $backendDir) {
    Push-Location $backendDir
    try {
        $result = python -m ruff check . 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[pre-commit] ruff check FAILED:" -ForegroundColor Red
            Write-Host $result
            $exitCode = 1
        } else {
            Write-Host "[pre-commit] ruff check OK" -ForegroundColor Green
        }
    } catch {
        Write-Host "[pre-commit] ruff not installed — skipping backend lint." -ForegroundColor Yellow
    }
    Pop-Location
}

# --- Frontend: tsc --noEmit ---
$frontendDir = Join-Path $root "frontend"
if (Test-Path (Join-Path $frontendDir "node_modules")) {
    Push-Location $frontendDir
    try {
        npx tsc --noEmit 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[pre-commit] tsc type-check FAILED" -ForegroundColor Red
            $exitCode = 1
        } else {
            Write-Host "[pre-commit] tsc type-check OK" -ForegroundColor Green
        }
    } catch {
        Write-Host "[pre-commit] tsc not available — skipping frontend type-check." -ForegroundColor Yellow
    }
    Pop-Location
} else {
    Write-Host "[pre-commit] frontend/node_modules not found — skipping frontend checks." -ForegroundColor Yellow
}

if ($exitCode -ne 0) {
    Write-Host "[pre-commit] Checks FAILED — commit aborted." -ForegroundColor Red
} else {
    Write-Host "[pre-commit] All checks passed." -ForegroundColor Green
}
exit $exitCode
