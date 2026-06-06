# move-dev-data-to-d.ps1 — Move heavy user folders from C: to D: (junction, rollback on failure)
# Safe default: preview only. Run with -Execute after closing Cursor and Docker Desktop.
#
# Example:
#   .\scripts\move-dev-data-to-d.ps1
#   .\scripts\move-dev-data-to-d.ps1 -Execute
#   .\scripts\move-dev-data-to-d.ps1 -Execute -Only cache
#
param(
    [switch]$Execute,
    [string]$TargetRoot = 'D:\DevData',
    [ValidateSet('cache', 'cursor', 'all')]
    [string]$Only = 'all'
)

$ErrorActionPreference = 'Stop'

function Write-Step([string]$msg, [string]$color = 'Cyan') {
    Write-Host $msg -ForegroundColor $color
}

function Get-FolderSizeBytes([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return 0 }
    $sum = 0L
    Get-ChildItem -LiteralPath $path -Recurse -File -Force -ErrorAction SilentlyContinue | ForEach-Object {
        $sum += $_.Length
    }
    return $sum
}

function Get-SizeGB([long]$Bytes) {
    return [math]::Round($Bytes / 1GB, 2)
}

function Test-PathIsJunction([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { return $false }
    $item = Get-Item -LiteralPath $path -Force
    return ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
}

function Get-JunctionTarget([string]$path) {
    if (-not (Test-PathIsJunction $path)) { return $null }
    $item = Get-Item -LiteralPath $path -Force
    return $item.Target
}

function Test-BlockingProcesses {
    $names = @('Cursor', 'Docker Desktop', 'com.docker.backend')
    $found = @()
    foreach ($n in $names) {
        if (Get-Process -Name $n -ErrorAction SilentlyContinue) { $found += $n }
    }
    return $found
}

function Move-FolderToD {
    param(
        [string]$Source,
        [string]$Dest,
        [bool]$DoExecute
    )

    $srcName = Split-Path $Source -Leaf
    Write-Step "`n--- $srcName ---"

    if (-not (Test-Path -LiteralPath $Source)) {
        Write-Step "Skip: not found ($Source)" 'DarkGray'
        return
    }

    if (Test-PathIsJunction $Source) {
        $t = Get-JunctionTarget $Source
        Write-Step "Already a junction -> $t" 'Green'
        return
    }

    if (Test-Path -LiteralPath $Dest) {
        $destBytes = Get-FolderSizeBytes $Dest
        if ($destBytes -gt 0) {
            throw "Target already exists and is not empty: $Dest ($(Get-SizeGB $destBytes) GB). Resolve manually."
        }
    }

    $bytes = Get-FolderSizeBytes $Source
    Write-Step "Source: $Source ($(Get-SizeGB $bytes) GB)" 'White'
    Write-Step "Target: $Dest"

    if (-not $DoExecute) {
        Write-Step '[Dry-run] Would move folder and create junction at source path.' 'Yellow'
        return
    }

    $parent = Split-Path $Dest -Parent
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    Write-Step 'Moving (may take several minutes)...' 'DarkGray'
    try {
        Move-Item -LiteralPath $Source -Destination $Dest -Force
    } catch {
        throw "Move failed: $_"
    }

    try {
        New-Item -ItemType Junction -Path $Source -Target $Dest -Force | Out-Null
    } catch {
        Write-Step 'Junction failed — rolling back move.' 'Red'
        if (Test-Path -LiteralPath $Source) {
            Remove-Item -LiteralPath $Source -Force -Recurse -ErrorAction SilentlyContinue
        }
        Move-Item -LiteralPath $Dest -Destination $Source -Force
        throw "Junction create failed (rolled back): $_"
    }

    if (-not (Test-PathIsJunction $Source)) {
        throw 'Post-check failed: source is not a junction.'
    }
    $probe = Get-ChildItem -LiteralPath $Source -Force -ErrorAction Stop | Select-Object -First 1
    if ($null -eq $probe) {
        Write-Step 'Junction OK (folder may be empty).' 'Green'
    } else {
        Write-Step 'Junction OK (readable).' 'Green'
    }
}

# --- main ---
Write-Step '=== Move dev data C: -> D: (safe) ==='
Write-Step "Mode: $(if ($Execute) { 'EXECUTE' } else { 'DRY-RUN (add -Execute to apply)' })"

$cFree = (Get-PSDrive -Name C).Free
$dFree = (Get-PSDrive -Name D).Free
Write-Step "C: free $(Get-SizeGB $cFree) GB | D: free $(Get-SizeGB $dFree) GB"

$jobs = @()
if ($Only -eq 'all' -or $Only -eq 'cache') {
    $jobs += @{ Source = Join-Path $env:USERPROFILE '.cache'; Dest = Join-Path $TargetRoot 'cache' }
}
if ($Only -eq 'all' -or $Only -eq 'cursor') {
    $jobs += @{ Source = Join-Path $env:USERPROFILE '.cursor'; Dest = Join-Path $TargetRoot 'cursor' }
}

$needBytes = 0L
foreach ($j in $jobs) {
    if (Test-Path -LiteralPath $j.Source) {
        if (-not (Test-PathIsJunction $j.Source)) {
            $needBytes += Get-FolderSizeBytes $j.Source
        }
    }
}

if ($needBytes -gt 0) {
    $buffer = 5GB
    if ($dFree -lt ($needBytes + $buffer)) {
        throw "D: needs at least $(Get-SizeGB ($needBytes + $buffer)) GB free (data + 5 GB buffer). Have $(Get-SizeGB $dFree) GB."
    }
    Write-Step "Planned move: ~$(Get-SizeGB $needBytes) GB -> under $TargetRoot"
}

$blocking = Test-BlockingProcesses
if ($blocking.Count -gt 0) {
    Write-Step "Close these apps before -Execute: $($blocking -join ', ')" 'Yellow'
    if ($Execute) {
        throw 'Blocking processes still running. Exit Cursor and Docker Desktop, then retry.'
    }
}

foreach ($j in $jobs) {
    Move-FolderToD -Source $j.Source -Dest $j.Dest -DoExecute:$Execute
}

if (-not $Execute) {
    Write-Step "`nNext steps:" 'Cyan'
    Write-Step '1. Close Cursor and Docker Desktop completely.'
    Write-Step '2. Run: .\scripts\move-dev-data-to-d.ps1 -Execute'
    Write-Step '3. Docker disk (optional): Settings -> Resources -> Advanced -> Disk image location -> D:\Docker\wsl-data -> Apply & Restart'
    Write-Step '4. Reopen Cursor; run: Get-PSDrive C  (expect much more free space)'
} else {
    $cFreeAfter = (Get-PSDrive -Name C).Free
    Write-Step "`nDone. C: free now $(Get-SizeGB $cFreeAfter) GB" 'Green'
    Write-Step 'Set Docker disk location: Settings -> Resources -> Advanced -> D:\Docker\wsl-data -> Apply & Restart.'
}
