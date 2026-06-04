# docker-repair-component-store.ps1 — Fix "Komponentenspeicher wurde besädigt" (ADMIN)
# Run BEFORE re-running docker-repair-admin.ps1 when VirtualMachinePlatform fails.
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Continue'
$Log = Join-Path (Split-Path $PSScriptRoot -Parent) 'docker-repair.log'

function Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Add-Content -Path $Log -Value $line
    Write-Host $line
}

Log '=== Component store repair (DISM + SFC) ==='
Log 'This can take 15-45 minutes. Do not close the window.'

Log 'DISM CheckHealth...'
DISM /Online /Cleanup-Image /CheckHealth 2>&1 | ForEach-Object { Log $_ }

Log 'DISM ScanHealth...'
DISM /Online /Cleanup-Image /ScanHealth 2>&1 | ForEach-Object { Log $_ }

Log 'DISM RestoreHealth (main fix)...'
DISM /Online /Cleanup-Image /RestoreHealth 2>&1 | ForEach-Object { Log $_ }

Log 'SFC /scannow...'
sfc /scannow 2>&1 | ForEach-Object { Log $_ }

Log '=== DISM/SFC finished ==='
Log 'REBOOT Windows, then in Admin PowerShell:'
Log '  .\scripts\docker-repair-admin.ps1'
Log 'Or: Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -All'
