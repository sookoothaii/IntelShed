# Globe — click-to-detail UX

The Cesium globe is the **primary interaction surface**: every marker with a `kind` property opens a detail modal with deeper context, live feeds where available, and **ASK AI**.

UI: http://localhost:5176 → **GLOBE** tab.

---

## Detail modal

| Trigger | Modal | Live content |
|---------|-------|--------------|
| Click any globe entity (aircraft, quake, vessel, …) | **GLOBE INTEL** | Metadata lines + related entities |
| Click **WEATHER** grid cell | **GLOBE INTEL** | Temp / wind / rain + **OPEN WINDY AT POINT** |
| Click **TRAFFIC CAMS** marker (Singapore) | **LIVE FEED** | JPEG stream via `/api/traffic/cams/{id}/frame` |
| **DATA → WEBCAMS** → click a cam | Switches to globe + **LIVE FEED** | Windy iframe embed |
| Focus from DATA / SITUATIONS / FULL SITUATION | Globe flies to point + modal | Depends on `kind` |

**Files:** `frontend/src/components/GlobeDetailModal.tsx`, `Globe.tsx` (`selectEntity`, `focusOn`).

Close modal (✕ or backdrop): globe stays at the location; camera does not reset.

---

## Weather vs traffic vs webcams

Operators in **Thailand** often see coloured dots labelled `28°` / `0.0mm` — these are **Windy weather grid cells**, not cameras.

| Layer | Toggle | Region (default) | Click result |
|-------|--------|------------------|--------------|
| **WEATHER** | LAYERS → ENV → WEATHER | Operator grid (`WORLDBASE_OPERATOR_REGION=thailand`) | Weather detail + Windy link |
| **TRAFFIC CAMS** | LAYERS → TRAFFIC CAMS or preset **OSINT** | Singapore (~90 cams, data.gov.sg) | Live road camera image |
| **Webcams** | DATA → WEBCAMS (not a globe layer) | Windy nearby + YouTube embeds | Globe modal with Windy player |

Thailand road cameras (iTIC) are planned — set `ITIC_API_TOKEN` when archive access is available.

---

## Traffic cameras API

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/traffic/cams?scope=regional\|global\|all` | Normalized camera list |
| GET | `/api/traffic/cams/{id}` | Single cam; `?refresh=1` refreshes image URL |
| GET | `/api/traffic/cams/{id}/frame` | JPEG proxy (CORS / hotlink bypass) |
| GET | `/api/traffic/cams/status` | Source availability |

**Backend:** `backend/traffic_bridge.py` · **Layer:** `frontend/src/hooks/layers/useTrafficCamsLayer.ts`

---

## Webcams API

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/webcams` | List; `?category=nature` etc. |
| GET | `/api/webcams/{id}` | Fresh Windy embed URL (tokens expire) |

Requires `WINDY_WEBCAM_API_KEY` in `backend/.env` for full Windy catalogue. Without key: curated YouTube live embeds only.

**Backend:** `backend/webcam_bridge.py` · **UI:** `WebcamSection.tsx` → `WebcamStreamPanel.tsx`

---

## Cesium Ion terrain

| Variable | Where | Purpose |
|----------|-------|---------|
| `VITE_CESIUM_ION_TOKEN` | `frontend/.env` | World Terrain, OSM 3D buildings, optional photorealistic tiles |

Token is **client-side** (bundled by Vite). Restrict domains in the [Ion console](https://ion.cesium.com/tokens). Restart Vite after changing `frontend/.env`.

**Fail-soft:** `frontend/src/lib/cesiumTerrain.ts` — if Ion init fails or terrain tiles return repeated 503/401, the globe switches to **ellipsoid fallback** (flat globe, imagery still works). Console: `[WorldBase] … ellipsoid fallback`.

Transient `503` on `assets.ion.cesium.com` in DevTools is usually **Ion CDN**, not a missing token. Verify:

```powershell
# Replace TOKEN with your VITE_CESIUM_ION_TOKEN value
$ep = Invoke-RestMethod "https://api.cesium.com/v1/assets/1/endpoint?access_token=TOKEN"
# Expect JSON with url + accessToken — not 401
```

---

## Verification

```powershell
.\scripts\smoke-test.ps1
Invoke-RestMethod http://127.0.0.1:8002/api/traffic/cams?scope=regional
Invoke-RestMethod http://127.0.0.1:8002/api/webcams
```

**Manual UI**

1. GLOBE → enable **TRAFFIC CAMS** → fly to Singapore → click orange marker → live image in modal.
2. DATA → WEBCAMS → click any cam with coordinates → globe + Windy stream modal.
3. GLOBE → **WEATHER** on → click Thailand grid dot → weather stats (not a camera).

---

## INTEL (FtM globe layer) {#intel-ftm-globe-layer}

Geolocated **FollowTheMoney** entities from the local DuckDB store (`entities.duckdb`) — same graph as DATA → INTEL, plotted on the globe.

| Item | Detail |
|------|--------|
| HUD toggle | Telemetry → **INTEL** group → **INTEL** (layer key `intelFt`) |
| Presets | **OSINT** and **FULL** enable `intelFt` by default; **OVERVIEW** off |
| Count | Shows `—` until layer is on and FtM query completes (~2 s); then entity count (e.g. 128) |
| Click | Opens **GLOBE INTEL** modal — schema, id, datasets, last_seen |
| API | `GET /api/intel/entities?geolocated=1&limit=250&window_hours=24` |
| Backend | `backend/ftm_store.py` → `entities_for_briefing()` |
| Frontend | `frontend/src/hooks/layers/useIntelLayer.ts` |

**Agent Bus:** MCP `worldbase_globe_toggle_layer` accepts `intelFt` as a layer key when Agent Bus is enabled.

**Verify:**

```powershell
Invoke-RestMethod 'http://127.0.0.1:8002/api/intel/entities?geolocated=1&limit=5'
# Expect count > 0 when FtM store has recent geolocated entities (GET /api/health → ftm.ready)
```
