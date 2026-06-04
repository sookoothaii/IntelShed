# Next LLM Mission — Positive Palantir (WorldBase)

> Copy the **Start prompt** below into a new agent session.  
> Read first: `LLM_HANDOFF.md` → `docs/POSITIVE_PALANTIR_VISION.md` → this file.

## Leitprinzip

**Fusion vor Feeds** — eine Karte, Timeline, Entities, Investigation. Kein 13. DATA-Tab.

Die nächste Instanz vertieft **Fusion und Bedienung**, nicht neue Feed-Bridges ohne Globe-Layer.

---

## Erledigt (nicht nochmal anfangen)

### Phase A — Done (2026-06-04)

| # | Feature | API / UI |
|---|---------|----------|
| 1 | Flowsint → Globe | `POST /api/osint/pins/import` — OSINT tab → Flowsint → paste JSON → **IMPORT TO GLOBE** |
| 2 | Situation Board | `GET /api/situations` — header **SITUATIONS** overlay |
| 3 | Entity layer | SQLite `entities` / `entity_links` — `GET /api/entity/{id}/context` |
| 4 | AI tools | Ollama `use_tools` on `/api/chat` — `osint_ip`, `focus_globe`, `list_situations`, … |

### Phase B — Partial (2026-06-04)

| Done | Item |
|------|------|
| ✅ | SMARD API fix + `/api/energy/de/globe` + **ENERGY** layer on globe |
| ✅ | GTFS defaults: VBB Berlin + gtfs.de aggregate (HH/München bbox); `vehicle.position` parser |
| ✅ | Pegel + rain in `/api/correlations` |
| ✅ | Situations API parallel fetch + 45s cache; correlations 120s cache |
| ✅ | Browser push for negative DE power price |

---

## Fokus nächste Instanz (Priorität)

### Erledigt (2026-06-04, Code)

| Item | Details |
|------|---------|
| ✅ Time Slider | `Globe.tsx` — SEISMIC + EVENTS, 6/12/24h, kumulativer Scrub, LIVE |
| ✅ OpenSky Client | `opensky_client.py` — OAuth when configured |
| ✅ adsb.lol fallback | `adsb_client.py` + `aircraft_provider.py` — ~1k aircraft without keys |
| ✅ Pi Sparklines | `SensorSparklines.tsx` — Node Target-Panel |
| ✅ Crises on globe | GDACS + `geo_centroids.py`; ReliefWeb v2 via `RELIEFWEB_APPNAME` |
| ✅ GDELT pulse | `GET /api/gdelt/pulse` (headlines, cached) |
| ✅ Flowsint export | `POST /api/flowsint/export-investigation` |

### 1. Ops / optional keys (User)

- `OPENSKY_CLIENT_ID` / `SECRET` — higher OpenSky rate limits (optional; adsb.lol works without)
- `RELIEFWEB_APPNAME` — approved appname for ReliefWeb v2 disasters on CRISES layer
- `AIRCRAFT_SOURCE=auto|opensky|adsb` in `backend/.env`

### 2. Phase C — Edge USP

- Optional: **Portal-Auth Pi** (`PORTAL_REQUIRE_AUTH`) — `docs/SECURITY_OPERATIONS.md`
- Mesh briefing LCD, Firewall/HAK_GAL als LAN-only globe layer

### 4. Polish (nebeneinander, nicht Hauptmission)

- Situation Board: erster Load noch ~10–20s (Correlations in `/api/situations` teuer) → weiter cachen oder entkoppeln
- GTFS DE: VBB oft nur **TripUpdates**, keine Live-Positionen — **kein Parser-Bug**; Helsinki/Boston für bewegliche Icons; DE-Positionen = anderer Endpoint recherchieren

---

## Phase D — Backlog (explizit nicht jetzt)

- AIS bridge, OSM Overpass civic POIs, `POST /api/citizen/report`, Simulation
- Neue Feeds **ohne** Globe-Anbindung

## Do NOT

- SCADA / traffic-light control
- Mass person tracking
- Commit secrets (`pi-node-token.conf`, `backend/.env`)
- Add feeds without globe fusion

---

## Start prompt (copy)

```
Mission: WorldBase Phase B abschließen + Phase C starten — Fusion, keine neuen Feeds.

Erledigt: Phase A (Pins, Situations, Entities, Chat-Tools); Phase B partial (SMARD/Globe, Pegel+Regen, Situations-Cache, GTFS-Defaults, negativer Strompreis-Push).

Erledigt: Time Slider, adsb.lol/OpenSky aircraft, Pi-Sparklines, GDACS crises, GDELT pulse.

Offen: ReliefWeb appname, Situation Board perf, GTFS DE VehiclePosition, aircraft trails.

Lies: LLM_HANDOFF.md, docs/NEXT_LLM_MISSION.md, Globe.tsx, feeds_extra.py, node_sync.py.
Test: .\start.ps1 → http://localhost:5176
Nicht: neue Feed-Bridges ohne Globe-Layer; SCADA; Massen-Tracking; Secrets committen.
Pi SSH nur bei Bedarf: user0@192.168.1.121
```

---

## Test checklist

### Regression (Phase A/B — sollte weiter grün sein)

- [ ] `POST /api/osint/pins/import` → pins on globe
- [ ] **SITUATIONS** — zweites Öffnen schnell (~1–2s); correlations + GDACS + pegel
- [ ] Globe **ENERGY** → ~9 Kraftwerkspunkte DE (`GET /api/energy/de/globe`)
- [ ] Transit **HELSINKI** / **BOSTON** → bewegliche Icons (Berlin = Trip-Delays only)

### Neue Arbeit

- [ ] Time Slider: scrub zurück → Quakes/Events (min.) sichtbar für gewähltes Zeitfenster
- [ ] `/api/aircraft` → `source` = `adsb.lol` oder `opensky`, count > 0; HUD zeigt Quelle
- [ ] **CRISES** → GDACS-Punkte weltweit (nicht 0,0-Stapel)
- [ ] Optional: `RELIEFWEB_APPNAME` → zusätzliche ReliefWeb-Disasters
- [ ] (Optional) Node-Klick → Sparklines aus `/api/node/{id}/sensors/history`
