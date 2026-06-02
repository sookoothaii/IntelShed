# Positive Palantir — A Vision for Radical Transparency
> "The best defense against surveillance is symmetrical transparency."

## Executive Summary

WorldBase ist bereits eine **räumliche Intelligenz-Workstation** mit 20+ öffentlichen Datenfeeds. Dieses Dokument skizziert die Evolution hin zu einer **maximal-informationsdichten Plattform** — nicht für Kontrolle, sondern für **bürgerliche Aufklärung**. Das Ziel: Jeder Bürger sieht dieselben Daten wie ein Geheimdienst, ein Bürgermeister oder ein Investmentbanker. Die Plattform bleibt **100% Open Source, lokal-first, keine API-Keys, keine Cloud-Abhängigkeit**.

**Die Regel**: Wir sammeln nur Daten, die bereits öffentlich sind. Wir steuern nichts. Wir zeigen nur an.

---

## Layer 0: Was WorldBase bereits kann (Stand 2026-06-02)

| Domain | Quellen | Refresh |
|--------|---------|---------|
| Luftverkehr | OpenSky, adsb.fi (militärisch) | 10-15s |
| Weltraum | CelesTrak, WhereIsISS | 3-60s |
| Seismologie | USGS | 5min |
| Naturkatastrophen | NASA EONET, GDACS | 10-15min |
| Raumwetter | NOAA SWPC | 5min |
| Geopolitik | ReliefWeb | On-demand |
| Finanzmärkte | CoinGecko, Frankfurter | 60s |
| Wetter | Open-Meteo | 10min |
| Luftqualität | Open-Meteo | 60min |
| Sensornetze | Off-grid Pi-Nodes | 30s |
| OSINT | ip-api, BigDataCloud, DNS | On-demand |
| KI-Analyse | Ollama (lokal) | Streaming |

---

## Layer 1: Erweiterung auf urbane Infrastruktur (Open Data)

### 1.1 Verkehr & Mobilität (keine Auth, öffentlich verfügbar)

| Feed | Quelle | Status | Integration |
|------|--------|--------|-------------|
| **GTFS-Realtime** | TransitFeeds.com | Kostenlos, 1500+ Agenturen | ÖPNV-Livepositionen, Verspätungen |
| **Verkehrszählung** | citypulse.eu (EU) | Open Data | Straßenbelastung pro Knoten |
| **Fahrzeugzulassungen** | Kraftfahrt-Bundesamt (DE) | CSV-Archive | Flottenzusammensetzung pro PLZ |
| **Radverkehr** | OpenStreetMap + Strava Metro | OSM: frei, Strava: Academic | Heatmaps aktiver Mobilität |
| **Maritime AIS** | AISHub / MarineTraffic (Free) | Rate-limited | Schiffspositionen global |

### 1.2 Energie & Versorgung (Open Data, nicht SCADA)

| Feed | Quelle | Status |
|------|--------|--------|
| **Stromnetz (DE)** | Bundesnetzagentur SMARD API | Frei, JSON, 15min-Auflösung |
| **Erneuerbare Erzeugung** | ENTSO-E Transparency Platform | Frei, 1h-Verzögerung |
| **Strompreis (Day-Ahead)** | ENTSO-E / aWattar | Frei |
| **Wasserverbrauch** | WaterSmart (US-Städte), lokale Open Data Portale | Fragmentiert |
| **Solar-Potenzial** | Global Solar Atlas (World Bank) | Frei, GeoTIFF |

### 1.3 Umwelt & Gesundheit

| Feed | Quelle | Status |
|------|--------|--------|
| **UV-Index** | Open-Meteo (bereits integriert) | Frei |
| **Pollen** | DWD / MeteoSwiss (via Open Data) | Frei, saisonal |
| **Lärmpegel** | Open Noise Map (EU H2020) | Teilweise Open |
| **Wasserqualität** | EU Bathing Water Directive API | Frei, saisonal |
| **Waldbrände** | NASA FIRMS (MODIS/VIIRS) | Frei, Near Real-Time |
| **Flusspegel** | Pegelonline / USGS WaterWatch | Frei, 15min |

### 1.4 Staat & Verwaltung

| Feed | Quelle | Status |
|------|--------|--------|
| **Wahlergebnisse** | Bundeswahlleiter / OpenElections | Frei, CSV/JSON |
| **Haushaltsdaten** | OpenBudgets.eu / OffenerHaushalt.de | Frei, strukturiert |
| **Baugenehmigungen** | Leika / lokale Open Data Portale | Fragmentiert |
| **Polizeiberichte** | Polizei Berlin, Hamburg, etc. (Open Data) | Frei, teilweise maschinenlesbar |
| **Gerichtsurteile** | OpenLegalData.de | Frei, NLP-fähig |
| **Lobbyregister** | EU Transparency Register / Bundestag | Frei, CSV |

---

## Layer 2: Theoretische Steuerung — Was technisch möglich wäre

> **Wichtig**: Dieser Layer ist eine **Gedankenübung** über die Grenzen von Open Data. Die tatsächliche Steuerung kritischer Infrastruktur (Ampeln, Stromnetz, Wasserpumpen) erfordert physischen Zugang zu SCADA/ICS-Systemen und ist in allen demokratischen Rechtsordnungen **illegal ohne Autorisierung**.

### Was existiert wirklich?

| System | Offene Schnittstelle? | Realität |
|--------|----------------------|----------|
| **Ampeln (Signalsteuerung)** | NTLIP / SPaT (US), OCIT-C (EU) | Nur für zugelassene Verkehrsrechner. Keine öffentlichen Endpunkte. |
| **Straßenlaternen** | TALQ / Zhaga-D4i | Proprietär, Gateway-basiert, verschlüsselt. |
| **Stromnetz (Schaltanlagen)** | IEC 61850 (GOOSE/MMS) | Air-gapped oder VLAN-isoliert. Kein Internetzugang. |
| **Wasserversorgung** | Modbus / DNP3 | Ältere Anlagen oft sogar ohne Netzwerk. |
| **ÖPNV-Zentralrechner** | VDV 454 (DE) / SIRI (EU) | Aufbereitete GTFS-Realtime ist die öffentliche Facade. |

### Was eine positive Plattform stattdessen tun kann:

1. **Transparenz-Monitoring**: Zeige, dass eine Ampel seit 30 Sekunden auf Rot steht, während keine Fußgänger kommen. Das ist öffentlich beobachtbar.
2. **Anomalie-Erkennung**: "Dieser Transformator hat seit 6h keinen Temperaturwechsel gemeldet" (via ENTSO-E).
3. **Crowdsourced Verifikation**: Bürger melden: "Straßenlaterne in XY aus". Aggregiert auf Karte.
4. **Simulation, keine Steuerung**: "Wenn hier Grünlicht 5s länger wäre, würden 120 Autos/h weniger im Stau stehen." (Daten: OpenStreetMap + GTFS + OpenSky)

---

## Layer 3: Technische Architektur für Maximal-Dichte

### 3.1 Data Ingestion (Was wir bauen können)

```
┌─────────────────────────────────────────────────────────────────┐
│                    WORLDBASE CORE (bereits da)                   │
│  FastAPI + SQLite + httpx + In-Memory TTL-Cache                 │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
   ┌────▼────┐         ┌────▼────┐          ┌────▼────┐
   │ STATIC  │         │ DYNAMIC │          │ STREAM  │
   │ Feeds   │         │ Feeds   │          │ Feeds   │
   │ (REST)  │         │ (REST)  │          │ (WS/SSE)│
   └─────────┘         └─────────┘          └─────────┘
   GTFS Static         GTFS-RT            AIS Stream
   OSM PBF extracts   SMARD              ADS-B Beast
   Census data        ENTSO-E            MQTT (Public)
   Lobbyregister      Open-Meteo         NASA FIRMS
```

### 3.2 Neue Komponenten (Roadmap)

| Komponente | Zweck | Aufwand |
|------------|-------|---------|
| `gtfs_ingestor.py` | GTFS-Static + Realtime Parser | 2-3 Tage |
| `osm_extractor.py` | Overpass-QL Abfragen für POI, Infrastruktur | 1-2 Tage |
| `smard_bridge.py` | BNetzA Stromdaten (JSON) | 0.5 Tage |
| `entsoe_bridge.py` | XML-Parser für ENTSO-E | 1-2 Tage |
| `nasa_firms.py` | FIRMS CSV Download + Ingest | 0.5 Tage |
| `buerger_melder.py` | POST-Endpoint für Crowd-Reports | 0.5 Tage |
| `simulation_engine.py` | Was-wäre-wenn-Verkehrssimulation | 1 Woche |

### 3.3 Frontend: Neue Visualisierungs-Layer

| Layer | Technik | Datenquelle |
|-------|---------|-------------|
| **Verkehrsknoten** | Cesium polyline color by speed | GTFS-RT + OSM |
| **Stromfluss** | Particle system auf Cesium | SMARD |
| **Wärmebild** | WebGL shader (bereits NVG/Thermal) | NASA FIRMS / Sensoren |
| **Bürger-Reports** | Clustered pins mit Confidence | SQLite + POST |
| **Simulation-Overlay** | Ghost-Layer (halbe Opazität) | Simulation Engine |

---

## Layer 4: Konkrete Nächste Schritte für WorldBase

### Phase A: Verkehr (2 Tage)
1. GTFS-Realtime-Ingestor für Berlin / Hamburg / München
2. Frontend: Bus/Bahn-Livepositionen als bewegte Icons auf dem Globe
3. Verspätungs-Heatmap: Linienfarbe = pünktlich (grün) vs. verspätet (rot)

### Phase B: Energie (1 Tag)
1. SMARD-Bridge: Stromerzeugung pro Quelle (Wind, Solar, Kohle, Atom)
2. Frontend: Deutschlandkarte mit Kraftwerken als pulsierende Kreise (Größe = Leistung)
3. Strompreis-Alarm: Push-Notification bei negativen Strompreisen

### Phase C: Bürgernahe Daten (2 Tage)
1. OpenStreetMap-Overpass-Integration: Baustellen, Polizeiwachen, Krankenhäuser
2. Bürger-Melder: POST /api/citizen/report mit lat/lon/category/photo
3. Frontend: "Melden"-Button auf Globe, Reports mit Upvote/Downvote

### Phase D: Simulation (1 Woche)
1. Mini-Verkehrssimulation: OSM-Straßennetz + Fahrzeug-Agenten
2. Was-wäre-wenn-Szenarien: "Mehr Radwege → weniger Stau" (Open Data basiert)

---

## Layer 5: Rechtliche & Ethische Rahmung

### Was wir NIEMALS tun werden:
- Kein Zugriff auf geschlossene SCADA/ICS-Systeme
- Keine Aggregation zu personenidentifizierbaren Bewegungsprofilen (kein Mass-Tracking)
- Kein Verkauf von Daten
- Keine exklusive Datenpartnerschaften (alle Daten sind für alle gleichermaßen offen)

### Was wir aktiv fördern:
- **Datenspenden**: Städte können eigene Open Data an WorldBase anbinden
- **Fehlerkorrektur**: Bürger melden fehlerhafte Daten → Verifikation → Korrektur
- **Lokale Instanzen**: Jede Kommune kann WorldBase selbst hosten (kein Vendor Lock-in)

---

## Fazit

Die "theoretische Steuerung von Ampeln" ist ein rotes Herring. Das wahre Machtpotenzial liegt in der **symmetrischen Transparenz**: Wenn jeder Bürger sieht, wo Verkehrsflaschenhälse entstehen, wo Strom aus Kohle kommt, wo Polizeikontrollen häufig sind — dann entsteht Druck auf politische Lösungen. Die Plattform ist das **Röntgengerät für die Stadt**, nicht der **Fernbedienung**.

WorldBase ist bereits die technische Basis. Die nächsten 2 Wochen könnten GTFS, SMARD und Bürger-Reporting hinzufügen. Dann hätten wir eine Plattform, die für jeden Bürger das bietet, was Palantir für Regierungen bietet — nur **offen, lokal und positiv**.

---

## Recherchierte Quellen (verifiziert 2026-06-02)

- GTFS-Realtime: https://gtfs.org/documentation/realtime/reference/
- SMARD API (DE): https://www.smard.de/page/en/download-center/download
- ENTSO-E Transparency: https://transparency.entsoe.eu/
- NASA FIRMS: https://firms.modaps.eosdis.nasa.gov/
- OpenStreetMap Overpass: https://overpass-api.de/
- TransitFeeds: https://transitfeeds.com/
- EU Open Data: https://data.europa.eu/
