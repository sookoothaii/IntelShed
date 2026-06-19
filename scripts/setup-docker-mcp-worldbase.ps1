# WorldBase — Docker MCP profile + DB volume sync for ai_coding
# Usage: .\scripts\setup-docker-mcp-worldbase.ps1
# After run: restart Cursor (reloads MCP_DOCKER gateway with updated profile)

$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$Backend = Join-Path $Root 'backend'
$DbPath = Join-Path $Backend 'worldbase.db'
$ProfileFile = Join-Path $Root 'docker\mcp\ai_coding-worldbase.profile.yaml'
$OpsScript = Join-Path $Root 'docker\mcp\ops-snapshot.js'

Write-Host ''
Write-Host 'WORLDBASE — Docker MCP setup' -ForegroundColor Cyan
Write-Host '===============================' -ForegroundColor Cyan
Write-Host ''

if (-not (Test-Path -LiteralPath $DbPath)) {
    Write-Host "Missing database: $DbPath" -ForegroundColor Red
    Write-Host 'Run .\start.ps1 once to init worldbase.db' -ForegroundColor Yellow
    exit 1
}

Write-Host '[1/4] Docker volumes + DB sync...' -ForegroundColor Yellow
docker volume create worldbase-mcp-data | Out-Null
docker volume create mcp-sqlite | Out-Null

$backendMount = $Backend -replace '\\', '/'
docker run --rm `
    -v "${backendMount}:/src:ro" `
    -v worldbase-mcp-data:/data `
    alpine cp /src/worldbase.db /data/worldbase.db | Out-Null

docker run --rm `
    -v "${backendMount}:/src:ro" `
    -v mcp-sqlite:/mcp `
    alpine cp /src/worldbase.db /mcp/worldbase.db | Out-Null

Write-Host '  Synced worldbase.db -> worldbase-mcp-data + mcp-sqlite' -ForegroundColor Green

Write-Host '[2/4] Import ai_coding profile (fetch + database-server)...' -ForegroundColor Yellow
if (-not (Test-Path -LiteralPath $ProfileFile)) {
    Write-Host "Missing profile file: $ProfileFile" -ForegroundColor Red
    exit 1
}
docker mcp profile import $ProfileFile
Write-Host '  Profile imported' -ForegroundColor Green

Write-Host '[3/4] Verify profile servers...' -ForegroundColor Yellow
docker mcp profile server ls
docker mcp profile config ai_coding --get database-server.database_url --format json

Write-Host '[4/4] Pre-pull MCP images...' -ForegroundColor Yellow
docker pull mcp/fetch:latest | Out-Null
docker pull souhardyak/mcp-db-server:latest | Out-Null
Write-Host '  Images ready' -ForegroundColor Green

Write-Host ''
Write-Host 'Done.' -ForegroundColor Green
Write-Host ''
Write-Host 'Next steps:' -ForegroundColor Cyan
Write-Host '  1. Restart Cursor (MCP_DOCKER reloads profile ai_coding)'
Write-Host '  2. In chat, register code-mode once:'
Write-Host '       MCP_DOCKER -> code-mode name=ops-snapshot servers=[fetch]'
Write-Host '     Script body: docker/mcp/ops-snapshot.js'
Write-Host '  3. Host SQL (no Docker): filesystem_mcp -> db_query on backend/worldbase.db'
Write-Host ''
Write-Host "Ops script: $OpsScript" -ForegroundColor DarkGray
