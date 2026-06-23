# OSINT external toolkit

WorldBase keeps **live feeds in the stack** (globe layers, briefing, fusion). The **OSINT → REFERENCE** tab and **EXTERNAL OSINT** block in the globe detail modal open vetted third-party UIs in a new tab — no scraping, no briefing ingest.

UI: http://localhost:5176 → **OSINT** → **REFERENCE** (or click any globe entity → modal).

---

## Architecture

```
Native (API / layer)     Complement (deep-link UI)     Meta (indexes)
──────────────────     ─────────────────────────     ───────────────
/api/aircraft          ADS-B Exchange, FR24          OSINT Framework
/api/maritime          MarineTraffic, VesselFinder   Bellingcat
/api/wildfires (FIRMS) NASA Worldview, FIRMS map
/api/outages (IODA)    IODA dashboard, CF Radar
/api/stac              Copernicus / Sentinel Hub EO
/api/insights          LiveUAMap, ACLED, ISW
```

Context-aware URLs are built from **lat/lon**, **ICAO**, **MMSI**, **domain**, **IP**, **email**, or **username** parsed from the globe modal or the REFERENCE context builder.

---

## Catalog size

| Category | Examples |
|----------|----------|
| **WORLDBASE NATIVE** | Aircraft, maritime, STAC, outages, GDELT, insights, FIRMS, GIBS |
| **AIR** | ADS-B Exchange, OpenSky, Flightradar24, FlightAware |
| **SEA** | MarineTraffic, VesselFinder, Equasis |
| **CONFLICT** | LiveUAMap, ACLED, ISW, S2U (optional env) |
| **IMAGERY** | NASA Worldview, Copernicus, Google Earth, Zoom Earth, YouTube geofind |
| **INFRA** | IODA dashboard, Cloudflare Radar, Open Railway Map |
| **COMMS** | Broadcastify, WebSDR, KiwiSDR, Radio Garden, SIGID |
| **CYBER** | crt.sh, Shodan, Censys, URLScan, Wayback, WiGLE |
| **IDENTITY** | WhatsMyName, ICANN, HIBP |
| **META** | OSINT Framework, Bellingcat, IntelTechniques, SpiderFoot |

Implementation: `frontend/src/lib/osintToolkit.ts` + `osintToolkitCatalog.ts`.

---

## Backend enrichments (Quick Tools)

| Endpoint | Extra |
|----------|--------|
| `GET /api/osint/domain/{domain}` | DNS A/MX + **crt.sh** subdomains (`cert_names`, `crt_sh_url`) |
| `GET /api/osint/email/{email}` | MX/disposable + **HIBP** breach names when `HIBP_API_KEY` set; always `breach_check_url` |

Requires `X-API-Key` when `WORLDBASE_API_KEY` is set (same as other OSINT routes).

Optional env:

| Variable | Where | Purpose |
|----------|-------|---------|
| `HIBP_API_KEY` | `backend/.env` | Breach names on email lookup |
| `VITE_S2U_MAP_URL` | `frontend/.env` | ArcGIS Experience deep-link |

---

## HUD session persistence

Tab and sub-tab state survives **reload within the same browser tab** via `sessionStorage` (`frontend/src/lib/hudSessionState.ts`):

- Main nav view, split view, FULL SITUATION / Situations overlays, map mode
- DATA sub-tab, NEWS filter, OSINT mode (TOOLS / REFERENCE / FLOWSINT)
- Globe telemetry preset and layer toggles

Chat keys, OSINT pins, and briefing language stay in `localStorage`.

---

## Do not ingest

LiveUAMap, Downdetector, Flightradar24, Shodan, MarineTraffic, etc. are **link-out only** — keeps licenses and briefing determinism clean.
