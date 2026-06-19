---
name: worldbase-globe
description: >-
  Debug and verify the Cesium globe, terrain fallback, click-to-detail modals,
  traffic cams, and webcam streams. Use when modifying Globe.tsx,
  GlobeDetailModal.tsx, cesiumTerrain.ts, hooks/layers/, traffic_bridge.py,
  webcam_bridge.py, or when the user reports blank globe, Ion 503/401, wrong
  click modal, weather dots mistaken for cameras, or missing LIVE FEED iframe.
---

# WorldBase Globe

Deep reference: [`docs/GLOBE.md`](../../docs/GLOBE.md). Visual checks: use `worldbase-ui-smoketest` after frontend changes.

## When to use

- Globe blank, flat ellipsoid only, or Ion token overlay
- Click opens text-only modal instead of **LIVE FEED** with iframe
- Thailand weather grid dots confused with traffic/webcam markers
- Traffic cam JPEG proxy or Windy embed fails
- Split-view camera sync regression

## Key files

| Area | Path |
|------|------|
| Globe + focus | `frontend/src/components/Globe.tsx` |
| Detail modal | `frontend/src/components/GlobeDetailModal.tsx` |
| Terrain fail-soft | `frontend/src/lib/cesiumTerrain.ts` |
| Traffic layer | `frontend/src/hooks/layers/useTrafficCamsLayer.ts` |
| Traffic API | `backend/traffic_bridge.py` |
| Webcams API | `backend/webcam_bridge.py` |
| Webcam UI | `frontend/src/components/WebcamSection.tsx`, `WebcamStreamPanel.tsx` |

## Diagnostics (run, do not guess)

### Backend feeds
```powershell
Invoke-RestMethod http://127.0.0.1:8002/api/health/ping
Invoke-RestMethod 'http://127.0.0.1:8002/api/traffic/cams?scope=regional'
Invoke-RestMethod http://127.0.0.1:8002/api/webcams
```

### Ion token (replace TOKEN with `VITE_CESIUM_ION_TOKEN`)
```powershell
Invoke-RestMethod "https://api.cesium.com/v1/assets/1/endpoint?access_token=TOKEN"
```
Expect JSON with `url` and `accessToken` — not 401.

### Browser (if frontend up)
- CDP: `window.__cesiumViewer ? "ok" : "no-viewer"`
- Console: `[WorldBase] … ellipsoid fallback` means Ion failed but globe should still render imagery

## Expected click behavior

| Click target | Modal badge | Live content |
|--------------|-------------|--------------|
| Entity (aircraft, quake, vessel, …) | **GLOBE INTEL** | Metadata + related entities |
| WEATHER grid cell | **GLOBE INTEL** | Temp/wind/rain + Windy link |
| TRAFFIC CAMS marker (Singapore) | **LIVE FEED** | JPEG via `/api/traffic/cams/{id}/frame` |
| DATA → WEBCAMS cam | Switches to globe + **LIVE FEED** | Windy iframe |

**WEATHER** dots in Thailand are not cameras. **TRAFFIC CAMS** are Singapore-only until iTIC token is set.

## Manual UI verification

1. GLOBE → **TRAFFIC CAMS** → Singapore → click marker → live image in modal.
2. DATA → WEBCAMS → click cam with coordinates → globe + stream modal.
3. GLOBE → **WEATHER** → click Thailand dot → weather stats (not a camera).

## Quality standards

- Restart Vite after changing `frontend/.env` (Ion token).
- Transient Ion CDN 503 in DevTools is not always a missing token — verify endpoint above.
- After substantive globe/modal changes, run `worldbase-ui-smoketest` or at minimum `.\scripts\smoke-test.ps1`.
