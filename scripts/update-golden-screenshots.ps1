<#
.SYNOPSIS
  Regenerate Playwright golden screenshots for visual regression tests (E-05).

.DESCRIPTION
  Runs `npx playwright test visual.spec.ts --update-snapshots` from the frontend dir.
  Prerequisites: dev server running (npm run dev) or Playwright webServer auto-start.

.PARAMETER KeepServer
  If set, don't kill the dev server after tests (useful when running other e2e after).
#>

param(
  [switch]$KeepServer
)

$ErrorActionPreference = 'Stop'
$FrontendDir = Join-Path $PSScriptRoot '..\frontend'
$FrontendDir = (Resolve-Path $FrontendDir).Path

Write-Host "[update-golden-screenshots] Regenerating baselines in $FrontendDir" -ForegroundColor Cyan

Push-Location $FrontendDir
try {
  # Ensure Playwright browsers are installed
  $env:CI = $null  # Don't skip visual tests
  npx playwright test visual.spec.ts --update-snapshots 2>&1 | ForEach-Object {
    Write-Host $_
  }
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    Write-Host "[update-golden-screenshots] Playwright exited with code $exitCode" -ForegroundColor Yellow
    Write-Host "  This is expected if the dev server was not running or Cesium failed to load." -ForegroundColor Yellow
    Write-Host "  Make sure: 1) npm run dev is running on :5176, 2) Cesium Ion token is set in frontend/.env" -ForegroundColor Yellow
  } else {
    Write-Host "[update-golden-screenshots] Baselines updated successfully." -ForegroundColor Green
  }
} finally {
  Pop-Location
}
