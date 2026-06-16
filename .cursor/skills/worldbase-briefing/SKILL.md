---
name: worldbase-briefing
description: Test and validate the WorldBase briefing pipeline, Operator region classification, and Pi node sync. Use when modifying operator_briefing.py, node_sync.py, or when asked to verify briefing generation or node pull.
disable-model-invocation: true
---

# WorldBase Briefing Pipeline Validation

This skill ensures the core intelligence briefing pipeline functions flawlessly, from feed ingestion to operator classification and Pi edge synchronization.

## Instructions

When working on the briefing pipeline, follow this strict validation sequence:

### 1. Static Validation (Unit Tests)
Always run the local unit tests first to ensure region classification logic (e.g., Thailand LOCAL vs REGIONAL) works without network dependencies:
```powershell
cd backend
.\venv\Scripts\python.exe -m unittest test_operator_briefing -v
```

### 2. Live Generation (FastAPI & Ollama)
Ensure the backend is running (`.\start.ps1` or `uvicorn`). Force a fresh briefing generation to verify Ollama (`qwen3:8b`) and the prompt formatting:
```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8002/api/briefing/generate" -TimeoutSec 120
```

### 3. Edge Node Pull Verification (Pi-Sync)
Verify that the Raspberry Pi can successfully pull the updated briefing via the dedicated mesh/pull endpoint. It must contain the `briefing_at` and `fusion_hotspots` fields:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8002/api/node/pull" | ConvertTo-Json -Depth 3
```

## Quality Standards
- **Never** commit changes to `operator_briefing.py` or `node_sync.py` if Step 1 fails.
- If Ollama timeouts occur in Step 2, advise the operator to check `OLLAMA_HOST` or the VRAM load.
- Always ensure the `digest` metadata (LOCAL/REGION/GLOBAL counts) aligns with the configured `WORLDBASE_OPERATOR_REGION`.