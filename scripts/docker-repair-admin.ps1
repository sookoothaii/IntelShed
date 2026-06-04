# docker-repair-admin.ps1 — Fix WSL + reinstall Docker Desktop (ADMIN required)
# Evidence 2026-06-03: WslService Disabled -> Docker failed with Wsl/0x80070422
# Run: Right-click PowerShell -> "Run as administrator", then:
#   Set-Location "D:\MCP Mods\worldbase"
#   .\scripts\docker-repair-admin.ps1

#Requires -RunAsAdministrator
$ErrorActionPreference = 'Continue'
$Log = Join-Path (Split-Path $PSScriptRoot -Parent) 'docker-repair.log'
$RebootNeeded = $false

function Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Add-Content -Path $Log -Value $line
    Write-Host $line
}

Log '=== Docker/WSL repair start ==='

# 1) Enable and start WSL service (root cause of 0x80070422)
foreach ($svc in @('WslService', 'LxssManager')) {
    $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if (-not $s) { Log "Service $svc not present (skip)"; continue }
    Log "$svc was: StartType=$($s.StartType) Status=$($s.Status)"
    Set-Service -Name $svc -StartupType Automatic
    try {
        Start-Service -Name $svc -ErrorAction Stop
        Log "$svc started OK"
    } catch {
        Log "WARN start $svc : $($_.Exception.Message)"
    }
}

# 2) Windows optional features for WSL2
$features = @(
    'Microsoft-Windows-Subsystem-Linux',
    'VirtualMachinePlatform'
)
foreach ($f in $features) {
    $state = (Get-WindowsOptionalFeature -Online -FeatureName $f -ErrorAction SilentlyContinue).State
    Log "Feature $f : $state"
    if ($state -eq 'Enabled') { continue }
    Log "Enabling $f (may take a few minutes)..."
    try {
        $r = Enable-WindowsOptionalFeature -Online -FeatureName $f -NoRestart -All -ErrorAction Stop
        if ($r.RestartNeeded) { $RebootNeeded = $true }
        Log "$f enable OK (RestartNeeded=$($r.RestartNeeded))"
    } catch {
        $msg = $_.Exception.Message
        Log "FAIL $f : $msg"
        if ($msg -match 'Komponentenspeicher|component store|0x80073712') {
            Log '>>> Component store corrupt. Run FIRST:'
            Log '>>>   .\scripts\docker-repair-component-store.ps1'
            Log '>>> Then REBOOT and run this script again.'
        }
    }
}

# 3) WSL update + default version
Log 'Running wsl --update ...'
wsl --update 2>&1 | ForEach-Object { Log "wsl --update: $_" }
wsl --set-default-version 2 2>&1 | ForEach-Object { Log "wsl --set-default-version: $_" }
wsl --status 2>&1 | ForEach-Object { Log "wsl --status: $_" }

# 4) Install Docker Desktop if missing
$dockerExe = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
if (-not (Test-Path $dockerExe)) {
    Log 'Docker Desktop not in Program Files — installing via winget...'
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements 2>&1 |
            ForEach-Object { Log "winget: $_" }
    } else {
        Log 'winget missing — download installer from https://www.docker.com/products/docker-desktop/'
    }
} else {
    Log "Docker Desktop found: $dockerExe"
}

if ($RebootNeeded) { Log 'REBOOT REQUIRED (Windows optional feature).' }
Log '=== Repair script finished ==='
Log 'REBOOT recommended, then start "Docker Desktop" from Start menu and wait until engine is running.'
Log 'Then: .\scripts\start-flowsint.ps1 -Build'
