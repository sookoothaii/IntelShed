# docker-preflight.ps1 — Why WSL2/Docker fails (run as Admin for full output)
$ErrorActionPreference = 'Continue'
Write-Host '=== Virtualization (BIOS/firmware) ===' -ForegroundColor Cyan
try {
    $os = Get-CimInstance Win32_ComputerSystem
    Write-Host "HypervisorPresent: $($os.HypervisorPresent)"
} catch {}
try {
    $firmware = (Get-CimInstance -ClassName Win32_Processor).VirtualizationFirmwareEnabled
    Write-Host "VirtualizationFirmwareEnabled (CPU): $firmware"
} catch { Write-Host 'VirtualizationFirmwareEnabled: (run as Admin or use msinfo32)' }
systeminfo | Select-String 'Hypervisor|Virtualization'

Write-Host "`n=== Optional features ===" -ForegroundColor Cyan
@('VirtualMachinePlatform', 'Microsoft-Windows-Subsystem-Linux', 'Microsoft-Hyper-V-All') | ForEach-Object {
    $f = Get-WindowsOptionalFeature -Online -FeatureName $_ -ErrorAction SilentlyContinue
    if ($f) { Write-Host "$($f.FeatureName): $($f.State)" }
}

Write-Host "`n=== WSL ===" -ForegroundColor Cyan
wsl --status 2>&1
wsl -l -v 2>&1

Write-Host "`n=== Services ===" -ForegroundColor Cyan
Get-Service WslService, vmcompute, hns -ErrorAction SilentlyContinue | Format-Table Name, Status, StartType

Write-Host "`n=== If VirtualMachinePlatform is not Enabled ===" -ForegroundColor Yellow
Write-Host 'Docker/Flowsint need WSL2. Fix Windows component store first (see docs/DOCKER_REPAIR.md).'
Write-Host 'BIOS: enable Intel VT-x / AMD-SVM if VirtualizationFirmwareEnabled is False.'
