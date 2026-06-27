# Optional features

WorldBase works out of the box with free feeds and local Ollama. These optional features add capability when you have the keys or hardware.

---

## Slim prompt guard (no HAK_GAL required)

A small regex layer (`backend/prompt_guard.py`, 0 VRAM) may reduce obvious abuse on **MCP write tools** and on **chat** when the 🛡️ toggle is on. It is **not** a substitute for API keys or network isolation, and it does not change briefing quality or trust scores.

HAK_GAL on port `:8001` is an **optional** second opinion when a lean orchestrator happens to be running — full stack alongside Ollama on 16 GB VRAM is assumed unreliable unless you measure otherwise. Details → [`docs/FIREWALL.md`](FIREWALL.md).

```env
# backend/.env — defaults; slim guard on without FIREWALL_HOST
WORLDBASE_SLIM_GUARD=1
WORLDBASE_SLIM_GUARD_MCP=1
```

HUD: chat 🛡️ toggle (optional slim guard) · API: `GET /api/firewall/status`, `GET /api/firewall/history`

---

## Live maritime AIS (Thailand corridor)

Free key at [aisstream.io](https://aisstream.io) → `backend/.env`:

```env
AISSTREAM_API_KEY=your-key
# WORLDBASE_MARITIME_AISSTREAM=1          # background WebSocket collector (default on when key set)
# WORLDBASE_MARITIME_COLLECT_SEC=30       # one-shot snapshot when collector off
# WORLDBASE_MARITIME_STREAM_STALE_SEC=1800
# WORLDBASE_MARITIME_MAX_VESSELS=800
# WORLDBASE_MARITIME_REGIONS=malacca,laem_chabang,bangkok_port,phuket,singapore  # default when WORLDBASE_OPERATOR_REGION=thailand
```

Restart backend. The API reads a **background AISstream buffer** (non-blocking); JSON includes `stream_connected` and `stream_buffer`. Without the key, `/api/maritime` falls back to MyShipTracking or demo fleet.

---

## Dark Web / Darknet OSINT (no extra keys)

Passive `.onion` search via clearnet APIs — no Tor relay required for the default engines.

```env
WORLDBASE_DARKWEB=1
WORLDBASE_DARKWEB_ENGINES=ahmia,darksearch
WORLDBASE_BRIEFING_DARKWEB=1
# Optional: route .onion requests through a local Tor SOCKS5 proxy
# WORLDBASE_DARKWEB_TOR_PROXY=socks5://127.0.0.1:9050
```

Restart backend. The DARK WEB panel appears under **DATA → DARK WEB**. The bridge searches for operator queries and high-value FtM entities, matches results against the entity graph, and ingests them as `Mention` entities. It feeds a dedicated digest block and Situation cards when `WORLDBASE_BRIEFING_DARKWEB=1`. Details, engine list, and OPSEC guardrails → [`docs/DARKWEB.md`](DARKWEB.md).

---

## Identity OSINT (email / username enumeration)

Passive existence checks across 92 social platforms — no credential stuffing, no profile scraping, only HTTP status checks.

```env
WORLDBASE_IDENTITY_OSINT=1
WORLDBASE_BRIEFING_IDENTITY=1
# WORLDBASE_IDENTITY_OSINT_RATE_LIMIT_SEC=2     # 2s between checks per platform
# WORLDBASE_IDENTITY_OSINT_MAX_PLATFORMS=50     # cap per lookup
# WORLDBASE_IDENTITY_OSINT_CACHE_SEC=86400      # 24h cache TTL
```

Restart backend. API: `GET /api/osint/identity?email=...` or `?username=...` → platform existence list. `POST /api/osint/identity/ingest?person_id=...` links results to FtM `Person` entities via `UserAccount` + `owns` edge. All lookups logged in SQLite audit table (`GET /api/osint/identity/audit`). Guardrails: opt-in only, rate-limited (2s/platform, 50 cap, 30s pause every 50), 24h cache, no PII stored, fail-soft.

---

## Ransomware intelligence

Ransomware.live + RansomLook leak-site monitoring → FtM `Event` mapping, briefing block, watch items. Passive metadata only — no leaked files downloaded.

```env
WORLDBASE_RANSOMWARE=1
WORLDBASE_BRIEFING_RANSOMWARE=1
```

---

## Telegram SOCMINT

Allow-listed public channels → SEA scoring, FtM `Event`/`Mention` ingest, DATA → TELEGRAM panel. Details → [`docs/TELEGRAM.md`](TELEGRAM.md).

```env
WORLDBASE_TELEGRAM=1
WORLDBASE_BRIEFING_TELEGRAM=1
WORLDBASE_TELEGRAM_CHANNELS=channel1,channel2
```

---

## Thailand briefing enrichment (no extra keys)

| Endpoint | Role |
|----------|------|
| `GET /api/cams/haze` | CAMS dust / AOD for Bangkok, Chiang Mai, ASEAN cities |
| `GET /api/humanitarian` | HDX datasets (Myanmar border, displacement) |
| `GET /api/gdelt/pulse/local` | Operator-region GDELT headlines |
| `GET /api/chat/context?q=...` | Query-aware chat context enrichment (smoke test endpoint) |

These feed the 24h security digest LOCAL / REGION blocks automatically. The chat context enricher (`backend/chat_context_enricher.py`) extracts entities from user queries and filters live feed caches (quakes, GDELT local, fusion hotspots) to inject relevant data into chat context, along with a synthesis directive (Structured Analytic Techniques, evidence weighting, red-team review, actionable intelligence).

---

## Offline maps (PMTiles)

```powershell
# Regional stack (~500 MB) — default for fast MAP load
.\scripts\download-pmtiles.ps1 -Region stack

# Full planet (~130 GB, resumable BITS)
.\scripts\download-pmtiles.ps1 -Region world-full -Force

# Optional ZXY MVT tiles (experimental Globe MVT layer)
.\scripts\start-pmtiles-serve.ps1   # http://127.0.0.1:8088
```

In **MAP** view, pick the archive in the dropdown. Default is **`thailand`** for speed; select **`planet_full`** for global offline detail when the ~130 GB file is present.

---

## Split view

**◫ SPLIT** in the HUD shows Globe (left) and Map (right) with linked camera sync.

- Both panes stay **mounted** (no remount on toggle — MapLibre keeps its state).
- CSS **grid** layout (`hud-main--split`) — no overlapping absolute layers over the WebGL canvas.
- On the globe half, heavy chrome (telemetry, controls, timeline) is hidden for a larger interactive area.
- First split open may briefly load PMTiles on the right; later toggles are instant.

Use for tactical overviews (3D feeds) + precise 2D basemap side by side.

---

## Satellite change detection (K4)

Sentinel-2 L2A COG window-read — NDVI/NDWI change detection, GeoJSON anomaly polygons, DATA → SATELLITE panel.

---

## Maritime anomaly detection (P7)

AIS trajectory storage + behavioural anomaly detection (speed variance, AIS gaps, night port visits, risk zone proximity). `GET /api/maritime/anomalies` → anomaly list with features.

---

## Entity resolution

Per-dataset dedupe → cross-dataset link (Splink), dual-pipeline (batch train + predict), human-in-the-loop labelling. `WORLDBASE_ENTITY_RESOLUTION_PIPELINE=two_stage` (opt-in).

---

## Multi-agent orchestrator (P3+)

5-agent orchestrator (Coverage → Retrieval → Spatial → Corroboration → Synthesis), rule-based dispatcher, 0 VRAM. `WORLDBASE_AGENT_ORCHESTRATOR=1` (opt-in).
