# WorldBase × HAK_GAL — optional spare-parts integration

Optional bridge to the external **HAK_GAL LLM-Security-Firewall** orchestrator (default port **8001**).

**Important:** HAK_GAL full stack is **not** treated as always functional. It is a **spare-parts warehouse** — borrow ideas and optional `/v1/detect` enrichment when the orchestrator is up. Full stack easily fills **16 GB VRAM** alongside Ollama.

**WorldBase baseline (always on, 0 VRAM):** `backend/prompt_guard.py` — slim regex guard for MCP write tools.

Deep research: operator-local `research/HAK_GAL_PICK_LIST.md`, `research/VRAM_16GB_DOCKER_GPU_SCHEDULER_PLAN.md`.

---

## Architecture

```text
MCP write tool
    → prompt_guard.slim_prompt_scan     [WorldBase, 0 VRAM, default ON]
    → optional HAK_GAL /v1/detect       [only if FIREWALL_HOST + WORLDBASE_FIREWALL_MCP=1]
    → fail-open if HAK_GAL down         [default — not a hard dependency]

HUD chat (🛡️ ON)
    → prompt_guard.slim_prompt_scan     [WorldBase, 0 VRAM, default ON]
    → optional HAK_GAL /v1/detect
    → fail-open if down
```

Do **not** run full HAK_GAL microservice fleet + qwen3:8b on a 16 GB GPU and expect reliability.

---

## Enable HAK_GAL (optional enrichment)

1. Start HAK_GAL orchestrator **lean** (orchestrator-only, `HIE_LITE_MODE=true`) — external repo.
2. In `backend/.env`:

```env
FIREWALL_HOST=localhost:8001
# WORLDBASE_FIREWALL_MCP=1          # optional second layer for MCP writes
```

3. Restart WorldBase: `.\start.ps1`

Slim guard works **without** `FIREWALL_HOST`.

---

## Environment variables

| Variable | Default | Effect |
|----------|---------|--------|
| `WORLDBASE_SLIM_GUARD` | `1` | WorldBase-native regex guard |
| `WORLDBASE_SLIM_GUARD_MCP` | `1` | Apply slim guard to MCP write tools |
| `FIREWALL_HOST` | unset | HAK_GAL target; empty = no HTTP bridge |
| `WORLDBASE_FIREWALL_MCP` | `0` | Optional HAK_GAL scan on MCP writes |
| `WORLDBASE_FIREWALL_MCP_FAIL_CLOSED` | `0` | `1` = block MCP when HAK_GAL down |
| `WORLDBASE_FIREWALL_RISK_THRESHOLD` | `0.7` | HAK_GAL fallback block threshold |
| `WORLDBASE_FIREWALL_TRACE` | `0` | `X-Logging: true` for decision_trace |
| `WORLDBASE_FIREWALL_SHADOW` | `0` | Log HAK_GAL would-block, never block |

---

## API (WorldBase)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/firewall/status` | Slim guard flags, pattern counts, optional HAK_GAL reachability |
| `GET /api/firewall/history` | In-memory decision ring (slim + HAK_GAL) |
| `POST /api/firewall/test` | Manual probe — slim guard first, then optional HAK_GAL |

**Operator script:** `.\scripts\firewall-probe.ps1` — slim-guard regression (12 checks, HAK_GAL optional WARN/SKIP). Does not require `:8001`.

---

## Roadmap

| Phase | Status | Scope |
|-------|--------|--------|
| **A** | Shipped | Session-aware chat bridge |
| **B** | Shipped | Slim MCP guard + optional HAK_GAL MCP gate |
| **C** | Planned | v2 abstention, outbound scan (optional) |
| **D** | Planned | Trust probe, shadow mode |

**Never** port full HAK_GAL into WorldBase.

---

## What it may help with (honest scope)

This is **not** marketed as enterprise LLM security. From local testing and design intent:

| Area | Slim guard (default) | Optional HAK_GAL |
|------|----------------------|------------------|
| MCP write tools | May block obvious jailbreak / tool-poisoning strings in JSON args | May add risk score when `:8001` is up |
| Chat (🛡️ ON) | Same baseline before Ollama | Optional second scan |
| Briefing / trust / Pi | No direct effect assumed | No direct effect assumed |
| VRAM | 0 | Full stack may conflict with qwen3 on 16 GB — measure on your GPU |

Regex rules are bypassable. Fail-open is default so WorldBase keeps working when HAK_GAL is down.

---

## Related

- Pick list — `research/HAK_GAL_PICK_LIST.md`
- MCP — [`docs/MCP.md`](MCP.md)
- 16 GB plan — `research/VRAM_16GB_DOCKER_GPU_SCHEDULER_PLAN.md`
