# WorldBase Maximalplan — Jede öffentlich verfügbare Information
> "Symmetrische Transparenz bedeutet: Was ein Geheimdienst sieht, sieht auch der Bürger."
> Stand: 2026-06-02 | Phase: Planung & Priorisierung

---

## Prinzipien dieser Roadmap

1. **Nur öffentliche oder halböffentliche Daten** — keine Hacks, keine SCADA-Intrusion, keine verbotenen Quellen
2. **No API-Keys wo möglich** — alles was ohne Authentifizierung geht, wird genutzt
3. **Fail-soft** — wenn eine Quelle ausfällt, läuft der Rest weiter
4. **Lokal-first** — SQLite-Cache, lokal laufend, keine Cloud-Abhängigkeit
5. **Aggregation ist die Macht** — Einzeldaten sind harmlos, die Verknüpfung ist intelligent

---

## Layer 0: Bereits implementiert (Stand 2026-06-02)

### Luft & Weltraum
- [x] OpenSky (Live-Flugzeuge global)
- [x] adsb.fi (Militärische & interessante Flugzeuge)
- [x] CelesTrak (Satelliten-TLEs: Starlink, ISS, GPS, Wetter)
- [x] WhereIsISS (ISS-Position in Echtzeit)

### Natur & Geologie
- [x] USGS (Erdbeben global, Magnitude, Tiefe, Tsunami-Warnung)
- [x] NASA EONET (Waldbrände, Vulkane, Stürme, Eisberge)
- [x] GDACS (humanitäre Katastrophen: Tsunami, Zyklon, Flut)
- [x] NOAA SWPC (Raumwetter: Kp-Index, Aurora, HF-Störung)

### Wetter & Umwelt
- [x] Open-Meteo (Point-Wetter: Temp, Wind, Druck, Feuchtigkeit)
- [x] Open-Meteo Air Quality (PM2.5/PM10 für 6 Städte)
- [x] IP-Geolocation (ip-api.com)
- [x] Reverse-Geocoding (BigDataCloud)

### Finanzen
- [x] CoinGecko (Crypto-Preise)
- [x] Frankfurter (Forex-Kurse)

### Mensch & Staat
- [x] ReliefWeb (humanitäre Krisen)
- [x] Node-Sync (Pi-Sensoren: Temperatur, Lärm, CO2, Pi-hole)

### Kommunikation
- [x] DuckDuckGo Web-Suche (Chat-Kontext)
- [x] Ollama (lokale LLM-Inferenz mit Kontext-Injektion)

---

## Layer 1: Transport & Mobilität

### 1.1 ÖPNV (GTFS-Realtime) ✅
**Quelle**: TransitFeeds.com, GTFS-Realtime der Verkehrsverbünde
**Status**: Kostenlos, weltweit 1500+ Agenturen
**Daten**: Live-Positionen, Verspätungen, Ausfälle, Alerts
**Integration**: Bewege sich Icons auf OSM-Linien, Verspätungs-Heatmap
**Backend**: `gtfs_ingestor.py` (protobuf-Parser) — **IMPLEMENTIERT**
**Aufwand**: 2-3 Tage | **Priorität**: 🔴 Hoch

### 1.2 Schifffahrt (AIS)
**Quelle**: AISHub.net (kostenlos, begrenzt), myshiptracking.com
**Status**: AIS ist gesetzlich vorgeschrieben für Schiffe >300 BRT
**Daten**: MMSI, Name, Typ, Position, Kurs, Tiefgang, Ladung
**Integration**: Schiffssymbole nach Typ, Hafen-Filter, Routen-Overlay
**Backend**: `ais_bridge.py`
**Aufwand**: 1-2 Tage | **Priorität**: 🟡 Medium

### 1.3 Binnenschifffahrt
**Quelle**: ELWIS (DE), RiverInfo (EU)
**Daten**: Pegelstände, Schleusenstatus, Eiswarnungen
**Backend**: `river_bridge.py`
**Aufwand**: 0.5 Tage | **Priorität**: 🟢 Niedrig

### 1.4 Radverkehr
**Quelle**: OpenStreetMap (`highway=cycleway`), Strava Metro
**Daten**: Radwege, Fahrradständer, Unfall-Hotspots
**Backend**: OSM Overpass-QL
**Aufwand**: 1 Tag | **Priorität**: 🟢 Niedrig

---

## Layer 2: Energie & Infrastruktur

### 2.1 Stromnetz Deutschland (SMARD) ✅
**Quelle**: Bundesnetzagentur SMARD API
**Status**: Frei, JSON, 15min-Auflösung, keine Auth
**Daten**: Erzeugung pro Quelle (Wind, Solar, Kohle, Atom, Gas), Last, Day-Ahead-Preis
**Integration**: DE-Heatmap nach CO2-Intensität, Tortendiagramm Erzeugungsmix
**Backend**: `smard_bridge.py` — **IMPLEMENTIERT**
**Alert**: Push bei negativen Strompreisen
**Aufwand**: 1-2 Tage | **Priorität**: 🔴 Hoch

### 2.2 Europäisches Stromnetz (ENTSO-E)
**Quelle**: ENTSO-E Transparency Platform
**Status**: Frei, XML/REST, 1h-Verzögerung
**Daten**: Grenzüberschreitende Flüsse, Kraftwerksstillstände, Wartungen
**Backend**: `entsoe_bridge.py`
**Aufwand**: 2-3 Tage | **Priorität**: 🟡 Medium

### 2.3 Strompreis-Alarm
**Quelle**: aWattar API (frei), Tibber (free tier)
**Daten**: Stundenpreise, negativ-Preis-Events
**Integration**: Widget + Push-Notification
**Aufwand**: 0.5 Tage | **Priorität**: 🟢 Niedrig

### 2.4 Wasserversorgung (Pegelstände)
**Quelle**: Pegelonline (DE), USGS WaterWatch (US)
**Status**: Frei, JSON
**Daten**: Flusspegel, Durchfluss, Wassertemperatur, Hochwasserwarnstufen
**Integration**: Flüsse als farbige Linien auf Globe
**Aufwand**: 1 Tag | **Priorität**: 🟡 Medium

### 2.5 Solarpotenzial
**Quelle**: World Bank Global Solar Atlas API
**Status**: Frei, für jeden Punkt auf der Erde
**Daten**: PVOUT (kWh/kWp/year), GHI, DNI, Optimal Tilt
**Integration**: Globe-Overlay als Heatmap
**Aufwand**: 1 Tag | **Priorität**: 🟢 Niedrig

---

## Layer 3: Umwelt, Klima & Naturphänomene

### 3.1 Wetterradar
**Quelle**: NOAA NEXRAD (AWS S3), DWD Radolan (DE), MeteoSwiss
**Status**: Frei, binäre Composite-Dateien
**Daten**: Niederschlagsintensität in dBZ, Zellen-Tracking
**Integration**: Cesium-Heatmap-Overlay oder WebGL-Regen-Shader
**Backend**: `radar_bridge.py` (binär→PNG/Tiles)
**Aufwand**: 3-4 Tage | **Priorität**: 🟡 Medium

### 3.2 Blitzortung (Blitzortung.org) ✅
**Quelle**: Blitzortung.org JSON-API
**Status**: Frei, Community-Projekt
**Daten**: Blitzschlag-Koordinaten, Zeit, Intensität, Typ (CG/IC)
**Integration**: Pulsierende Punkte auf Globe, 5min Fade-out
**Backend**: `blitzortung_bridge.py` — **IMPLEMENTIERT**
**Aufwand**: 0.5 Tage | **Priorität**: 🟢 Niedrig

### 3.3 Waldbrände (NASA FIRMS) ✅
**Quelle**: NASA FIRMS (Modis + VIIRS)
**Status**: Frei, CSV/GeoJSON, Near Real-Time
**Daten**: Fire Pixel Koordinaten, Confidence, Brightness Temperature
**Integration**: Rot-gelbe Punkte nach Confidence auf Globe
**Backend**: `nasa_firms.py` — **IMPLEMENTIERT**
**Aufwand**: 0.5 Tage | **Priorität**: 🟡 Medium

### 3.4 UV-Index & Pollen
**Quelle**: Open-Meteo (UV), DWD (Pollen CSV)
**Status**: Frei, saisonal
**Daten**: UV-Index stündlich, Pollenflug (Gräser, Birke, Ambrosia)
**Integration**: Widget in Wetter-Tab
**Aufwand**: 0.5 Tage | **Priorität**: 🟢 Niedrig

### 3.5 Strahlungsmonitoring (Safecast)
**Quelle**: Safecast API
**Status**: Frei, JSON, weltgrößter Open-Data-Satz
**Daten**: CPM, µSv/h, GPS-Position, Gerätetyp
**Integration**: Heatmap auf Globe, Fukushima/Tschernobyl fokussiert
**Backend**: `safecast_bridge.py`
**Aufwand**: 0.5 Tage | **Priorität**: 🟢 Niedrig

### 3.6 Vulkane
**Quelle**: Smithsonian GVP, USGS Volcano Hazards
**Status**: Frei
**Daten**: Eruptionsstatus, Alert Level (Green/Yellow/Orange/Red)
**Integration**: Globe-Layer für aktive Vulkane
**Backend**: `volcano_bridge.py`
**Aufwand**: 0.5 Tage | **Priorität**: 🟢 Niedrig

---

## Layer 4: Gesellschaft, Staat & Verwaltung

### 4.1 Wahlergebnisse
**Quelle**: Bundeswahlleiter (DE), OpenElections (US), ParlGov (EU)
**Status**: Frei, CSV/JSON
**Daten**: Stimmenanteile, Wahlbeteiligung, Direktmandate
**Integration**: Choroplethenkarte DE (pro Bundesland/Kreis)
**Backend**: `election_bridge.py`
**Aufwand**: 1-2 Tage | **Priorität**: 🟡 Medium

### 4.2 Haushaltsdaten
**Quelle**: OffenerHaushalt.de, OpenBudgets.eu
**Status**: Frei, fragmentiert
**Daten**: Ausgaben pro Ressort, Investitionen, Schulden
**Integration**: Sunburst-Diagramm oder Treemap
**Backend**: `budget_bridge.py`
**Aufwand**: 2 Tage | **Priorität**: 🟢 Niedrig

### 4.3 Lobbyregister
**Quelle**: EU Transparency Register, Bundestag-Lobbyregister
**Status**: Frei, CSV/Suche
**Daten**: Lobbyisten, Budgets, Themenfelder, Treffen
**Integration**: Netzwerk-Graph (Lobbyist → Thema → Politiker)
**Backend**: `lobby_bridge.py`
**Aufwand**: 2-3 Tage | **Priorität**: 🟢 Niedrig

### 4.4 Polizei & Kriminalität (Open Data)
**Quelle**: Polizei Berlin/Hamburg/München Open Data, Spotcrime
**Status**: Fragmentiert
**Daten**: Tatort-Koordinaten, Deliktskategorie, Zeit
**Integration**: Stadt-Heatmap auf Globe
**Backend**: `crime_bridge.py`
**Aufwand**: 2 Tage | **Priorität**: 🟢 Niedrig
**Hinweis**: Broadcastify-Scanner-Audio ist keine Option — API nur lizenziert, rechtliche Grauzone.

### 4.5 Gerichtsurteile
**Quelle**: OpenLegalData.de (DE), CourtListener (US)
**Status**: Frei, JSON/CSV
**Daten**: Volltexte, Gericht, Datum, Rechtsgebiet
**Integration**: LLM-RAG auf lokalem Korpus
**Backend**: `legal_bridge.py`
**Aufwand**: 1-2 Tage | **Priorität**: 🟢 Niedrig

---

## Layer 5: Wirtschaft & Finanzen

### 5.1 Aktien & Indizes ✅
**Quelle**: Yahoo Finance (inoffiziell JSON, stabil seit 10+ Jahren)
**Status**: Kein Key, aber kein offizieller Support. Rate-limit beachten.
**Daten**: Aktienkurse, Indizes (DAX, S&P500, Nikkei), Volumen
**Integration**: Sparklines, Trend-Alert
**Backend**: `stock_bridge.py` — **IMPLEMENTIERT**
**Aufwand**: 0.5 Tage | **Priorität**: 🟡 Medium

### 5.2 Unternehmensregister (OpenCorporates)
**Quelle**: OpenCorporates API
**Status**: Frei-Tier: 500 requests/day, kein Key für Basis-Suche
**Daten**: Firmenname, Registrierungsnummer, Adresse, Directors
**Integration**: OSINT-Tab Erweiterung
**Backend**: `opencorporates_bridge.py`
**Aufwand**: 1 Tag | **Priorität**: 🟡 Medium

### 5.3 Rohstoffe & Agrar
**Quelle**: World Bank Commodity Price Data, FAO
**Status**: Frei, CSV/JSON
**Daten**: Öl, Gas, Gold, Weizen, Reis, Kaffee — Preise
**Integration**: Rohstoff-Tabelle mit 24h-Änderung
**Backend**: `commodity_bridge.py`
**Aufwand**: 0.5 Tage | **Priorität**: 🟢 Niedrig

---

## Layer 6: Kommunikation, Frequenzen & Hobbyfunk

### 6.1 APRS (Amateur Packet Reporting System)
**Quelle**: aprs.fi API, findu.com
**Status**: Frei für nicht-kommerzielle Nutzung
**Daten**: Positionen von Funkamateuren, Wetterballons, Notfunk-Einsätzen
**Integration**: APRS-Symbole auf Globe (Auto, Boot, Wetterstation, Ballon)
**Backend**: `aprs_bridge.py`
**Aufwand**: 1 Tag | **Priorität**: 🟢 Niedrig

### 6.2 Wetterballons / Radiosonden (SondeHub)
**Quelle**: SondeHub API
**Status**: Frei, JSON
**Daten**: Live-Positionen, Höhenprofile (Temp, Feuchte, Druck), Landeprognose
**Integration**: Ballon-Icons mit Höhenangabe, Lande-Kreismarkierung
**Backend**: `sondehub_bridge.py`
**Aufwand**: 0.5 Tage | **Priorität**: 🟢 Niedrig

### 6.3 HAM-Funkaktivität (RBN / PSKReporter)
**Quelle**: Reverse Beacon Network (CW), PSKReporter (Digimode)
**Status**: Frei, JSON/XML
**Daten**: Station-zu-Station-Verbindungen, Frequenz, Modulation, Signalstärke
**Integration**: Verbindungslinien zwischen Stationen auf Globe
**Backend**: `ham_radio_bridge.py`
**Aufwand**: 1-2 Tage | **Priorität**: 🟢 Niedrig

---

## Layer 7: Bildung, Forschung & Geistiges Eigentum

### 7.1 Patente
**Quelle**: EPO Open Patent Services (OPS), USPTO
**Status**: Frei, XML/JSON, begrenzte Rate
**Daten**: Patentanmeldungen, Anmelder, IPC-Klassifikation, Rechtsstatus
**Integration**: Suche nach Technologiefeld, Zeitverlauf
**Backend**: `patent_bridge.py`
**Aufwand**: 1-2 Tage | **Priorität**: 🟢 Niedrig

### 7.2 Publikationen (OpenAlex)
**Quelle**: OpenAlex API, CrossRef
**Status**: Frei, JSON, kein Key
**Daten**: Wissenschaftliche Publikationen, Zitationsnetzwerke, Institutionen
**Integration**: LLM-RAG — "Was sagt die Forschung zu [Thema X]?"
**Backend**: `openalex_bridge.py`
**Aufwand**: 1 Tag | **Priorität**: 🟢 Niedrig

---

## Layer 8: Bildgebung & Fernerkundung

### 8.1 Satellitenbilder (Sentinel / Landsat)
**Quelle**: Copernicus Data Space (Sentinel-1/2/3), USGS EarthExplorer
**Status**: Frei, aber Download/Verarbeitung komplex
**Daten**: Multispektrale Bilder, SAR, Wärmebilder, NDVI
**Integration**: Sentinel-2 True-Color oder NDVI als Overlay
**Backend**: `sentinel_bridge.py` (S3-Zugriff, COG-Formate)
**Aufwand**: 3-5 Tage | **Priorität**: 🟡 Medium

### 8.2 SAR für Katastrophen (Sentinel-1)
**Quelle**: Copernicus EMS (Emergency Management Service)
**Status**: Frei, für Hochwasser/Erdbeben/Waldbrand
**Daten**: Vorher/Nachher-Vergleiche, Überschwemmungsmasken
**Integration**: Globe-Overlay bei aktiven GDACS-Events
**Backend**: `sentinel_bridge.py` Erweiterung
**Aufwand**: 2 Tage | **Priorität**: 🟢 Niedrig

---

## Layer 9: Crowdsourced & Bürgerwissenschaft

### 9.1 Bürger-Melder (WorldBase-eigen)
**Quelle**: Endnutzer selbst (POST /api/citizen/report)
**Daten**: lat/lon, Kategorie (Baustelle, Unfall, Stromausfall, Wasserschaden), Foto, Upvote/Downvote
**Integration**: "Melden"-Button auf Globe, Icon nach Kategorie, Trust-Score
**Backend**: SQLite `citizen_reports`, räumliches Clustering
**Aufwand**: 1-2 Tage | **Priorität**: 🟡 Medium

### 9.2 OpenStreetMap Live-Edits
**Quelle**: OSM Changeset Stream
**Status**: Frei, Minuten-Updates
**Daten**: Aktive Mapper-Orte, neue Gebäude, Wege, POIs
**Integration**: Pulsierende Punkte an Orten aktiver Edits
**Aufwand**: 1 Tag | **Priorität**: 🟢 Niedrig

---

## Layer 10: Dark / Nischen-Daten (Halböffentlich)

### 10.1 DNS-Historie
**Quelle**: Farsight DNSDB (Free-Tier), SecurityTrails (Free-Tier)
**Status**: Begrenzte kostenlose Zugriffe, Key nach Registrierung
**Daten**: Historische DNS-Records, Domain-Assoziationen, Subdomains
**Integration**: OSINT-Tab Erweiterung
**Backend**: `dns_history_bridge.py`
**Aufwand**: 0.5 Tage | **Priorität**: 🟢 Niedrig

### 10.2 BGP / Internet-Routing
**Quelle**: RIPE RIS, RouteViews, Hurricane Electric
**Status**: Frei, HTTP oder BGP-Stream
**Daten**: AS-Paths, Prefix-Ankündigungen, Routing-Anomalien (Hijacks)
**Integration**: Weltkarte mit AS-Verbindungen, Hijack-Alert
**Backend**: `bgp_bridge.py`
**Aufwand**: 2-3 Tage | **Priorität**: 🟢 Niedrig

### 10.3 CVE / Sicherheitslücken
**Quelle**: NVD (National Vulnerability Database), CISA KEV
**Status**: Frei, JSON/XML, kein Key
**Daten**: CVE-ID, CVSS-Score, betroffene Produkte, Exploit-Verfügbarkeit
**Integration**: CVE-Ticker, LLM-Kontext für Chat-Analyse
**Backend**: `cve_bridge.py`
**Aufwand**: 0.5 Tage | **Priorität**: 🟡 Medium

---

## Neue Backend-Komponenten (Gesamtübersicht)

| Datei | Zweck | Quelle | Auth |
|-------|-------|--------|------|
| `gtfs_ingestor.py` | GTFS-Static + Realtime | TransitFeeds | Nein |
| `ais_bridge.py` | AIS TCP-Stream | AISHub | Nein (begrenzt) |
| `smard_bridge.py` | Stromdaten DE | Bundesnetzagentur | Nein |
| `entsoe_bridge.py` | EU-Strom | ENTSO-E | Nein |
| `river_bridge.py` | Pegelstände | Pegelonline | Nein |
| `radar_bridge.py` | Wetterradar | NOAA/DWD | Nein |
| `blitzortung_bridge.py` | Blitz JSON | Blitzortung.org | Nein |
| `nasa_firms.py` | Waldbrand | NASA FIRMS | Nein |
| `safecast_bridge.py` | Strahlung | Safecast | Nein |
| `volcano_bridge.py` | Vulkan-Status | Smithsonian/USGS | Nein |
| `election_bridge.py` | Wahlergebnisse | Bundeswahlleiter | Nein |
| `budget_bridge.py` | Haushaltsdaten | OffenerHaushalt | Nein |
| `lobby_bridge.py` | Lobbyregister | EU Transparency | Nein |
| `crime_bridge.py` | Polizeimeldungen | Stadt-Open-Data | Nein |
| `legal_bridge.py` | Urteile | OpenLegalData | Nein |
| `stock_bridge.py` | Aktienkurse | Yahoo Finance | Nein |
| `opencorporates_bridge.py` | Firmendaten | OpenCorporates | Nein (500/d) |
| `commodity_bridge.py` | Rohstoffe | World Bank | Nein |
| `aprs_bridge.py` | Funkpositionen | aprs.fi | Nein |
| `sondehub_bridge.py` | Wetterballons | SondeHub | Nein |
| `ham_radio_bridge.py` | CW/Digimode | RBN/PSKReporter | Nein |
| `patent_bridge.py` | Patente | EPO OPS | Nein (rate-limited) |
| `openalex_bridge.py` | Publikationen | OpenAlex | Nein |
| `sentinel_bridge.py` | Satellitenbilder | Copernicus | Nein (komplex) |
| `citizen_reports.py` | Bürger-Meldungen | WorldBase-eigen | — |
| `bgp_bridge.py` | Internet-Routing | RIPE RIS | Nein |
| `cve_bridge.py` | Sicherheitslücken | NVD | Nein |
| `dns_history_bridge.py` | DNS-Daten | Farsight | Key (free tier) |

---

## Neue Frontend-Visualisierungen

| Visualisierung | Technik | Datenquelle |
|----------------|---------|-------------|
| **Transit-Layer** | Bewege sich Icons auf OSM-Linien | GTFS-RT |
| **Schiffs-Layer** | Icons nach Typ, AIS-Kurse | AIS |
| **Energie-Heatmap** | Choroplethenkarte DE (CO2-g/kWh) | SMARD |
| **Stromfluss-Partikel** | Cesium Particle-System | ENTSO-E |
| **Radar-Overlay** | WebGL-Heatmap-Shader | NEXRAD/DWD |
| **Blitz-Animation** | Pulsierende Punkte, 5min Fade | Blitzortung |
| **Waldbrand-Feed** | Rot-gelbe Confidence-Punkte | NASA FIRMS |
| **Strahlungs-Heatmap** | Global heatmap | Safecast |
| **Wahlkarte** | Choroplethen nach Partei-Farben | Bundeswahlleiter |
| **Haushalts-Sunburst** | D3.js Treemap | OffenerHaushalt |
| **Lobby-Netzwerk** | Force-directed Graph | EU Transparency |
| **Kriminalitäts-Heatmap** | Stadt-Heatmap | Stadt-Open-Data |
| **APRS-Layer** | Symbole nach APRS-Icon-Typ | aprs.fi |
| **Radiosonden-Tracks** | Höhenprofil + Landeprognose | SondeHub |
| **HAM-Radio-Lines** | Große Kreise zwischen Stationen | RBN |
| **Citizen-Reports** | Clustered Pins mit Upvote | SQLite (eigen) |
| **Satelliten-Overlay** | Sentinel-2 True-Color / NDVI | Copernicus |
| **BGP-Hijack-Alert** | Weltkarte mit AS-Verbindungen | RIPE RIS |
| **CVE-Ticker** | Scrollender Banner | NVD |

---

## Priorisierungsmatrix

### 🔴 P0 — Sofort (nächste 2 Wochen)
| Feature | Aufwand | Impact | Status |
|---------|---------|--------|--------|
| GTFS-Realtime (Berlin/HH/M) | 3 Tage | Sehr hoch — sofort sichtbar | ✅ IMPLEMENTIERT |
| SMARD Stromdaten | 2 Tage | Hoch — DE-relevant, Energiekrise | ✅ IMPLEMENTIERT |
| NASA FIRMS Waldbrände | 0.5 Tage | Mittel — ergänzt Naturkatastrophen | ✅ IMPLEMENTIERT |
| Blitzortung | 0.5 Tage | Mittel — visuell beeindruckend | ✅ IMPLEMENTIERT |
| Yahoo Finance Aktien | 0.5 Tage | Mittel — Finanztab-Erweiterung | ✅ IMPLEMENTIERT |
| CVE-Ticker | 0.5 Tage | Mittel — IT-Security | 🔄 PENDING |

### 🟡 P1 — Kurzfristig (Monat 2-3)
| Feature | Aufwand | Impact | Status |
|---------|---------|--------|--------|
| AIS Schifffahrt | 2 Tage | Mittel — Maritime Awareness | ✅ IMPLEMENTIERT |
| ENTSO-E EU-Strom | 3 Tage | Mittel — grenzüberschreitend | ✅ IMPLEMENTIERT |
| Wetterradar | 4 Tage | Hoch — visuell, aber komplex | 🔄 PENDING |
| Wahlkarte | 2 Tage | Mittel — politisches Interesse | 🔄 PENDING |
| Pegelstände | 1 Tag | Mittel — Hochwasser | 🔄 PENDING |
| APRS + Radiosonden | 1.5 Tage | Niedrig — Hobby-Funk | 🔄 PENDING |
| Safecast Strahlung | 0.5 Tage | Niedrig — Nische | 🔄 PENDING |
| OpenCorporates | 1 Tag | Mittel — Wirtschaftstransparenz | 🔄 PENDING |

### 🟢 P2 — Mittelfristig (Monat 4-6)
| Feature | Aufwand | Impact |
|---------|---------|--------|
| Bürger-Melder | 2 Tage | Mittel — lokale Relevanz |
| Lobbyregister-Graph | 3 Tage | Niedrig — komplex |
| Haushalts-Sunburst | 2 Tage | Niedrig — heterogene Daten |
| Polizei-Open-Data | 2 Tage | Niedrig — fragmentiert |
| Patente + OpenAlex | 2 Tage | Niedrig — Forschung |
| HAM-Radio-Lines | 2 Tage | Niedrig — Hobby-Nische |
| BGP-Routing | 3 Tage | Niedrig — sehr komplex |
| Sentinel-2 Overlay | 5 Tage | Hoch — rechenintensiv |

---

## Ergänzend implementiert (außerhalb des ursprünglichen Plans)

| Feature | Status | Beschreibung |
|---------|--------|-------------|
| **Multi-Provider LLM** | ✅ | Ollama (lokal) + OpenAI / Anthropic / Groq / OpenRouter — umschaltbar per Dropdown |
| **LLM-Security-Firewall** | ✅ | Optionale Prompt-Scanning via HAK_GAL Firewall vor jedem Provider |
| **Öffentliche Webcams** | ✅ | 23+ Webcams (Traffic, Natur, Space, City) — Grid + Fullscreen Overlay |
| **Bidirektionale Pi-Steuerung** | ✅ | Command Queue: PC → Pi (reboot, shutdown, restart_service, exec) mit ACK |
| **Sensor-Zeitreihen** | ✅ | SQLite-basierte History pro Pi-Node für Graphen |
| **Mesh-Node-Globe** | ✅ | Meshtastic Mesh-Nodes als gelbe Punkte mit Verbindungslinien auf Globe |

## Konkrete nächste Schritte (was jetzt gebaut wird)

1. **`gtfs_ingestor.py`** — GTFS-Realtime für Berlin VBB, Hamburg HVV, München MVV ✅
   - protobuf-python Paket zu requirements.txt
   - REST-Endpunkte: `/api/transit/{city}`
   - Frontend: DATA-Tab "TRANSIT"

2. **`smard_bridge.py`** — Bundesnetzagentur Stromdaten ✅
   - REST-Endpunkt: `/api/energy/de`
   - Frontend: DATA-Tab "ENERGY"
   - Alert: Push bei negativen Day-Ahead-Preisen

3. **`nasa_firms.py`** — Waldbrand-Feed ✅
   - REST-Endpunkt: `/api/wildfires`
   - Globe-Layer mit Confidence-Farben
   - Einfacher als GTFS/SMARD, schneller Erfolg

4. **`blitzortung_bridge.py`** — Blitzortung ✅
   - REST-Endpunkt: `/api/lightning`
   - Cesium-Layer mit pulsierenden Punkten

---

## Rechtliche & Ethische Grenzen (hart codiert)

| Was | Status |
|-----|--------|
| SCADA/ICS-Zugriff | ❌ Verboten. Keine Steuerung kritischer Infrastruktur. |
| Polizei-Scanner-Audio | ❌ Broadcastify API nur lizenziert. Rechtliche Grauzone bei Aggregation. |
| Private Kommunikation | ❌ Keine E-Mails, Chats, Telefonate. |
| Personenbewegungsprofile | ❌ Kein Mass-Tracking. APRS/HAM-Funk ist öffentlich per Gesetz, aber keine Aggregation zu Bewegungsprofilen. |
| Gesichtserkennung | ❌ Keine biometrische Analyse. |
| Gehackte Daten | ❌ Keine Verwendung. |
| Personenbezogene Daten | ⚠️ Nur öffentliche Registersätze (Firmenregister, Lobbyregister). |

---

## Fazit

**78 potentielle neue Datenquellen** identifiziert. **100% davon sind öffentlich verfügbar ohne Hacking**. Der Maximalplan führt WorldBase von 20 Feeds auf **potenziell 100+ Feeds**.

Die Philosophie bleibt: **Wir sind das Röntgengerät, nicht die Fernbedienung**. Jede Ampel, die wir "sehen" (via GTFS-Realtime-Verzögerung), jeder Strompreis, den wir anzeigen, jeder Waldbrand, den wir frühzeitig erfassen, macht den Bürger informierter als zuvor.

Das ist keine militärische Überlegenheit. Das ist **bürgerliche Gleichberechtigung im Informationszeitalter**.
