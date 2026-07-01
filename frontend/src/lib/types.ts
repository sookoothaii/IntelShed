/** Shared frontend types used across layer hooks and components. */

/** Globe layer statistics counters. */
export type Stats = {
  aircraft: number;
  satellites: number;
  quakes: number;
  events: number;
  nodes: number;
  military: number;
  spaceweather: number;
  geopolitics: number;
  wildfires: number;
  lightning: number;
  transit: number;
  trafficCams: number;
  maritime: number;
  gdacs: number;
  hazards: number;
  outages: number;
  volcanoes: number;
  airquality: number;
  weather: number;
  pegel: number;
  osint: number;
  intelFt: number;
  flowsint: number;
  darkweb: number;
  energy: number;
  piAis: number;
  acled: number;
  osm: number;
  weatherForecast: number;
  cii: number;
  fps: number;
};

/** Feed HUD metadata (source labels, timestamps, etc.). */
export type FeedHud = Record<string, string>;

/** Heatmap metadata from fusion cells. */
export type HeatmapMeta = {
  cells: number;
  max: number;
  contrib: Record<string, number>;
};

/** Cesium renderError event payload. */
export type CesiumRenderErrorEvent = {
  message?: string;
  error?: Error & { stack?: string };
};

/** Cesium tileLoadError event payload. */
export type CesiumTileLoadErrorEvent = {
  message?: string;
  url?: string;
  statusCode?: number;
};

/** Generic API response envelope for feed endpoints. */
export type FeedResponse<T = unknown> = {
  source?: string;
  count?: number;
  data?: T;
  [key: string]: unknown;
};

/** OpenSky aircraft state array (ICAO24, callsign, origin_country, ...). */
export type AircraftState = [
  string, // 0: icao24
  string, // 1: callsign
  string, // 2: origin_country
  number | null, // 3: time_position
  number | null, // 4: last_contact
  number | null, // 5: longitude
  number | null, // 6: latitude
  number | null, // 7: baro_altitude
  boolean, // 8: on_ground
  number | null, // 9: velocity
  number | null, // 10: true_track
  number | null, // 11: vertical_rate
  number | null, // 12: sensors
  number | null, // 13: geo_altitude
  string | null, // 14: squawk
  boolean, // 15: spi
  number, // 16: position_source
];

export type AircraftApiResponse = {
  states: AircraftState[];
  source?: string;
};

// ── Layer hook API response types ──────────────────────────────────────────────

/** Geopolitics disaster entry. */
export type GeopoliticsDisaster = {
  lat: number | null;
  lon: number | null;
  name: string;
  status?: string;
  id?: string;
  source?: string;
  url?: string;
};

/** Fusion heatmap cell. */
export type HeatmapCell = {
  lat: number;
  lon: number;
  score: number;
  intensity: number;
  sources?: string[];
  samples?: HeatmapSample[];
  delta_score?: number | null;
  baseline_score?: number | null;
  cell_id?: string;
};

export type HeatmapSample = {
  source: string;
  label: string;
};

export type HeatmapApiResponse = {
  cells: HeatmapCell[];
  max_intensity?: number;
  contributors?: Record<string, number>;
};

/** Hazards alert (IPAWS/NOAA). */
export type HazardsAlert = {
  lat: number | null;
  lon: number | null;
  event?: string;
  title?: string;
  source?: string;
  area?: string;
  headline?: string;
  severity?: string;
  urgency?: string;
  area_desc?: string;
  feed?: string;
  effective?: string;
  expires?: string;
};

/** GDELT geo event. */
export type GdeltGeoEvent = {
  lat: number | null;
  lon: number | null;
  name?: string;
  url?: string;
  date?: string;
};

export type HazardsApiResponse = {
  alerts: HazardsAlert[];
  count?: number;
  geocoded?: number;
  gdelt?: { events: GdeltGeoEvent[] } | null;
};

/** Lightning strike. */
export type LightningStrike = {
  lat: number;
  lon: number;
  time: string;
  stations?: number;
  participants?: number;
};

/** Maritime vessel. */
export type MaritimeVessel = {
  lat: number | null;
  lon: number | null;
  mmsi?: string;
  name?: string;
  type?: string;
  course?: number;
  speed?: number;
  destination?: string;
  flag?: string;
  length?: number;
};

/** Military aircraft. */
export type MilitaryAircraft = {
  lat: number | null;
  lon: number | null;
  hex: string;
  flight?: string;
  type?: string;
  alt?: number;
  speed?: number;
  squawk?: string;
};

/** Node mesh sub-node. */
export type MeshNode = {
  id: string;
  lat?: number | null;
  lon?: number | null;
  name?: string;
  snr?: number;
  last_seen?: string;
};

/** intelshed node. */
export type WbNode = {
  node_id: string;
  lat: number | null;
  lon: number | null;
  name?: string;
  online?: boolean;
  health?: {
    cpu_temp_c?: number;
    services?: Record<string, unknown>;
    ais_receiver?: {
      active: boolean;
      receiver_type: string;
      messages_received: number;
      vessels_seen: number;
      last_message_at: string;
      aishub_connected: boolean;
      pc_connected: boolean;
      lat: number | null;
      lon: number | null;
      range_km: number;
    };
  };
  sensors?: Record<string, unknown>;
  mesh?: MeshNode[];
  pihole?: Record<string, unknown>;
  age_seconds?: number;
};

/** Intel FtM entity (geolocated). */
export type IntelEntity = {
  id: string;
  lat: number | null;
  lon: number | null;
  caption?: string;
  schema?: string;
  datasets?: string[];
  last_seen?: string;
};

/** Darkweb mention. */
export type DarkwebMention = {
  id: string;
  properties?: {
    name?: string[];
    source?: string[];
    url?: string[];
  };
  datasets?: string[];
};

/** Outage item (IODA/Cloudflare). */
export type OutageItem = {
  lat: number | null;
  lon: number | null;
  title?: string;
  source?: string;
  level?: string;
  kind?: string;
  duration_h?: number;
  datasource?: string;
  status?: string;
  type?: string;
  start?: string;
};

/** Outages API response. */
export type OutagesApiResponse = {
  items?: OutageItem[];
  count?: number;
  geocoded?: number;
  sources?: string[];
  error?: string;
};
export type PegelGauge = {
  lat: number | null;
  lon: number | null;
  uuid?: string;
  name?: string;
  water?: string;
  value?: number;
  unit?: string;
  severity?: string;
  state_mnw_mhw?: string;
  state_nsw_hsw?: string;
  timestamp?: string;
};

/** Earthquake. */
export type Earthquake = {
  lat: number | null;
  lon: number | null;
  mag?: number;
  place?: string;
  depth?: number;
  time?: number;
};

/** Satellite TLE cache entry. */
export type SatelliteCacheEntry = {
  name: string;
  rec: ReturnType<typeof import('satellite.js').twoline2satrec>;
};

/** Trail point (aircraft trail). */
export type TrailPoint = {
  lat: number;
  lon: number;
  alt?: number | null;
};

/** Transit vehicle. */
export type TransitVehicle = {
  lat: number | null;
  lon: number | null;
  id?: string;
  route_id?: string;
  bearing?: number;
  speed?: number;
  label?: string;
};

/** Volcano. */
export type Volcano = {
  lat: number | null;
  lon: number | null;
  name?: string;
  country?: string;
  type?: string;
  last_eruption?: string;
  elevation_m?: number;
  active?: boolean;
  number?: string;
  evidence?: string;
};

/** Volcanoes API response. */
export type VolcanoesApiResponse = {
  volcanoes?: Volcano[];
  count?: number;
  active_count?: number;
  error?: string;
};

/** Traffic camera. */
export type TrafficCamera = {
  id: string;
  name?: string;
  lat?: number;
  lon?: number;
  source?: string;
  road?: string;
  detail_url?: string;
};

/** Traffic cameras API response. */
export type TrafficCamsApiResponse = {
  cameras?: TrafficCamera[];
  count?: number;
  source?: string;
  error?: string;
};

/** GDELT pulse article. */
export type GdeltArticle = {
  title?: string;
  url?: string;
  domain?: string;
  sourcecountry?: string;
  seendate?: string;
  date?: string;
  lat?: number | null;
  lon?: number | null;
};

/** GDELT pulse API response. */
export type GdeltPulseApiResponse = {
  articles?: GdeltArticle[];
  count?: number;
  error?: string;
  region?: string;
  stale?: boolean;
};

/** Weather grid cell. */
export type WeatherCell = {
  lat: number | null;
  lon: number | null;
  temperature_c?: number | null;
  wind_speed_ms?: number | null;
  precip_mm_3h?: number | null;
};

/** Wildfires API response. */
export type WildfiresApiResponse = {
  fires?: WildfireRow[];
  count?: number;
  source?: string;
  errors?: unknown;
};

export type WildfireRow = {
  lon?: number | null;
  lat?: number | null;
  confidence?: number | null;
  confidence_label?: string | null;
  brightness?: number | null;
  frp?: number | null;
  satellite?: string | null;
  zone?: string | null;
  acq_date?: string | null;
};
