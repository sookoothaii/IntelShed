# KIMI.md — WorldBase für Kimi Work

> **Kimi-Work-Schnellstart.** Lies diese Datei zuerst, dann [`AGENTS.md`](AGENTS.md), dann [`LLM_HANDOFF.md`](LLM_HANDOFF.md).  
> Ziel: Jede Kimi-Instanz versteht sofort die Windows/Git-Bash-Spezifika, die Endpunkte und die wichtigsten Konventionen — ohne bei Null anzufangen.

---

## 1. Shell & Environment (Windows / Git Bash)

| Problem | Warum | Workaround |
|---------|-------|------------|
| `python` not found | Git Bash PATH hat kein `python.exe` | Immer `py -c "..."` verwenden |
| `curl` leert / Encoding-Fehler | Git Bash `curl` hat Windows-Pfad-Probleme | Immer `py` mit `urllib.request` verwenden |
| `2>//null` oder `2>/null` fail | `//null` wird als Directory interpretiert | `2>/dev/null` verwenden |
| `powershell` nicht in Git Bash | PowerShell nicht im PATH | `tasklist` oder `netstat` verwenden; separate PowerShell-Session |
| Paths mit Spaces | `D:\MCP Mods\worldbase` | `-LiteralPath` in PowerShell; Quotes in Bash |

**Beispiel-Probe (kompakt):**

```python
py -c "import urllib.request, json; print(json.loads(urllib.request.urlopen('http://127.0.0.1:8002/api/health/ping', timeout=5).read().decode()))"
```

---

## 2. Ports & Services

| Service | Port | URL | Status-Check |
|---------|------|-----|--------------|
| API Backend | 8002 | `http://127.0.0.1:8002` | `GET /api/health/ping` |
| UI Frontend | 5176 | `http://localhost:5176` | `py` → `urllib.request.Request('http://localhost:5176')` |
| Flowsint | 5173 | `http://localhost:5173` | Embedded OSINT tool (separat) |
| Ollama | 11434 | `http://127.0.0.1:11434` | `GET /api/tags` |

**⚠️ Vite IPv6-Falle:** `frontend/vite.config.ts` bindet ohne `host: '127.0.0.1'` auf `[::1]` (IPv6). Dann funktioniert `http://127.0.0.1:5176` **nicht**, aber `http://localhost:5176` schon (resolvt auf `[::1]`). Fix: `host: '127.0.0.1'` in `vite.config.ts` setzen.

---

## 3. Kimi-Work-Standard-Checks (9-Step Audit)

Führe bei jedem Projekt-Check oder Neustart-Verifikation diese **deterministischen 9 Schritte** aus. Schritte 1–4 parallel, dann 5–8 parallel, dann 9 (Zusammenfassung).

### Schritt 1 — Zeitstempel (Anchor)
```bash
date '+%Y-%m-%dT%H:%M:%S%z (%Z)'
```

### Schritt 2 — API Backend
```python
py -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8002/api/health/ping', timeout=5).read().decode())"
```

### Schritt 3 — Ollama
```python
py -c "import urllib.request, json; print(len(json.loads(urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=5).read().decode())['models']), 'models')"
```

### Schritt 4 — UI Frontend
```python
py -c "import urllib.request; print(urllib.request.urlopen('http://localhost:5176', timeout=5).status)"
```
⚠️ Wenn Vite IPv6-bound ist und `127.0.0.1` failt, `localhost` probieren (resolvt auf `[::1]`).

### Schritt 5 — Trust Probes (Score 0–4)
```python
py -c "import urllib.request, json; print(json.dumps(json.loads(urllib.request.urlopen('http://127.0.0.1:8002/api/trust', timeout=10).read().decode()), indent=2))"
```
- **Erwartet: 4/4.** Häufige Ausfälle: `ollama` (Schema fehlt in env) oder `gdelt_local` (cold cache nach restart).

### Schritt 6 — Full Health Status
```python
py -c "import urllib.request, json; print(json.dumps(json.loads(urllib.request.urlopen('http://127.0.0.1:8002/api/health', timeout=10).read().decode()), indent=2))"
```
- Extrahiere: `db_connected` (heißt wirklich so, nicht `database.connected`), `ftm` (entities, ready), `credentials` (configured/total), Feed-Status (fresh/stale/warn/missing).

### Schritt 7 — Latest Briefing
```python
py -c "import urllib.request, json; print(json.dumps(json.loads(urllib.request.urlopen('http://127.0.0.1:8002/api/briefing', timeout=10).read().decode()), indent=2))"
```
- Prüfe: `created_at` (Frische), `quality.score` (0–1), `text.length` (nicht leer).

### Schritt 8 — Connectors
```python
py -c "import urllib.request, json; print(json.dumps(json.loads(urllib.request.urlopen('http://127.0.0.1:8002/api/connectors', timeout=10).read().decode()), indent=2))"
```

### Schritt 9 — Zusammenfassung
- Status-Tabelle in Deutsch: 🟢/🟡/🔴 für Backend, UI, Ollama, Trust, Briefing, Health, Connectors.
- Nach Zusammenfassung: Explizit fragen, ob Fixes gewünscht oder nur Status-Report.

**Danach:** Details in `AGENTS.md` § „Briefing pipeline" und `LLM_HANDOFF.md` (local).

---

## 4. Wichtige Endpunkte für Kimi

| Endpunkt | Zweck | Kimi-relevant |
|----------|-------|---------------|
| `GET /api/health/ping` | Schnell-Check | Immer zuerst |
| `GET /api/health` | Vollständiger Feed-Status | `db_connected`, `ftm`, `feeds` |
| `GET /api/trust` | Trust Score 0–4 + Probes + Feed Drift | `score`, `probes`, `feed_drift` |
| `GET /api/briefing` | Aktuelles Briefing (SQLite) | `text`, `quality`, `digest`, `watch_items`, `sections` |
| `GET /api/connectors` | Connector-Registry | `count`, `credentials_configured` |
| `GET /api/nodes` | Pi-Edge-Status | `online`, `age_seconds`, `sensors` |
| `POST /api/briefing/generate` | Force-Regenerate | Header `X-API-Key` wenn gesetzt; `?force=1` |

**Briefing-Response-Keys:** `created_at`, `text`, `alerts`, `fusion_hotspots`, `intel`, `digest`, `quality`, `watch_items`, `digest_line_meta`, `agentic`, `insights`.

**Kein `sections`-Key!** Die Frontend zeigt `briefing.text` (Plaintext-Protokoll). Die Abschnitte (LOCAL / REGION / GLOBAL / CYBER & INFRA / RECOMMENDATION) sind **im Text** als Labels, nicht als separate JSON-Array.

---

## 5. Häufige Fehler & Sofort-Fixes (Skill-Pitfalls)

| Symptom | Ursache | Fix |
|---------|---------|-----|
| `ConnectionRefusedError: 127.0.0.1:5176` | Vite bindet auf `[::1]` | `host: '127.0.0.1'` in `vite.config.ts` |
| `quality_score: null`, `sections: []` | Altes Briefing im SQLite-Cache | Stack-Neustart → Briefing neu generieren |
| Trust `gdelt_local` fail, count=0 | GDELT Rate-Limit / Cold Cache nach Restart | `GET /api/gdelt/pulse/local` manuell triggern; warte 30s; Autopilot holt nach |
| Trust score **3/4** nach Restart | `gdelt_local` zeigt `count=0` weil Cache kalt | Warte auf Autopilot oder manuell `/api/gdelt/pulse/local` |
| `newsdata_sources` 47h stale | NewsData Free-Tier ~12h Delay | Normal; self-heal auf nächsten Pull |
| `ollama` trust probe fail | `OLLAMA_HOST` in `backend/.env` ohne `http://` Schema | `trust_probes.py` normalisiert auto; Backend-Restart nötig |
| `/api/node/pull` 403 | Fehlender `X-Node-Token` Header | Für lokale Health-Checks erwartet; kein Fehler |
| `traffic_cams` stale | Low-Priority Feeds, refresh selten | Nur flaggen wenn User aktiv Traffic-Cam-Layer nutzt |
| `quakes:day` oder `hazards` missing | Cache-Key-Mismatch oder Connector fehlt | `feed_drift` freshness list prüfen |
| `2>//null` Error | Git Bash interpretiert `//` als Pfad | `2>/dev/null` verwenden |

---

## 6. Verification-Regeln (Kritisch)

| Regel | Bedeutung |
|-------|-----------|
| **Nur der Operator startet/stoppt den Stack.** | Agents verifizieren **read-only** (`py` + `urllib`). Nie `start.ps1` oder Services anfassen. |
| **„Ich habe alles neu gestartet"** | Operator sagt `ICH HABE ALLES NEU GESTARTET` → **Nichts selbst neu starten!** Nur aktuellen Zustand verifizieren und Next Steps vorschlagen. |
| **Messung vor Claim.** | „Es funktioniert" = `py`-Probe hat HTTP 200 + Payload validiert. |
| **Fixes anbieten.** | Nach Zusammenfassung explizit fragen: „Soll ich X fixen oder nur Status-Report?" |

---

## 7. Konventionen für Kimi-Work

1. **Nur der Operator startet/stoppt den Stack.** Agents verifizieren read-only (`py` + `urllib`). Nie `start.ps1` oder Services anfassen.
2. **Messung vor Claim.** „Es funktioniert" = `py`-Probe hat HTTP 200 + Payload validiert.
3. **`py` statt `curl`**, `urllib.request` statt shell-Tools. Git Bash curl ist auf Windows unzuverlässig.
4. **Zeitstempel zuerst.** `date '+%Y-%m-%dT%H:%M:%S%z (%Z)'` als Anchor für alle Age-Berechnungen.
5. **Parallel wo möglich.** Unabhängige Checks in einem Bash-Call oder mehreren `py`-Calls parallel.
6. **Doku aktualisieren.** Nach jeder Session `LLM_HANDOFF.md` (local) + committete Doku (`README.md`, `docs/*.md`) updaten.
7. **Deutsch/English.** Operator spricht Deutsch mit English-Technical-Terms. Agent antwortet auf Deutsch; Code/Doku auf Englisch.

---

## 8. Dokumentations-Hierarchie

| Datei | Sprache | Committed | Zweck | Für Kimi |
|-------|---------|-----------|-------|----------|
| `KIMI.md` (diese) | Deutsch | ✅ Ja | **Kimi-Work-Schnellstart** — Shell, Checks, Pitfalls | **Zuerst lesen** |
| `AGENTS.md` | Englisch | ✅ Ja | System, Endpunkte, Key-Files, Tests | Danach lesen |
| `LLM_HANDOFF.md` | Englisch | ❌ **Nein** (local) | Operator-Prefs, letzte Messungen, Done | Danach lesen |
| `README.md` | Englisch | ✅ Ja | Öffentliche Projektbeschreibung | Referenz |
| `docs/*.md` | Englisch | ✅ Ja | Thematische Docs (RAG, MCP, GLOBE, etc.) | Nach Bedarf |
| `briefs/*.md` | Englisch | ❌ **Nein** (local) | Recherche, Pläne, Experimente | Nach Bedarf |
| `SKILL.md` (skill) | Deutsch | ✅ Skill | Prozedural Memory für `check das projekt` | Automatisch geladen |

**Kimi-Work-Workflow:**
1. Session startet → `KIMI.md` lesen (diese Datei)
2. User sagt „check das projekt" → `worldbase-project-check` Skill triggert automatisch → 9-Step Audit
3. User will Details → `AGENTS.md` lesen
4. User will Context/History → `LLM_HANDOFF.md` lesen (local, nie commit)
5. Arbeit abschließen → `LLM_HANDOFF.md` updaten + committete Doku pflegen

---

## 9. Schnell-Referenz: Projekt-Status (Konstanten)

*Wird bei jeder Session in `LLM_HANDOFF.md` aktualisiert — hier nur die unveränderlichen Fakten.*

| Faktor | Wert |
|--------|------|
| **Stack** | FastAPI + React/Vite + SQLite + Ollama + optional Pi |
| **Region** | Thailand (`WORLDBASE_OPERATOR_REGION=thailand`) |
| **RAG** | R0–R1.4 shipped (BGE rerank, spatial, CRAG-lite, agentic loop) |
| **Briefing** | 24h digest, rule-based quality score, prediction ledger |
| **Pi** | offgrid-pi, push 45s, pull 120s, SSH `user0@192.168.1.121` |
| **Hardware-Ref** | Lenovo Legion, i9-12900HX, RTX 3080 Ti 16 GB |
| **Smoke** | `.
| **Pilots** | B-03 (prediction), B-04 (corroboration), B-05 (subgraph), B-06 (fusion) |

---

*Last updated: 2026-06-24 by Kimi Work session. Enriched with `worldbase-project-check` SKILL.md details.*
