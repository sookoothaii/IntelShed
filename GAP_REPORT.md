# WorldBase Gap Report — Stand vor Phase 1

Audit-Datum: 2026-06-02

---

## ✅ EXISTIERT (getestet)

### Backend (alle Endpoints geben 200 + echte Daten)

| Endpoint | Status | Daten |
|----------|--------|-------|
| `/api/health` | ✅ | uptime, status |
| `/api/aircraft` | ✅ | live ADS-B states |
| `/api/satellites` | ✅ | TLE + positions |
| `/api/earthquakes` | ✅ | USGS quakes (24h) |
| `/api/events` | ✅ | EONET natural events |
| `/api/spaceweather` | ✅ | NOAA Kp-index |
| `/api/geopolitics` | ✅ | ReliefWeb disasters |
| `/api/markets` | ✅ | CoinGecko crypto |
| `/api/nodes` | ✅ | Pi telemetry (1 node online) |
| `/api/military` | ✅ | Aircraft with military hex |
| `/api/models` | ✅ | Ollama model list |
| `/api/briefing` | ✅ | 22 Briefings generiert |
| `/api/chat` | ✅ | Streaming + Context + Web Search |
| `/api/search` | ✅ | DuckDuckGo HTML scraping |

### Datenbank

| Tabelle | Zeilen | Status |
|---------|--------|--------|
| `briefings` | 22 | ✅ Autopilot generiert alle 10 min |
| `node_state` | 1 | ✅ Pi online, 9.55N 100.05E |
| `aircraft` | 0 | ⚠️ Table existiert, nicht genutzt |
| `satellites` | 0 | ⚠️ Table existiert, nicht genutzt |
| `feed_cache` | 0 | ⚠️ Table existiert, nicht genutzt |

### Frontend

| Komponente | Status | Was rendert |
|-----------|--------|-------------|
| `Globe.tsx` | ✅ | Aircraft, Satellites, Erdbeben, Events, ISS, Nodes |
| `DataPanel` | ✅ | Aircraft, Satellites, Seismic, Events, ISS, Health Tabs |
| `ChatPanel` | ✅ | Streaming, Model-Select, Web-Search Toggle, Context |
| `OsintPanel` | ✅ | OpenOSINT iframe via SSH tunnel |
| `App.tsx` | ✅ | HUD, Clock, SystemStatus, Navigation |

---

## ❌ FEHLEND für Phase 1 (Globe + Intelligence)

### DATA Tab — fehlende Feed-Tabs

| Feed | Backend | Frontend Tab | Status |
|------|---------|--------------|--------|
| Spaceweather | ✅ | ❌ | Fehlt komplett |
| Geopolitics | ✅ | ❌ | Fehlt komplett |
| Markets | ✅ | ❌ | Fehlt komplett |
| Nodes | ✅ | ❌ | Fehlt komplett |
| Military | ✅ | ❌ | Fehlt komplett |

### Globe — fehlende Layer

| Layer | Backend | Globe Rendering | Status |
|-------|---------|---------------|--------|
| Military aircraft | ✅ | ❌ | Keine Visualisierung |
| Squawk 7500/7600/7700 | ✅ | ❌ | Keine Emergency-Highlighting |
| Spaceweather (Kp-ring) | ✅ | ❌ | Kein Geomagnetic overlay |
| Geopolitics pins | ✅ | ❌ | Keine ReliefWeb-Marker |
| Markets | ✅ | ❌ | Nicht geografisch (skip) |

### Intelligence — fehlende Features

| Feature | Status | Blocker |
|---------|--------|---------|
| Aircraft anomaly detection | ❌ | Kein Code |
| Cross-feed correlation | ❌ | Kein Code |
| Globe click → "Ask AI" | ❌ | Kein Code |
| Entity context injection | ❌ | Kein Code |

### Backend — kleine Lücken

| Feature | Status | Problem |
|---------|--------|---------|
| Feed cache persistiert | ❌ | `feed_cache` leer — Cache nur im Memory |
| Aircraft/Satellites in DB | ❌ | Tabellen leer — nie geschrieben |

---

## 📋 Priorisierte Todo-Liste für Phase 1

### Block 1: DATA Tab vollständig machen (schnell)
1. `spaceweather` Tab — Kp-index, scale, solar wind
2. `geopolitics` Tab — ReliefWeb disasters mit Status-filter
3. `markets` Tab — Crypto-Preise (nicht-geo)
4. `nodes` Tab — Pi-Telemetrie-Tabelle
5. `military` Tab — Military hex aircraft Tabelle

### Block 2: Globe Layer erweitern (mittel)
6. Military aircraft als eigene DataSource (rot)
7. Emergency squawk highlighting (7500/7600/7700 = pulsierend rot)
8. Spaceweather Kp-ring (aurora-oval Farbverlauf)
9. Geopolitics pins (ReliefWeb-Krisen als Marker)

### Block 3: Intelligence Engine (komplex)
10. Aircraft anomaly detection (no-callsign, loitering, altitude drop)
11. Cross-feed correlation (geo-proximity + time-proximity scoring)
12. Globe click → "Ask AI" Button → Kontext in ChatPanel injizieren
13. Entity context injection (Koordinaten, Typ, Werte als System-Prompt)

### Block 4: Stabilität (klein)
14. Feed cache in SQLite persistieren (statt nur Memory)
15. `/api/health` mit Feed-Freshness (last-success timestamps)

---

## 🎯 Empfohlene Reihenfolge

1. **Block 1** (1 Tag) — Sofortiger Nutzen, schnell zu implementieren
2. **Block 2** (2 Tage) — Globe wird zum "lebendigen Lagebild"
3. **Block 3** (3 Tage) — Die KI wird wirklich intelligent
4. **Block 4** (1 Tag) — Stabilität für den Alltag

Gesamtschätzung: ~7 Tage implementieren + testen
