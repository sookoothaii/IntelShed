# docker-repair-enable-wsl.ps1 — Enable WSL2 features + update (skip full DISM)
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Continue'
$Log = Join-Path (Split-Path $PSScriptRoot -Parent) 'docker-repair.log'

function Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Add-Content -Path $Log -Value $line
    Write-Host $line
}

Log '=== WSL2 enable (no DISM) ==='

Get-Service WslService -ErrorAction SilentlyContinue | ForEach-Object {
    Set-Service WslService -StartupType Automatic
    Start-Service WslService -ErrorAction SilentlyContinue
    Log "WslService: $($_.Status) -> running"
}

foreach ($f in @('VirtualMachinePlatform', 'Microsoft-Windows-Subsystem-Linux')) {
    $state = (Get-WindowsOptionalFeature -Online -FeatureName $f -ErrorAction SilentlyContinue).State
    Log "Feature $f : $state"
    if ($state -ne 'Enabled') {
        try {
            $r = Enable-WindowsOptionalFeature -Online -FeatureName $f -All -NoRestart -ErrorAction Stop
            Log "$f -> $($r.RestartNeeded)"
        } catch {
            Log "FAIL $f : $($_.Exception.Message)"
        }
    }
}

Log 'wsl --install --no-distribution ...'
wsl --install --no-distribution 2>&1 | ForEach-Object { Log $_ }
wsl --update 2>&1 | ForEach-Object { Log $_ }
wsl --set-default-version 2 2>&1 | ForEach-Object { Log $_ }
wsl --status 2>&1 | ForEach-Object { Log $_ }

Log 'If RestartNeeded: REBOOT then: winget install Docker.DockerDesktop'
Log '=== done ==='
