# Requires Administrator: forwards LAN :8000 -> WorldBase :8002 so Pi can keep WORLDBASE_PORT=8000 until reconfigured.
# Run: powershell -ExecutionPolicy Bypass -File scripts/pc-portproxy-for-pi.ps1

$ErrorActionPreference = 'Stop'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host 'Run this script as Administrator.' -ForegroundColor Red
    exit 1
}

netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=8000 2>$null
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=8000 connectaddress=127.0.0.1 connectport=8002
netsh interface portproxy show all
Write-Host 'Port proxy active: 0.0.0.0:8000 -> 127.0.0.1:8002' -ForegroundColor Green
Write-Host 'Prefer fixing the Pi with: sudo bash fix-worldbase-port-8002.sh' -ForegroundColor Yellow
