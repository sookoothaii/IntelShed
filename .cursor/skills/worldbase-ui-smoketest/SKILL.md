---
name: worldbase-ui-smoketest
description: Visual smoke test of the WorldBase HUD via the cursor-ide-browser MCP. Use after frontend changes (App.tsx, Globe.tsx, hooks/layers/, hud.css) or when the user asks to verify the UI renders correctly.
---

# WorldBase UI Smoke Test (Browser MCP)

`npm run build` catches TypeScript errors but **not** visual regressions, layout breaks, runtime React errors, or Cesium init failures. This skill drives the actual UI in a Cursor-controlled browser tab.

## Pre-conditions
- Frontend reachable at http://localhost:5176 (run `.\start.ps1` if not)
- Cesium Ion token in `frontend/.env` (else ellipsoid fallback — not a test failure; see `docs/GLOBE.md`)

## Execution sequence

### 1. Open the HUD
Use the `cursor-ide-browser` MCP:
- `browser_navigate` to `http://localhost:5176` (omit `position` to keep focus)
- `browser_lock` action `lock` once the tab is open

### 2. Initial render check
- `browser_snapshot` — read the accessibility tree
  - Expect HUD chrome: header with "WORLDBASE", "FULL SITUATION" button, view tabs (GLOBE / MAP / DATA / AI / OSINT)
  - Expect telemetry panel with live feed dots
- `browser_take_screenshot` — visual baseline
- `browser_cdp` with `Log.enable` then `Runtime.evaluate` querying `window.__cesiumViewer ? "ok" : "no-viewer"` to confirm Cesium initialized

### 3. View switch tests
For each view (`GLOBE`, `MAP`, `DATA`, `AI`):
- `browser_click` on the tab (use ref from snapshot)
- Wait ~500 ms via short CDP `Runtime.evaluate` `await new Promise(r=>setTimeout(r,500))`
- `browser_snapshot` + `browser_take_screenshot`
- Verify the view-specific element is present (DATA: tab strip; AI: chat input; MAP: MapLibre canvas)

### 4. Console error scan
- `browser_cdp` with `Runtime.evaluate` returning recent `console.error` count
- Or pull `Log.enable` events buffered since step 2
- **0 errors expected.** Common false positives: Cesium Ion 401 if token missing — note but do not fail.

### 5. Globe detail modal (optional)
- DATA → WEBCAMS → click a cam with coordinates
- Expect view switch to GLOBE + modal badge **LIVE FEED** with iframe
- Close modal — globe region remains visible (not empty space)
- See `docs/GLOBE.md`

### 6. FULL SITUATION overlay
- `browser_click` the FULL SITUATION button
- Wait ~3 s for parallel feed fetches
- `browser_snapshot` — expect 13 feed cards in 2 columns
- `browser_take_screenshot`
- Close overlay (Escape or close button)

### 7. Split view (current default)
- Click `◫ SPLIT`
- Verify both globe and map panes render side by side
- Camera-sync regression check: pan in MapLibre, snapshot Cesium pose — pitch should follow

### 8. Cleanup
- `browser_lock` action `unlock`

## When NOT to use
- After purely backend-only changes (use `worldbase-stack-check` instead)
- Pre-commit (smoke-test.ps1 already validates `npm run build`)

## Quality standards
- Always `browser_lock` before interaction, `unlock` at the end of the run
- Maximum 4 retry attempts on a flaky element — then report blocker, do not loop
- Embed the screenshots inline (`![view](path)`) in the final report
- If Cesium Ion shows the "missing token" overlay, note it but treat globe interaction as testable
- Iframe content (Flowsint OSINT panel) cannot be inspected — skip OSINT iframe verification
