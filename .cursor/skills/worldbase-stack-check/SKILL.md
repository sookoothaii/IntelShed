---
name: worldbase-stack-check
description: One-shot stack health audit for WorldBase. Use when the operator asks to check the project, asks for status, wants to know if everything is up, or returns after a break. Triggers include phrases like "check the project", "status?", "is everything running?", "stack health".
---

# WorldBase Stack Check (One-Shot Audit)

This skill runs a deterministic 7-check audit covering backend, frontend, Ollama, Pi sync, briefing, smoke test, and git state. Output is a concise table the operator can scan in 5 seconds.

## When to use
- Operator asks for project status, stack health, or whether services are up
- Returning to the project after a long pause, before starting new work
- Before a release or before claiming "done"

## Execution order (do all in parallel where independent)

### 1. Liveness probes (parallel)
```powershell
# Backend
try { (Invoke-WebRequest -Uri 'http://127.0.0.1:8002/api/health/ping' -UseBasicParsing -TimeoutSec 3).Content } catch { "BACKEND_DOWN" }
# Frontend
try { (Invoke-WebRequest -Uri 'http://localhost:5176' -UseBasicParsing -TimeoutSec 3).StatusCode } catch { "FRONTEND_DOWN" }
# Ollama
try { (Invoke-WebRequest -Uri 'http://127.0.0.1:11434/api/tags' -UseBasicParsing -TimeoutSec 3).Content | ConvertFrom-Json | Select-Object -ExpandProperty models | Measure-Object | Select-Object Count } catch { "OLLAMA_DOWN" }
```

### 2. Briefing freshness
```powershell
$b = Invoke-RestMethod -Uri 'http://127.0.0.1:8002/api/briefing' -TimeoutSec 5
$created = [datetimeoffset]::Parse($b.created_at)
$age_min = [math]::Round(([datetimeoffset]::UtcNow - $created).TotalMinutes, 1)
"age=${age_min}min bytes=$($b.text.Length)"
```
Briefing should be < 6 h old (or `WORLDBASE_BRIEFING_INTERVAL` seconds).
**Note:** use `[datetimeoffset]::Parse` — `[datetime]` strips the timezone and produces wrong ages.

### 3. Pi node health
```powershell
$n = Invoke-RestMethod -Uri 'http://127.0.0.1:8002/api/nodes' -TimeoutSec 5
foreach ($node in $n.nodes) { "$($node.node_id) | online=$($node.online) | age=$([int]$node.age_seconds)s | temp=$($node.sensors.temp_c)" }
```
Expected: `online=True`, `age < 60s`, sensors present.

### 4. Pi SSH check (if node offline)
Only if `/api/nodes` reports offline:
```powershell
& "$env:WINDIR\System32\OpenSSH\ssh.exe" -i "$env:USERPROFILE\.ssh\offgrid-pi" -o ConnectTimeout=8 -o BatchMode=yes user0@192.168.1.121 "journalctl -u worldbase_push -n 5 --no-pager"
```
Common cause: PC IP drift (reservation lost, DHCP expired). PC should be on `192.168.1.111`.

### 5. Smoke test (full validation)
```powershell
.\scripts\smoke-test.ps1
```
Expected: **25/25 PASS**, FAIL 0, WARN 0.

### 6. Git state
```powershell
git status --short
git log --oneline -3
```
Note any unexpected uncommitted files (especially `*.db-shm`, `*.db-wal` should be gitignored).

### 7. Health-feed staleness
```powershell
$h = Invoke-RestMethod -Uri 'http://127.0.0.1:8002/api/health' -TimeoutSec 8
$h.feeds.PSObject.Properties | Where-Object { $_.Value.status -eq 'stale' } | Select-Object Name, @{N='age_h';E={[math]::Round($_.Value.age_sec/3600,1)}}
```
Stale feeds with active TTL are usually self-healing on next pull.

## Output format

Present as a single markdown table, no narration:

| Check | Status | Notes |
|---|---|---|
| Backend `/api/health/ping` | ✅/❌ | |
| Frontend `:5176` | ✅/❌ | |
| Ollama (model count) | ✅/❌ | |
| Briefing freshness | ✅/⚠️/❌ | age, bytes |
| Pi node | ✅/❌ | online, age, temp |
| Smoke test | ✅/❌ | X/Y PASS |
| Git | ✅/⚠️ | clean / dirty |

Only drill deeper when a check fails.

## Quality standards
- Run probes in parallel batches (one Shell call per batch)
- Smoke test takes ~50 s; queue it but do not block other checks on it
- If backend is down, do **not** proceed to checks 2/3/4/7 — fix backend first via `.\start.ps1`
- Never fabricate numbers — if a check times out, report "TIMEOUT" not a guess
