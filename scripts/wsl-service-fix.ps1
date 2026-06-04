# wsl-service-fix.ps1 — Enable WslService (fixes Wsl/0x80070422). Run as Administrator.
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$s = Get-Service WslService
Write-Host "WslService before: $($s.StartType) / $($s.Status)"
Set-Service WslService -StartupType Automatic
Start-Service WslService
$s2 = Get-Service WslService
Write-Host "WslService after:  $($s2.StartType) / $($s2.Status)"
Write-Host ""
wsl --status
wsl -l -v
