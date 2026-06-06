# Deploy PC node token + HTTP LAN sync to the Off-Grid Pi via SSH.
# Prereqs: setup-node-security.ps1, SSH key ~/.ssh/offgrid-pi, Pi user0@192.168.1.121
# Also run pc-firewall-pi.ps1 as Admin once on the PC.

$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$PiHost = $env:WORLDBASE_PI_HOST
if (-not $PiHost) { $PiHost = '192.168.1.121' }
$PcIp = $env:WORLDBASE_PC_IP
if (-not $PcIp) { $PcIp = '192.168.1.111' }

$tokenFile = Join-Path $Root 'offgrid-raspi\scripts\pi-node-token.conf'
if (-not (Test-Path $tokenFile)) {
    Write-Host 'Missing pi-node-token.conf — run .\scripts\setup-node-security.ps1 first' -ForegroundColor Red
    exit 1
}

$ssh = Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
$key = Join-Path $env:USERPROFILE '.ssh\offgrid-pi'
$tokenConf = Get-Content $tokenFile -Raw
$httpConf = @"
[Service]
Environment=WORLDBASE_SCHEME=http
Environment=WORLDBASE_PORT=8002
Environment=WORLDBASE_PC=$PcIp
"@

Write-Host "Deploying sync config to user0@${PiHost}..." -ForegroundColor Cyan

$remote = @"
set -e
sudo mkdir -p /etc/systemd/system/worldbase_push.service.d
sudo mkdir -p /etc/systemd/system/worldbase_pull.service.d
sudo mv /etc/systemd/system/worldbase_push.service.d/tls.conf /etc/systemd/system/worldbase_push.service.d/tls.conf.bak 2>/dev/null || true
sudo mv /etc/systemd/system/worldbase_pull.service.d/tls.conf /etc/systemd/system/worldbase_pull.service.d/tls.conf.bak 2>/dev/null || true
cat <<'TOKENDROP' | sudo tee /etc/systemd/system/worldbase_push.service.d/override.conf >/dev/null
$tokenConf
TOKENDROP
cat <<'TOKENDROP' | sudo tee /etc/systemd/system/worldbase_pull.service.d/override.conf >/dev/null
$tokenConf
TOKENDROP
cat <<'HTTPDROP' | sudo tee /etc/systemd/system/worldbase_push.service.d/http-lan.conf >/dev/null
$httpConf
HTTPDROP
cat <<'HTTPDROP' | sudo tee /etc/systemd/system/worldbase_pull.service.d/http-lan.conf >/dev/null
$httpConf
HTTPDROP
sudo systemctl daemon-reload
sudo systemctl restart worldbase_push worldbase_pull
sleep 2
systemctl is-active worldbase_push worldbase_pull
journalctl -u worldbase_push -n 2 --no-pager
curl -s -m 8 http://${PcIp}:8002/api/health || echo HEALTH_FAIL
"@

# Pipe as LF-only script — avoids CRLF breaking bash on the Pi
$remote = $remote -replace "`r`n", "`n"
$remote | & $ssh -i $key -o BatchMode=yes "user0@$PiHost" bash -s
Write-Host 'Done. Restart PC backend (.\start.ps1) if WORLDBASE_BIND_HOST changed.' -ForegroundColor Yellow
