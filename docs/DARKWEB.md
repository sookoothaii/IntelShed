# Dark Web / Darknet OSINT Module (P8)

> WorldBase component for passive dark-web threat intelligence. No Tor relay is required for the default clearnet-engine mode; an optional Tor SOCKS5 proxy can be enabled for direct `.onion` indexing.

---

## Terminology

| Term | Meaning |
|------|---------|
| **Surface web** | Indexed, publicly reachable content (Google, News, normal HTTPS) |
| **Deep web** | Unindexed but legal content behind authentication or paywalls |
| **Darknet** | Anonymity overlay networks — **Tor**, I2P, Freenet. The "road". |
| **Dark web** | Sites and services hosted **on** darknets. The "traffic on the road". |
| **`.onion`** | Tor hidden-service address suffix. A `.onion` domain is part of the dark web. |

So: **`.onion` belongs to the dark web**, and the dark web is a subset of the darknet / deep-web ecosystem. WorldBase uses the terms interchangeably in UI labels, but the architecture is technically Tor-centric.

---

## What WorldBase does (and does not do)

**Does:**

- Query passive clearnet dark-web search engines (Ahmia, DarkSearch, etc.) without requiring a Tor relay.
- Match results against FtM entities (Organizations, Persons, Vessels, Companies, etc.).
- Ingest matched mentions as FtM `Mention` entities with `dataset="darkweb"`.
- Score source reliability as `0.3` (low) in the provenance table (P4).
- Surface results in the briefing digest, insight cards, and a dedicated HUD panel.
- Optionally route through a Tor SOCKS5 proxy for direct `.onion` scraping.

**Does not:**

- Crawl arbitrary `.onion` sites by default (no Tor dependency by default).
- Store or display abuse material — Ahmia's blacklist is respected; unsafe engines are gated behind opt-in flags.
- Perform illegal activity or credential stuffing — only passive search, no login attempts.

---

## Architecture

```
Operator query / FtM entity name
    → darkweb_bridge.search_darkweb()
    → parallel clearnet fan-out (Ahmia, DarkSearch, OnionLand) — one shared client
    → sequential Tor fan-out (Torch, Tor66, TorDex, Haystak, Not Evil) — fresh client per engine
      → fresh httpx client per request isolates Tor circuits
      → 10 s cooldown between Tor engines to avoid exit-node rate limits
    → deduplication by URL
    → optional: `_scrape_onion_page()` deep-scrapes `.onion` result pages
      → extracts crypto wallets, PGP keys, emails, IOCs, related .onion links
    → match_entities_to_darkweb() against FtM entities
    → ingest_results() → FtM Mention
    → briefing digest block (when enabled)
    → HUD DARK WEB panel + globe layer
```

### Backend files

| File | Role |
|------|------|
| `backend/darkweb_bridge.py` | Search, parsing, entity matching, ingestion, FastAPI routes |
| `backend/darkweb_parsers.py` | V4-58 engine-specific HTML parsers (BeautifulSoup4) for Torch, Tor66, TorDex, Haystak, Not Evil |
| `backend/breach_bridge.py` | Breach/credential-leak intelligence (HIBP + XposedOrNot + Pwned Passwords) |
| `backend/ingest/mappings/darkweb_mentions.yml` | YAML mapping for `Mention` schema ingest |
| `backend/ingest/schemas/darkweb_mentions.json` | JSON schema for mapping validation |
| `backend/connector_registry.py` | `darkweb` connector manifest + TTL |
| `backend/provenance.py` | Source reliability table entry `darkweb` = 0.3, `xposedornot` = 0.75 |
| `backend/config.py` | `WORLDBASE_DARKWEB_*`, `WORLDBASE_BREACH_*` flags |
| `backend/features.py` | Dynamic feature flag registration |
| `backend/routes/registry.py` | Router registration |
| `backend/mcp_server.py` | MCP tools: `worldbase_breach_status`, `worldbase_breach_check_password` |
| `backend/mcp_schema.py` | Output schemas for breach MCP tools |

### Frontend files

| File | Role |
|------|------|
| `frontend/src/components/DarkwebPanel.tsx` | DARK WEB tab / search panel |
| `frontend/src/hooks/layers/useDarkwebLayer.ts` | Globe markers for dark-web mentions |
| `frontend/src/lib/darkwebApi.ts` | API client for `/api/darkweb/*` |

---

## Search engines

### Default (clearnet, no Tor)

| Engine | Endpoint | Filtering | Notes |
|--------|----------|-----------|-------|
| **Ahmia** | `https://ahmia.fi/search/?q=` | Abuse material filtered | Tor Project-endorsed, safest default |
| **DarkSearch** | `https://darksearch.io/api/search` | Minimal | JSON API, rate-limited |

### Optional / Tor-proxy engines

| Engine | Requires Tor | Filtering | Notes |
|--------|--------------|-----------|-------|
| **Torch** | Yes | Minimal | Large index, 1M+ pages |
| **Tor66** | Yes | Category-curated | Directory + "Fresh Onions" feed |
| **OnionLand** | Yes | Minimal | Tor + I2P + clearnet blended results |
| **TorDex** | Yes | Minimal | Uncensored, large index |
| **Haystak** | Yes | Abuse-only | Deep historical index |
| **Not Evil** | Yes | None | Community-policed, availability varies |

All non-Ahmia engines are opt-in per engine and require an explicit `WORLDBASE_DARKWEB_ENGINES` list. They are not enabled by default.

### V4-58 Engine-specific HTML Parsers (shipped)

Each Tor engine has a dedicated BeautifulSoup4 parser in `backend/darkweb_parsers.py`, replacing the previous generic `_parse_tor_html()` heuristic. The parsers use engine-specific CSS selectors with fallback link extraction:

| Engine | Parser function | Layout | Pagination |
|--------|----------------|--------|------------|
| **Torch** | `parse_torch()` | `<div class="result">` with `<h3><a>`, `<div class="snippet">` | `page=N` |
| **Tor66** | `parse_tor66()` | `<tr class="result">` table rows with `<a href>` | `page=N` |
| **TorDex** | `parse_tordex()` | `<div class="result">` cards with `<h3><a>`, `<p class="desc">` | `page=N` |
| **Haystak** | `parse_haystak()` | `<div class="result">` with `<h4><a>`, `<p class="summary">` | `offset=N*20` |
| **Not Evil** | `parse_notevil()` | `<div class="result">` or `<div class="g">` with `<a href>`, `<div class="snippet">` | `start=N*10` |

Each parser includes:
- URL redirect unwrapping (`/redirect?url=...`, `/url?q=...`, `/url?u=...`)
- Deduplication by URL
- `.onion` URL validation
- Fallback to generic `<a>` link extraction when structured selectors fail
- Consistent output format: `{title, url, snippet, engine, first_seen}`

Integration: `darkweb_bridge._search_tor_engine()` calls `darkweb_parsers.parse_engine_html()` first, falling back to `_parse_tor_html()` if the dedicated parser returns empty or raises.

---

## Configuration

`backend/.env`:

```env
# Master toggle (default off, opt-in)
WORLDBASE_DARKWEB=1

# Comma-separated engines. Ahmia + darksearch work without Tor.
WORLDBASE_DARKWEB_ENGINES=ahmia,darksearch

# Optional: route all .onion traffic through a Tor SOCKS5 proxy.
# WORLDBASE_DARKWEB_TOR_PROXY=socks5://127.0.0.1:9050

# Cache and result limits
WORLDBASE_DARKWEB_CACHE_SEC=3600
WORLDBASE_DARKWEB_MAX_RESULTS=50

# Include in briefing digest
WORLDBASE_BRIEFING_DARKWEB=1
```

Feature flags:

```env
WORLDBASE_DARKWEB=1
WORLDBASE_BRIEFING_DARKWEB=1
WORLDBASE_RANSOMWARE=1
WORLDBASE_BRIEFING_RANSOMWARE=1
WORLDBASE_BREACH=1
WORLDBASE_BRIEFING_BREACH=1
WORLDBASE_HIBP_API_KEY=          # optional — XposedOrNot fallback works without key
WORLDBASE_BREACH_CACHE_SEC=3600
```

---

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/darkweb?q=...` | Cached search envelope |
| `GET` | `/api/darkweb/search?q=...` | Raw search results, no cache |
| `GET` | `/api/darkweb/status` | Bridge status, configured engines |
| `GET` | `/api/darkweb/engines` | List all available engines + Tor requirements |
| `POST` | `/api/darkweb/ingest` | Ingest results for a query into FtM |
| `POST` | `/api/darkweb/match` | Match a list of results against FtM entities |
| `GET` | `/api/darkweb/entities?q=...` | Search + match + return linked entity IDs |
| `GET` | `/api/darkweb/mentions` | List already ingested `Mention` entities |
| `POST` | `/api/darkweb/scrape` | Scrape a single `.onion` URL via Tor proxy |
| `POST` | `/api/darkweb/deep_search` | Search + deep-scrape top `.onion` results |
| `GET` | `/api/darkweb/ransomware/groups` | Tracked ransomware groups + last known URLs |
| `GET` | `/api/darkweb/ransomware/victims` | Parsed ransomware victim-list metadata |
| `POST` | `/api/darkweb/ransomware/refresh` | Force refresh of Ransomwatch URL tracker |
| `POST` | `/api/darkweb/ransomware/ingest` | Ingest selected victims as FtM `Event` entities |
| `GET` | `/api/darkweb/breach/status` | Breach monitor status (provider, enabled flags, monitor count) |
| `POST` | `/api/darkweb/breach/check` | Check email for known breaches (HIBP or XposedOrNot fallback) |
| `POST` | `/api/darkweb/breach/password` | Check password via Pwned Passwords k-anonymity (no key needed) |
| `POST` | `/api/darkweb/breach/monitor` | Add email to breach monitoring table |
| `GET` | `/api/darkweb/breach/monitors` | List monitored emails |
| `DELETE` | `/api/darkweb/breach/monitor/{id}` | Remove a monitored email |
| `POST` | `/api/darkweb/breach/refresh` | Refresh all monitored emails for new breaches |

### Routing modes

Most search/ingest/entity endpoints accept a `mode` parameter:

- **`auto`** (default): Clearnet engines (Ahmia, DarkSearch, OnionLand) use a direct connection, Tor-only engines use the configured Tor proxy.
- **`clear`**: Only clearnet engines run; Tor-required engines are skipped.
- **`tor`**: All selected engines are routed through the Tor proxy for session-level anonymity.

---

## Entity extraction

When a Tor proxy is configured, the bridge can optionally deep-scrape `.onion` pages and extract:

- **Cryptocurrency wallets** (BTC, ETH, XMR, LTC addresses)
- **PGP public keys** and fingerprints
- **Email addresses** and usernames
- **Additional `.onion` links** (recursive discovery)
- **Hashes / IOCs** (MD5, SHA256, CVEs)

Extracted entities are linked to the originating `Mention` via `seeAlso` / `source` properties.

---

## Briefing integration

When `WORLDBASE_BRIEFING_DARKWEB=1`:

- The autopilot runs a dark-web search for the operator region and high-value entities once per `WORLDBASE_BRIEFING_INTERVAL`.
- Matched mentions are added to the 24h digest as a `DARK WEB` block with severity `high` if the mention is tied to a known entity, otherwise `medium`.
- Insight cards of type `darkweb_mention` are generated when corroborated by at least one other source or repeated across engines.

When `WORLDBASE_BRIEFING_RANSOMWARE=1`:

- Recent ransomware victims are pulled from `ransomware.live` and `ransomlook`.
- A `RANSOMWARE VICTIMS` block (max 5 lines) is injected into the 24h briefing prompt.
- Victims are prioritised: FTM-correlated entities first, then operator region (ASEAN), then APAC, then global.
- Correlated victims automatically generate a `ransomware` watch item with a 72-hour horizon.
- Provenance metadata is attached with `source: darkweb_ransomware` and low integrity (0.3).

When `WORLDBASE_BRIEFING_BREACH=1`:

- All monitored emails are checked for new breaches during each briefing cycle.
- A `BREACH / CREDENTIAL-LEAK` block (max 5 lines) is injected into the 24h briefing prompt.
- Only breaches flagged as `is_new=True` (not seen in previous checks) are included.
- Watch items are generated with `critical` severity when password data classes are involved, otherwise `high`.
- Provider is indicated in the digest: `hibp` (full metadata) or `xposedornot` (breach names only).

---

## Frontend UX

- **DATA → DARK WEB** tab: search any query, view results, trigger ingest, see matched entities.
- **Globe layer `darkweb`**: markers for mentions that have geolocation hints (rare; most are global). Falls back to a count badge.
- **SITUATIONS board**: dark-web insight cards with severity and entity links.

---

## OPSEC & guardrails

1. **Passive only** — no credentials, no login attempts, no automated posting.
2. **Ahmia-first default** — abuse-filtered, no Tor required.
3. **Engine opt-in** — uncensored engines require explicit `WORLDBASE_DARKWEB_ENGINES` configuration.
4. **Rate limiting** — each engine has a per-query timeout and the connector cache prevents hammering upstream APIs.
5. **No PII storage** — only titles, snippets, URLs, and extracted public identifiers are stored; no user content or private messages.
6. **Audit log** — all dark-web queries are logged via `structured_log` with redaction.

---

## References

- [Ahmia](https://ahmia.fi/) — Tor hidden service search
- [DarkSearch](https://darksearch.io/) — SOC-oriented dark web search API
- [darkdump](https://github.com/josh0xA/darkdump) — multi-engine dark web OSINT CLI
- [OnionSearch](https://github.com/megadose/OnionSearch) — Python dark web search library
- [voidaccess](https://github.com/KatrielMoses/voidaccess) — self-hosted dark web threat-intel pipeline
- [dark-web-scraper](https://github.com/shellytrifonov/dark-web-scraper) — Dockerized .onion scraping + entity extraction

---

## Ransomware leak site intelligence (P8.6)

Ransomware victim lists are a high-signal OSINT source for corporate risk and regional impact. The WorldBase darkweb module tracks them **passively**: only metadata (victim name, date, group, claimed data size) is ingested; leaked files themselves are never downloaded or stored.

### Data sources

- **Ransomwatch** (`github.com/joshhighet/ransomwatch`) — community-maintained JSON of active group `.onion` URLs.
- **Ransomware Tracker** (`ransomwaretracker.abuse.ch`) — clearnet JSON with onion references.
- **Direct `.onion` victim-list pages** — parsed via the configured Tor proxy when available.

### Supported groups (2026)

| Group | Pattern | FtM mapping |
|-------|---------|-------------|
| The Gentlemen | HTML table: `.victim-name`, `.date`, `.deadline` | `Event` (type: ransomware) |
| Qilin | HTML table: victim name, exfil size, date | `Event` |
| Akira | Onion blog: victim list + screenshots metadata | `Event` |
| LockBit (fragment) | Rebrand/fragmented domains; parsed if reachable | `Event` |
| Ransom House | Data-theft list | `Event` |
| Everest | Data-leak + ransomware list | `Event` |

### API

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/darkweb/ransomware/groups` | List tracked groups and their last known URLs |
| `GET` | `/api/darkweb/ransomware/victims?group=...&limit=...` | Query parsed victims (live fetch + cached) |
| `POST` | `/api/darkweb/ransomware/refresh` | Force refresh of Ransomwatch URL tracker |

### OPSEC rules

- Never download leaked data, internal files, or victim documents.
- Only extract public victim-list metadata (name, date, group, claimed data volume).
- Use a dedicated Tor proxy; never browse leak sites from a non-anonymized connection.
- Source reliability for ransomware metadata in provenance is `0.25` (unverified criminal claims).

---

## Quick verification

With the backend running (`http://127.0.0.1:8002`) and `WORLDBASE_DARKWEB=1`:

```bash
# List engines
curl -s http://127.0.0.1:8002/api/darkweb/engines

# Search Ahmia + DarkSearch
curl -s "http://127.0.0.1:8002/api/darkweb/search?q=WorldBase&engines=ahmia,darksearch"

# Scrape a single .onion page (requires Tor proxy)
curl -s -X POST http://127.0.0.1:8002/api/darkweb/scrape \
  -H "Content-Type: application/json" \
  -d '{"url":"http://abc234abc234abcd.onion/page"}'

# Search + deep-scrape top .onion results
curl -s -X POST http://127.0.0.1:8002/api/darkweb/deep_search \
  -H "Content-Type: application/json" \
  -d '{"q":"WorldBase","engines":"ahmia","limit":10,"scrape_limit":3,"mode":"auto"}'

# Route all engines through Tor for session anonymity
curl -s "http://127.0.0.1:8002/api/darkweb/search?q=WorldBase&engines=ahmia,torch&mode=tor"

# Ransomware intelligence — tracked groups and parsed victims
curl -s http://127.0.0.1:8002/api/darkweb/ransomware/groups
curl -s "http://127.0.0.1:8002/api/darkweb/ransomware/victims?group=the_gentlemen&limit=10"
```

All endpoints are fail-soft: missing Tor proxy, disabled darkweb, or unreachable engines return JSON with an `error` field instead of crashing.

---

## Roadmap within P8

| Phase | Feature | Status |
|-------|---------|--------|
| P8.1 | Ahmia + DarkSearch clearnet search, entity matching, FtM ingest | ✅ Shipped |
| P8.2 | Engine registry (8 engines); Tor proxy with fresh-client circuit isolation; sequential Tor engine fan-out + parallel clearnet | ✅ Shipped |
| P8.3 | Entity extraction regexes (crypto, PGP, emails, IOCs, .onion) | ✅ Shipped |
| P8.4 | Briefing digest block + insight cards + frontend panel + globe layer | ✅ Shipped |
| P8.5 | Tor `.onion` deep scraping (page content extraction) via `POST /api/darkweb/scrape` and `POST /api/darkweb/deep_search` | ✅ Shipped |
| P8.6 | Ransomware leak site intelligence (Ransomwatch URL tracker + victim-list parsers) | In Progress |
| P8.7 | Engine-specific HTML parsers (Torch, Tor66, OnionLand, etc.) | Planned |
| P8.8 | Breach / credential-leak intelligence mode (HIBP + XposedOrNot fallback) | ✅ Shipped |

---

## Appendix — related OSINT capability landscape

The dark web module is one piece of a broader OSINT stack. The following capabilities are **not** part of P8 but are documented here as research-backed expansion candidates.

### K1 — Breach Intelligence Bridge (HIBP + XposedOrNot) — ✅ Shipped as P8.8

Privacy-first credential-leak checks for monitored emails. Implemented in `backend/breach_bridge.py`.

- **HIBP API v3** (primary, with `WORLDBASE_HIBP_API_KEY`): full breach metadata (name, date, data classes, pwn count, verification flags).
- **XposedOrNot API** (free fallback, no key needed): `GET https://api.xposedornot.com/v1/check-email/{email}` — returns breach names only. 100 req/day per IP, no auth required. Automatically used when no HIBP key is configured.
- **Pwned Passwords k-anonymity** (always free, no key): `POST /api/darkweb/breach/password` — only first 5 chars of SHA1 hash sent.
- **Storage:** SHA1 hash + base64-encoded email in SQLite `breach_monitors` table; breach history in `breach_checks` table. Never plaintext emails in DB.
- **Briefing integration:** `gather_breach_briefing()` → `breach_digest` → BREACH block in `briefing_prompt.py`; watch items for new breaches with `critical` severity when password data classes are involved.
- **MCP tools:** `worldbase_breach_status` (shows provider, monitors, config), `worldbase_breach_check_password` (k-anonymity password check).
- **Rate limit:** 1.5 s between HIBP requests; XposedOrNot has 2 req/s API-side limit.
- **Config:** `WORLDBASE_BREACH=1`, `WORLDBASE_BRIEFING_BREACH=1`, `WORLDBASE_HIBP_API_KEY` (optional — XposedOrNot fallback works without key).
- **Tests:** `test_breach_bridge.py` — 35 tests (30 original + 5 XposedOrNot fallback); `test_mcp_tools_new.py` — 4 breach MCP tests. All pass.
- **Live verified (2026-07-01):** All 7 endpoints tested against live backend — status (provider=xposedornot), password check (compromised=True for common passwords), email check (XposedOrNot fallback), monitor CRUD, refresh.

### K2 — STIX/TAXII Export (WorldBase as threat-intel producer)

Export FtM entities and briefings as STIX 2.1 bundles / TAXII 2.1 collections for MISP/OpenCTI.

- **Mapping:** `Person` (sanctions list) → `ThreatActor`; `Person` (otherwise) → `Identity`; `Vessel` → `Infrastructure` (`vessel`); `Event` → `Incident`; `Mention` → `Indicator` or `Note`; `Breach` → `Incident`.
- **Report:** Each briefing becomes a STIX `Report` with `object_refs` to referenced entities.
- **Endpoint:** `GET /api/taxii2/collections/{id}/objects/` with pagination and `since` filter.
- **Dependency:** `stix2` Python library (pure Python, no VRAM).

### K3 — Telegram SOCMINT Bridge (SEA coverage)

Passive monitoring of public Telegram channels for Southeast Asia situational awareness.

- **Scope:** Only allow-listed public channels; no private groups, no user-list scraping.
- **Implementation:** `telethon` async MTProto client.
- **Output:** Geo-tagged posts → FtM `Event`; text posts → FtM `Mention` (`source: telegram`).
- **Guardrails:** Content hashes stored, not full message text; 12 s between channels to avoid `FloodWaitError`; 90-day retention.
- **Dependency:** `telethon`; requires Telegram `api_id` / `api_hash` from https://my.telegram.org.

### K4 — Satellite Imagery Change Detection (STAC + COG)

Windowed read of Sentinel-2 Cloud-Optimized GeoTIFFs for AOI change detection.

- **Use case:** Port expansion, deforestation, border activity, disaster damage.
- **Algorithm:** NDVI / NDWI band differencing between two cloud-free scenes.
- **Input:** STAC search → best cloud-cover item per epoch → windowed COG read.
- **Output:** GeoJSON anomaly features with pixel count and confidence.
- **Dependency:** `rasterio` + GDAL (wheels available); computationally cheap (0 VRAM).

| Capability | Impact | Effort | Dependencies |
|------------|--------|--------|--------------|
| K1 Breach Intel | High (privacy-critical) | ✅ Shipped (P8.8) | `httpx` (already used) |
| K2 STIX/TAXII | High (platform maturity) | 2–3 days | `stix2` (new) |
| K3 Telegram | Very high (SEA coverage) | 2–3 days | `telethon` (new) |
| K4 Satellite CD | Medium (GEOINT wow) | 3–4 days | `rasterio` + GDAL |
