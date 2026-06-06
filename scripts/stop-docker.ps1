# stop-docker.ps1 — Stop the WorldBase Docker stack.
#   .\scripts\stop-docker.ps1            # stop + remove containers (keeps volumes/data)
#   .\scripts\stop-docker.ps1 -Volumes   # also remove named volumes (DELETES the DB!)

param(
    [switch]$Volumes
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path $PSScriptRoot -Parent)

if ($Volumes) {
    Write-Host 'Stopping WorldBase and REMOVING volumes (database will be lost) ...' -ForegroundColor Yellow
    docker compose down -v
} else {
    Write-Host 'Stopping WorldBase (data volumes preserved) ...' -ForegroundColor Cyan
    docker compose down
}
