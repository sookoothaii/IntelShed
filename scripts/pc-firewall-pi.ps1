# Allow Raspberry Pi to reach WorldBase backend on LAN port 8002.
# Requires Administrator.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/pc-firewall-pi.ps1

$ErrorActionPreference = 'Stop'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Run as Administrator.' -ForegroundColor Red
    exit 1
}

$PiIp = $env:WORLDBASE_PI_IP
if (-not $PiIp) { $PiIp = '192.168.1.121' }

$name = 'WorldBase Pi LAN 8002'
$existing = Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
if ($existing) {
    Remove-NetFirewallRule -DisplayName $name
}

New-NetFirewallRule -DisplayName $name `
    -Direction Inbound -Action Allow -Protocol TCP `
    -LocalPort 8002 -RemoteAddress $PiIp | Out-Null

Write-Host "Firewall: allow TCP 8002 from $PiIp" -ForegroundColor Green
