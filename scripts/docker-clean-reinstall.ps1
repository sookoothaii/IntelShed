# docker-clean-reinstall.ps1 — Remove Docker + WSL distros, then fresh install path
# Run as Administrator. READ prompts — this deletes Docker/WSL VM data.
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Continue'
$Log = Join-Path (Split-Path $PSScriptRoot -Parent) 'docker-repair.log'

function Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Add-Content -Path $Log -Value $line
    Write-Host $line
}

Log '=== CLEAN: Docker + WSL (Docker-related) ==='

# 1) Stop Docker processes
Get-Process -Name 'Docker Desktop','com.docker.backend','docker*' -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 3

# 2) Uninstall Docker Desktop (winget + legacy uninstaller)
if (Get-Command winget -ErrorAction SilentlyContinue) {
    Log 'winget uninstall Docker.DockerDesktop ...'
    winget uninstall -e --id Docker.DockerDesktop --silent 2>&1 | ForEach-Object { Log $_ }
}
$uninstall = 'C:\Program Files\Docker\Docker\Docker Desktop Installer.exe'
if (Test-Path $uninstall) {
    Log 'Running Docker uninstaller ...'
    Start-Process -FilePath $uninstall -ArgumentList 'uninstall' -Wait -NoNewWindow -ErrorAction SilentlyContinue
}

# 3) Remove install dir if still present
foreach ($dir in @(
    'C:\Program Files\Docker',
    'C:\Program Files\Docker\Docker'
)) {
    if (Test-Path $dir) {
        Log "Removing $dir ..."
        Remove-Item -LiteralPath $dir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# 4) Unregister WSL distros used by Docker (safe for other distros if you name them)
$dockerDistros = @('docker-desktop', 'docker-desktop-data')
wsl -l -v 2>&1 | ForEach-Object { Log "wsl list: $_" }
$wslList = @(wsl -l -v 2>$null | ForEach-Object { $_.ToString() })
foreach ($d in $dockerDistros) {
    if ($wslList -match [regex]::Escape($d)) {
        Log "wsl --unregister $d"
        wsl --unregister $d 2>&1 | ForEach-Object { Log $_ }
    } else {
        Log "wsl distro not found (skip): $d"
    }
}

# 5) User data (settings/cache — fresh start)
foreach ($p in @(
    "$env:LOCALAPPDATA\Docker",
    "$env:APPDATA\Docker",
    "$env:USERPROFILE\.docker"
)) {
    if (Test-Path $p) {
        Log "Removing $p ..."
        Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue
    }
}

# 6) Docker service
Get-Service com.docker.service -ErrorAction SilentlyContinue | ForEach-Object {
    Stop-Service com.docker.service -Force -ErrorAction SilentlyContinue
    sc.exe delete com.docker.service 2>&1 | ForEach-Object { Log $_ }
}

Log '=== CLEAN done ==='
Log ''
Log 'NEXT (after this script):'
Log '  1) REBOOT Windows'
Log '  2) Admin PS:  wsl --install --no-distribution'
Log '  3) REBOOT again if prompted'
Log '  4) Admin PS:  winget install -e --id Docker.DockerDesktop'
Log '  5) Start Docker Desktop, wait for Engine running'
Log '  6) docker version'
Log '  7) cd worldbase; .\scripts\start-flowsint.ps1 -Build'
Log ''
Log 'If wsl --install fails: Settings -> Apps -> Optional features -> remove+add'
Log '  "Virtual Machine Platform" and "Windows Subsystem for Linux", then reboot.'
