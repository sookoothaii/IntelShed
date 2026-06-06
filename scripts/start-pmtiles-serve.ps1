# Serve all .pmtiles in data/pmtiles as MapLibre-compatible ZXY MVT (localhost only).
# Usage: .\scripts\start-pmtiles-serve.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$destDir = Join-Path $root "data\pmtiles"
$toolsDir = Join-Path $root "tools\pmtiles"
$port = if ($env:PMTILES_PORT) { $env:PMTILES_PORT } else { 8088 }

if (-not (Test-Path $destDir)) {
    throw "No $destDir — run .\scripts\download-pmtiles.ps1 -Region stack first"
}

$cli = Get-Command pmtiles -ErrorAction SilentlyContinue
if (-not $cli) {
    $local = Join-Path $toolsDir "pmtiles.exe"
    if (Test-Path $local) { $cli = @{ Source = $local } }
}
if (-not $cli) {
    throw "pmtiles CLI missing. Run .\scripts\download-pmtiles.ps1 -Region stack (auto-installs CLI)."
}

$names = (Get-ChildItem $destDir -Filter "*.pmtiles").BaseName -join ", "
Write-Host "Serving PMTiles on http://127.0.0.1:${port}/" -ForegroundColor Green
Write-Host "Archives: $names" -ForegroundColor DarkGray
Write-Host "TileJSON: http://127.0.0.1:${port}/planet_z6.json (example)" -ForegroundColor DarkGray
Write-Host "Press Ctrl+C to stop." -ForegroundColor DarkGray

& $cli.Source serve $destDir --port=$port --public-url="http://127.0.0.1:$port" --cors="*"
