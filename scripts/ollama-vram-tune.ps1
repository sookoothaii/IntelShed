# Free Ollama VRAM and apply lean defaults for WorldBase + Cesium on one GPU.
# Run from worldbase root. Restart backend + Ollama after changes.

$ErrorActionPreference = 'Stop'
$Root = Split-Path $PSScriptRoot -Parent
$EnvFile = Join-Path $Root 'backend\.env'

Write-Host '=== Ollama VRAM tune ===' -ForegroundColor Cyan

# Unload all models from VRAM now
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    ollama ps 2>$null
    ollama stop qwen3:8b 2>$null
    ollama stop qwen2.5:14b 2>$null
    ollama stop nomic-embed-text 2>$null
    Write-Host 'Stopped loaded Ollama models.' -ForegroundColor Green
} else {
    Write-Host 'ollama CLI not in PATH — skip stop' -ForegroundColor Yellow
}

if (-not (Test-Path $EnvFile)) {
    Write-Host "No $EnvFile — copy from .env.example first" -ForegroundColor Red
    exit 1
}

$lines = Get-Content $EnvFile
$set = @{
    'OLLAMA_KEEP_ALIVE' = '0'
    'OLLAMA_MODEL' = 'qwen3:8b'
    'WORLDBASE_BRIEFING_AUTOPILOT' = '0'
    'WORLDBASE_RAG_AUTOPILOT' = '0'
    'WORLDBASE_BRIEFING_INTERVAL' = '1800'
    'FIREWALL_HOST' = ''
}
$out = New-Object System.Collections.Generic.List[string]
$seen = @{}
foreach ($line in $lines) {
    $k = ($line -split '=', 2)[0].Trim()
    if ($set.ContainsKey($k)) {
        $out.Add("$k=$($set[$k])")
        $seen[$k] = $true
    } else {
        $out.Add($line)
    }
}
foreach ($k in $set.Keys) {
    if (-not $seen[$k]) { $out.Add("$k=$($set[$k])") }
}
Set-Content -Path $EnvFile -Value $out -Encoding UTF8

Write-Host ''
Write-Host 'backend/.env updated (Globe-first profile):' -ForegroundColor Green
Write-Host '  OLLAMA_KEEP_ALIVE=0'
Write-Host '  WORLDBASE_BRIEFING_AUTOPILOT=0'
Write-Host '  WORLDBASE_RAG_AUTOPILOT=0'
Write-Host '  FIREWALL_HOST= (disabled)'
Write-Host ''
Write-Host 'Restart: close HAK_GAL firewall if running, then .\start.ps1' -ForegroundColor Yellow
Write-Host 'Intel mode (Pi briefing): set WORLDBASE_BRIEFING_AUTOPILOT=1 and OLLAMA_KEEP_ALIVE=1m' -ForegroundColor DarkGray
