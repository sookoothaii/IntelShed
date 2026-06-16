---
name: worldbase-firewall
description: Understand and interact with the HAK_GAL LLM security firewall. Use when the user specifically asks to enable, debug, or integrate the firewall, or when encountering port 8001 connection issues.
disable-model-invocation: true
---

# HAK_GAL Security Firewall Integration

WorldBase includes an optional integration with the HAK_GAL LLM firewall (port 8001). This is strictly **out of scope** for normal operations unless the operator explicitly requests it.

## Architecture Guidelines
- The firewall runs as a completely separate standalone service.
- Integration point: `backend/firewall_bridge.py`.
- It uses a **fail-open design**: if the firewall is unreachable, WorldBase continues normally.
- UI Toggle: Controlled by `SHOW_FIREWALL` in `frontend/src/lib/features.ts` or via `.env`.

## Diagnostics Instructions
If the operator explicitly requests firewall debugging:
1. Check backend status:
   ```powershell
   Invoke-RestMethod "http://127.0.0.1:8002/api/firewall/status"
   ```
2. Test payload rejection:
   ```powershell
   Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8002/api/firewall/test" -Body '{"query": "hello"}' -ContentType "application/json"
   ```

## Quality Standards
- Remember that the firewall consumes significant VRAM. If Ollama runs out of memory, advise the user to shut down the firewall or adjust `OLLAMA_KEEP_ALIVE`.
- **Never** attempt to fix the firewall's internal Python dependencies from this repository. The firewall lives outside the WorldBase Git tree. Focus only on the bridge script.