# LF-safe deploy: worldbase_push.py + worldbase_pull.py (+ optional portal) to Off-Grid Pi.
# Avoids CRLF trap (python3\r shebang) when SCP from Windows.
# Prereqs: SSH key ~/.ssh/offgrid-pi, Pi user0@192.168.1.121
#
# Usage:
#   .\scripts\deploy-pi-sync.ps1              # push + pull scripts
#   .\scripts\deploy-pi-sync.ps1 -Portal      # offgrid-portal + portal_ui.html + 120s pull
#   .\scripts\deploy-pi-sync.ps1 -TrimArduino # remove /mnt/sdcard/.arduino15 (~7 GB)
#   .\scripts\deploy-pi-sync.ps1 -NoClearBuffer

param(
    [switch]$Portal,
    [switch]$TrimArduino,
    [switch]$NoClearBuffer
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$PiHost = $env:WORLDBASE_PI_HOST
if (-not $PiHost) { $PiHost = '192.168.1.121' }
$PiProject = $env:WORLDBASE_PI_PROJECT
if (-not $PiProject) { $PiProject = '/home/user0/CascadeProjects/windsurf-project' }

$ssh = Join-Path $env:WINDIR 'System32\OpenSSH\ssh.exe'
$scp = Join-Path $env:WINDIR 'System32\OpenSSH\scp.exe'
$key = Join-Path $env:USERPROFILE '.ssh\offgrid-pi'
$pi = "user0@$PiHost"

function Write-LfCopy {
    param([string]$Src, [string]$DstName)
    if (-not (Test-Path $Src)) {
        throw "Missing source: $Src"
    }
    $out = Join-Path $env:TEMP $DstName
    $raw = [IO.File]::ReadAllText($Src)
    $lf = $raw -replace "`r`n", "`n" -replace "`r", "`n"
    [IO.File]::WriteAllText($out, $lf, [Text.UTF8Encoding]::new($false))
    return $out
}

$pushSrc = Join-Path $Root 'offgrid-raspi\scripts\worldbase_push.py'
$pullSrc = Join-Path $Root 'offgrid-raspi\scripts\worldbase_pull.py'
$portalSrc = Join-Path $Root 'offgrid-raspi\offgrid\bin\offgrid-portal'
$portalUiSrc = Join-Path $Root 'offgrid-raspi\offgrid\content\portal_ui.html'

Write-Host "=== deploy-pi-sync -> $pi ===" -ForegroundColor Cyan

$pushLf = Write-LfCopy $pushSrc 'worldbase_push.py'
$pullLf = Write-LfCopy $pullSrc 'worldbase_pull.py'
& $scp -i $key $pushLf $pullLf "${pi}:/tmp/"
Write-Host 'SCP: worldbase_push.py, worldbase_pull.py' -ForegroundColor Green

if ($Portal) {
    $portalLf = Write-LfCopy $portalSrc 'offgrid-portal'
    $portalUiLf = Write-LfCopy $portalUiSrc 'portal_ui.html'
    & $scp -i $key $portalLf $portalUiLf "${pi}:/tmp/"
    & $ssh -i $key -o BatchMode=yes $pi "mv /tmp/portal_ui.html /tmp/offgrid-portal-ui.html"
    Write-Host 'SCP: offgrid-portal, portal_ui.html' -ForegroundColor Green
}

$trimBlock = ''
if ($TrimArduino) {
    $trimBlock = @'
echo "--- trim .arduino15 ---"
if [ -d /mnt/sdcard/.arduino15 ]; then
  du -sh /mnt/sdcard/.arduino15
  rm -rf /mnt/sdcard/.arduino15
  echo "removed /mnt/sdcard/.arduino15"
else
  echo "no /mnt/sdcard/.arduino15"
fi
rm -f /home/user0/.local/bin/arduino-cli 2>/dev/null || true
df -h /mnt/sdcard | tail -1
'@
}

$clearBuffer = if ($NoClearBuffer) { '' } else {
    'sudo rm -f /var/lib/offgrid/worldbase_push_buffer.jsonl'
}

$portalBlock = ''
if ($Portal) {
    $portalBlock = @"
cp /tmp/offgrid-portal $PiProject/offgrid/bin/offgrid-portal
chmod +x $PiProject/offgrid/bin/offgrid-portal
cp /tmp/offgrid-portal-ui.html $PiProject/offgrid/content/portal_ui.html
sudo mkdir -p /etc/systemd/system/worldbase_pull.service.d
cat <<'OPERATORDROP' | sudo tee /etc/systemd/system/worldbase_pull.service.d/operator-interval.conf >/dev/null
[Service]
Environment=WORLDBASE_PULL_INTERVAL=120
OPERATORDROP
"@
}

$restartPortal = if ($Portal) { 'sudo systemctl restart offgrid-portal' } else { '' }

$remote = @"
set -e
sudo cp /tmp/worldbase_push.py /usr/local/bin/worldbase_push.py
sudo chmod +x /usr/local/bin/worldbase_push.py
sudo cp /tmp/worldbase_pull.py /usr/local/bin/worldbase_pull.py
sudo chmod +x /usr/local/bin/worldbase_pull.py
$portalBlock
$clearBuffer
if [ -f /etc/systemd/system/worldbase_pull.service.d/operator-interval.conf ]; then
  sudo systemctl daemon-reload
fi
sudo systemctl restart worldbase_push worldbase_pull
$restartPortal
sleep 2
echo "--- services ---"
systemctl is-active worldbase_push worldbase_pull offgrid-portal
echo "--- pull interval ---"
systemctl show worldbase_pull -p Environment --no-pager | tr ' ' '\n' | grep PULL_INTERVAL || true
$trimBlock
echo "--- push log ---"
journalctl -u worldbase_push --no-pager --lines=3
"@

$remote = ($remote -replace "`r`n", "`n") -replace "`r", ""
$remote | & $ssh -i $key -o BatchMode=yes $pi bash -s
Write-Host 'Done.' -ForegroundColor Green
