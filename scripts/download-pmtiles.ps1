# Download / build free Protomaps PMTiles (ODbL). No purchase required.
#
# Recommended for Thailand + world (powerful PC):
#   .\scripts\download-pmtiles.ps1 -Region stack      # world z6 (~60 MB) + Thailand detail
#   .\scripts\download-pmtiles.ps1 -Region world-z10  # global z0-10 (~1 GB)
#   .\scripts\download-pmtiles.ps1 -Region world-full -Force   # full planet ~130 GB
#
# Then: .\scripts\start-pmtiles-serve.ps1

param(
    [ValidateSet("sample", "z6", "world-z6", "world-z10", "world-full", "thailand", "asean", "germany", "stack")]
    [string]$Region = "stack",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$destDir = Join-Path $root "data\pmtiles"
$toolsDir = Join-Path $root "tools\pmtiles"
New-Item -ItemType Directory -Force -Path $destDir | Out-Null

# Refresh at maps.protomaps.com/builds if this 404s
$PlanetBuild = "https://build.protomaps.com/20260604.pmtiles"

$Regions = @{
    thailand = @{ File = "thailand.pmtiles"; Bbox = "97.3,5.6,105.6,20.5"; MaxZoom = 14 }
    asean    = @{ File = "asean.pmtiles";    Bbox = "92.0,-11.0,141.0,28.5"; MaxZoom = 12 }
    germany  = @{ File = "germany.pmtiles";  Bbox = "5.8,47.2,15.0,55.1";   MaxZoom = 14 }
}

function Get-PmtilesCli {
    $cmd = Get-Command pmtiles -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $local = Join-Path $toolsDir "pmtiles.exe"
    if (Test-Path $local) { return $local }

    Write-Host "Installing pmtiles CLI to $toolsDir ..." -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/protomaps/go-pmtiles/releases/latest" -Headers @{ "User-Agent" = "WorldBase" }
    $asset = $rel.assets | Where-Object { $_.name -match "Windows_x86_64\.zip$" } | Select-Object -First 1
    if (-not $asset) { throw "No Windows pmtiles release asset found." }
    $zip = Join-Path $env:TEMP "go-pmtiles.zip"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $toolsDir -Force
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    $exe = Get-ChildItem -Path $toolsDir -Recurse -Filter "pmtiles.exe" | Select-Object -First 1
    if (-not $exe) { throw "pmtiles.exe not found after extract." }
    return $exe.FullName
}

function Invoke-Extract {
    param([string]$Out, [string]$Bbox = "", [int]$MaxZoom = 6)
    $cli = Get-PmtilesCli
    if (Test-Path $Out) {
        Write-Host "Skip (exists): $Out" -ForegroundColor Yellow
        return
    }
    Write-Host "Extract -> $Out" -ForegroundColor Cyan
    Write-Host "Source: $PlanetBuild" -ForegroundColor DarkGray
    if ($Bbox) {
        & $cli extract $PlanetBuild $Out --bbox=$Bbox --maxzoom=$MaxZoom
    } else {
        & $cli extract $PlanetBuild $Out --maxzoom=$MaxZoom
    }
    if ($LASTEXITCODE -ne 0) { throw "pmtiles extract failed (exit $LASTEXITCODE)" }
}

function Invoke-PlanetDownload {
    param([string]$Out)
    if (Test-Path $Out) {
        Write-Host "Already exists: $Out" -ForegroundColor Yellow
        return
    }
    $gb = 136
    $free = (Get-PSDrive -Name ($Out.Substring(0,1))).Free / 1GB
    Write-Host "Full planet download: ~${gb} GB (free disk on drive: $([math]::Round($free,1)) GB)" -ForegroundColor Yellow
    if ($free -lt ($gb + 20)) {
        throw "Not enough free disk space. Need ~$($gb + 20) GB. Use -Region world-z10 or stack instead."
    }
    if (-not $Force) {
        throw "Full planet is ~130 GB. Re-run with -Force to confirm: .\scripts\download-pmtiles.ps1 -Region world-full -Force"
    }
    Write-Host "Downloading full planet (resumable BITS)..." -ForegroundColor Cyan
    Start-BitsTransfer -Source $PlanetBuild -Destination $Out -DisplayName "Protomaps Planet" -Description "WorldBase offline basemap"
}

function Write-Manifest {
    $files = Get-ChildItem $destDir -Filter "*.pmtiles" | ForEach-Object {
        @{ name = $_.Name; path = $_.FullName; size_mb = [math]::Round($_.Length / 1MB, 1) }
    }
    $manifest = @{
        updated = (Get-Date).ToUniversalTime().ToString("o")
        files = $files
        serve = ".\scripts\start-pmtiles-serve.ps1"
        tile_url = "http://127.0.0.1:8088/{name}/{z}/{x}/{y}.mvt"
    }
    $manifest | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $destDir "manifest.json") -Encoding UTF8
}

$out = $null
switch ($Region) {
    "sample" {
        $url = "https://r2-public.protomaps.com/protomaps-sample-datasets/cb_2018_us_zcta510_500k.pmtiles"
        $out = Join-Path $destDir "protomaps-sample-us-zcta.pmtiles"
        if (-not (Test-Path $out)) {
            Write-Host "Downloading sample (~20 MB)..." -ForegroundColor Cyan
            Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing
        }
    }
    { $_ -in "z6", "world-z6" } {
        $out = Join-Path $destDir "planet_z6.pmtiles"
        Invoke-Extract -Out $out -MaxZoom 6
    }
    "world-z10" {
        $out = Join-Path $destDir "planet_z10.pmtiles"
        Write-Host "Global z0-10 (~1 GB estimated, streams from Protomaps)..." -ForegroundColor Cyan
        Invoke-Extract -Out $out -MaxZoom 10
    }
    "world-full" {
        $out = Join-Path $destDir "planet_full.pmtiles"
        Invoke-PlanetDownload -Out $out
    }
    { $_ -in "thailand", "asean", "germany" } {
        $r = $Regions[$Region]
        $out = Join-Path $destDir $r.File
        Invoke-Extract -Out $out -Bbox $r.Bbox -MaxZoom $r.MaxZoom
    }
    "stack" {
        Write-Host "Stack: global overview (z6) + Thailand detail (z14)" -ForegroundColor Green
        Invoke-Extract -Out (Join-Path $destDir "planet_z6.pmtiles") -MaxZoom 6
        $r = $Regions["thailand"]
        Invoke-Extract -Out (Join-Path $destDir $r.File) -Bbox $r.Bbox -MaxZoom $r.MaxZoom
        $out = Join-Path $destDir "planet_z6.pmtiles"
    }
}

Write-Manifest
if ($out -and (Test-Path $out)) {
    $mb = [math]::Round((Get-Item $out).Length / 1MB, 1)
    Write-Host "Done. Last artifact: $mb MB" -ForegroundColor Green
}
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. .\scripts\start-pmtiles-serve.ps1"
Write-Host "  2. backend/.env -> PMTILES_SERVE_URL=http://127.0.0.1:8088"
Write-Host "  3. Optional full world later: .\scripts\download-pmtiles.ps1 -Region world-z10"
