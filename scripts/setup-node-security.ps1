# setup-node-security.ps1 — Generate node tokens and configure PC + Pi sync
# Run from worldbase root. Does NOT push to Pi automatically (SSH step at end).

$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$BackendEnv = Join-Path $Root 'backend\.env'
$Example = Join-Path $Root 'backend\.env.example'

function New-Token {
    $bytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', 'x').Replace('/', 'y').Substring(0, 32)
}

$token = New-Token
$bind = '0.0.0.0'  # Pi on LAN must reach PC; protected by NODE_INGEST_TOKEN

Write-Host '=== WorldBase node security setup ===' -ForegroundColor Cyan

if (-not (Test-Path $BackendEnv)) {
    if (Test-Path $Example) {
        Copy-Item $Example $BackendEnv
        Write-Host "Created $BackendEnv from example" -ForegroundColor Green
    } else {
        New-Item -Path $BackendEnv -ItemType File -Force | Out-Null
    }
}

$lines = @(Get-Content $BackendEnv -ErrorAction SilentlyContinue)
$keys = @{
    'NODE_INGEST_TOKEN' = $token
    'NODE_ADMIN_TOKEN'  = $token
    'WORLDBASE_BIND_HOST' = $bind
}
$out = New-Object System.Collections.Generic.List[string]
$seen = @{}
foreach ($line in $lines) {
    $k = ($line -split '=', 2)[0].Trim()
    if ($keys.ContainsKey($k)) {
        $out.Add("$k=$($keys[$k])")
        $seen[$k] = $true
    } else {
        $out.Add($line)
    }
}
foreach ($k in $keys.Keys) {
    if (-not $seen[$k]) { $out.Add("$k=$($keys[$k])") }
}
Set-Content -Path $BackendEnv -Value $out -Encoding UTF8

$PiDropin = @"
# Copy to Pi: /etc/systemd/system/worldbase_push.service.d/override.conf
#          and worldbase_pull.service.d/override.conf
[Service]
Environment=NODE_INGEST_TOKEN=$token
"@

$PiDir = Join-Path $Root 'offgrid-raspi\scripts\pi-node-token.conf'
Set-Content -Path $PiDir -Value $PiDropin -Encoding UTF8
Write-Host '  (pi-node-token.conf is gitignored — do not commit)' -ForegroundColor DarkGray

Write-Host ''
Write-Host 'PC backend/.env updated:' -ForegroundColor Green
Write-Host "  NODE_INGEST_TOKEN=(32 chars)"
Write-Host "  WORLDBASE_BIND_HOST=$bind"
Write-Host ''
Write-Host 'Pi override written:' -ForegroundColor Yellow
Write-Host "  $PiDir"
Write-Host ''
Write-Host 'On the Pi (SSH):' -ForegroundColor Cyan
Write-Host @'
  sudo mkdir -p /etc/systemd/system/worldbase_push.service.d
  sudo mkdir -p /etc/systemd/system/worldbase_pull.service.d
  sudo cp pi-node-token.conf /etc/systemd/system/worldbase_push.service.d/override.conf
  sudo cp pi-node-token.conf /etc/systemd/system/worldbase_pull.service.d/override.conf
  sudo systemctl daemon-reload
  sudo systemctl restart worldbase_push worldbase_pull
'@
Write-Host 'Restart WorldBase backend after this (start.ps1).' -ForegroundColor Yellow
