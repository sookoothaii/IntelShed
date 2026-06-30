<#
.SYNOPSIS
  intelshed backup — SQLite, DuckDB, subgraph, fusion parquet, .env

.DESCRIPTION
  Creates a timestamped backup of all persistent intelshed data.
  Safe to run while the API is up (uses VACUUM INTO for SQLite, file copy for DuckDB WAL+main).

.PARAMETER OutDir
  Backup destination directory. Default: .\backups\

.PARAMETER IncludeEnv
  Include backend/.env in the backup (contains secrets — handle with care).

.PARAMETER Compress
  Create a .zip archive of the backup folder after copying.

.EXAMPLE
  .\scripts\backup.ps1
  .\scripts\backup.ps1 -OutDir D:\Backups\intelshed -IncludeEnv -Compress
#>
[CmdletBinding()]
param(
    [string]$OutDir = (Join-Path $PSScriptRoot "..\backups"),
    [switch]$IncludeEnv,
    [switch]$Compress
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$Backend    = Join-Path $ProjectRoot "backend"
$Stamp      = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupRoot = Join-Path $OutDir "worldbase-$Stamp"

# --- Resolve data paths -------------------------------------------------------

$DataDir = Join-Path $Backend "data"
$DataFiles = @(
    @{ Path = (Join-Path $Backend "worldbase.db");                       Name = "sqlite-worldbase.db";        Method = "vacuum" }
    @{ Path = (Join-Path $DataDir "entities.duckdb");                    Name = "duckdb-entities.duckdb";     Method = "copy"  }
    @{ Path = (Join-Path $DataDir "entities.duckdb.wal");                Name = "duckdb-entities.duckdb.wal"; Method = "copy"  }
    @{ Path = (Join-Path $DataDir "fusion_events.parquet");              Name = "fusion_events.parquet";      Method = "copy"  }
    @{ Path = (Join-Path $DataDir "intel_subgraph_latest.json");         Name = "intel_subgraph_latest.json"; Method = "copy"  }
)

# .env (secrets)
$EnvFile = Join-Path $Backend ".env"

# TLE directory
$TleDir  = Join-Path $DataDir "tle"

# --- Helpers ------------------------------------------------------------------

function Write-Step([string]$msg) { Write-Host "[backup] $msg" -ForegroundColor Cyan }
function Write-Ok([string]$msg)   { Write-Host "[backup] $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "[backup] $msg" -ForegroundColor Yellow }

function Copy-FileSafe {
    param([string]$Src, [string]$Dst)
    if (-not (Test-Path -LiteralPath $Src)) {
        Write-Warn "SKIP (not found): $Src"
        return $false
    }
    Copy-Item -LiteralPath $Src -Destination $Dst -Force
    $size = (Get-Item -LiteralPath $Dst).Length
    $sizeMB = [math]::Round($size / 1MB, 1)
    $srcName = Split-Path $Src -Leaf
    $dstName = Split-Path $Dst -Leaf
    Write-Ok "OK ($sizeMB MB): $srcName -> $dstName"
    return $true
}

function Backup-SqliteVacuum {
    param([string]$Src, [string]$Dst)
    if (-not (Test-Path -LiteralPath $Src)) {
        Write-Warn "SKIP (not found): $Src"
        return $false
    }
    try {
        # VACUUM INTO creates a clean, consistent snapshot without locking the DB
        # SQLite VACUUM INTO does not support parameter binding — use escaped literal
        $tmpPy = [System.IO.Path]::GetTempFileName() + ".py"
        @"
import sqlite3, sys
src = sys.argv[1]
dst = sys.argv[2].replace("'", "''")
con = sqlite3.connect(src)
con.execute(f"VACUUM INTO '{dst}'")
con.close()
print("OK")
"@ | Set-Content -LiteralPath $tmpPy -Encoding UTF8
        $result = python $tmpPy $Src $Dst 2>&1
        Remove-Item -LiteralPath $tmpPy -Force -ErrorAction SilentlyContinue
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "VACUUM INTO failed, falling back to file copy: $result"
            Copy-FileSafe -Src $Src -Dst $Dst
        } else {
            $size = (Get-Item -LiteralPath $Dst).Length
            $sizeMB = [math]::Round($size / 1MB, 1)
            $srcName = Split-Path $Src -Leaf
            $dstName = Split-Path $Dst -Leaf
            Write-Ok "OK ($sizeMB MB): $srcName -> $dstName (VACUUM INTO)"
        }
        return $true
    } catch {
        Write-Warn "SQLite backup error: $_  - falling back to file copy"
        Copy-FileSafe -Src $Src -Dst $Dst
    }
}

# --- Main ---------------------------------------------------------------------

Write-Step "intelshed Backup - $Stamp"
Write-Step "Output: $BackupRoot"

New-Item -ItemType Directory -Path $BackupRoot -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $BackupRoot "data") -Force | Out-Null

$copied = 0
$skipped = 0

foreach ($entry in $DataFiles) {
    $src = $entry.Path
    $dstName = $entry.Name
    $dataSubDir = Join-Path $BackupRoot "data"
    $dst = if ($dstName -like "duckdb-*" -or $dstName -like "fusion_*" -or $dstName -like "intel_*") {
        Join-Path $dataSubDir $dstName
    } else {
        Join-Path $BackupRoot $dstName
    }
    $dstParent = Split-Path $dst -Parent
    if (-not (Test-Path -LiteralPath $dstParent)) {
        New-Item -ItemType Directory -Path $dstParent -Force | Out-Null
    }

    if ($entry.Method -eq "vacuum") {
        if (Backup-SqliteVacuum -Src $src -Dst $dst) { $copied++ } else { $skipped++ }
    } else {
        if (Copy-FileSafe -Src $src -Dst $dst) { $copied++ } else { $skipped++ }
    }
}

# .env (opt-in)
if ($IncludeEnv) {
    $envDst = Join-Path $BackupRoot ".env"
    if (Copy-FileSafe -Src $EnvFile -Dst $envDst) {
        $copied++
        Write-Warn ".env contains secrets - secure or delete after use!"
    } else {
        $skipped++
    }
} else {
    Write-Step ".env skipped (use -IncludeEnv to include secrets)"
}

# TLE directory
if (Test-Path -LiteralPath $TleDir) {
    $tleFiles = Get-ChildItem -LiteralPath $TleDir -File
    if ($tleFiles.Count -gt 0) {
        $tleDst = Join-Path $dataSubDir "tle"
        New-Item -ItemType Directory -Path $tleDst -Force | Out-Null
        foreach ($f in $tleFiles) {
            Copy-Item -LiteralPath $f.FullName -Destination $tleDst -Force
        }
        $tleCount = $tleFiles.Count
        Write-Ok "OK: TLE data ($tleCount files)"
        $copied++
    } else {
        Write-Step "TLE directory empty - skipping"
    }
}

# Write manifest
$manifest = [PSCustomObject]@{
    timestamp    = $Stamp
    project      = "intelshed"
    backup_dir   = $BackupRoot
    files_copied = $copied
    files_skipped = $skipped
    include_env  = $IncludeEnv.IsPresent
    created_by   = $env:USERNAME
    hostname     = $env:COMPUTERNAME
}
$manifestPath = Join-Path $BackupRoot "manifest.json"
$manifest | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
Write-Ok "Manifest: $manifestPath"

# Compress
if ($Compress) {
    $zipPath = "$BackupRoot.zip"
    Compress-Archive -Path "$BackupRoot\*" -DestinationPath $zipPath -Force
    $zipSize = (Get-Item -LiteralPath $zipPath).Length
    $zipMB = [math]::Round($zipSize / 1MB, 1)
    Write-Ok "ZIP: $zipPath ($zipMB MB)"
    # Optionally remove the uncompressed folder
    Remove-Item -LiteralPath $BackupRoot -Recurse -Force
    Write-Step "Removed uncompressed folder (ZIP retained)"
}

Write-Step "Done - $copied files copied, $skipped skipped"
