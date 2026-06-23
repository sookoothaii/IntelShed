# start-redis.ps1 — Local Redis for WorldBase rate limiting (native start.ps1 dev stack).
#
# Uses docker-compose service `redis` (127.0.0.1:6380 on the host).
# Does NOT start the WorldBase API or Vite — operator runs start.ps1 separately.
#
# Usage:
#   .\scripts\start-redis.ps1
#   .\scripts\start-redis.ps1 -Down

param(
    [switch]$Down
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $Root

if ($Down) {
    docker compose stop redis
    Write-Host 'Redis stopped (container kept). Use: docker compose rm -sf redis' -ForegroundColor Yellow
    exit 0
}

Write-Host '=== WorldBase Redis (local Docker) ===' -ForegroundColor Cyan
docker compose up -d redis

$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) {
    $pong = docker compose exec -T redis redis-cli ping 2>$null
    if ($pong -match 'PONG') {
        Write-Host 'Redis: PONG on 127.0.0.1:6380' -ForegroundColor Green
        exit 0
    }
    Start-Sleep -Seconds 2
}

Write-Host 'Redis container up but healthcheck not green yet — check: docker compose ps redis' -ForegroundColor Yellow
exit 1
