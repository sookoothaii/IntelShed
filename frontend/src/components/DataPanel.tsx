import { useState, useEffect } from 'react';
import { fetchApi } from '../lib/networkFetch';
import type { FocusTarget } from '../lib/focus';
import Sparkline from './Sparkline';

interface Sat {
  id: string;
  name: string;
  lat: number;
  lon: number;
  alt_km: number;
  vel_kms: number;
  tle1?: string;
  tle2?: string;
}
interface Quake {
  id: string;
  place: string;
  mag: number;
  time: string;
  lat: number;
  lon: number;
  depth: number;
  tsunami?: number;
  url?: string;
}
interface WEvent {
  id: string;
  title: string;
  date: string;
  lat: number;
  lon: number;
  sources: string[];
  category?: string;
  categories?: { id: string; title: string }[];
  magnitude?: { mag: number; type: string };
  unit?: string;
  points?: { lat: number; lon: number }[];
  closed?: string;
  link?: string;
}
interface Disaster {
  id: string;
  type: string;
  name: string;
  date: string;
  lat: number;
  lon: number;
  severity: string;
  source: string;
  status?: string;
}
interface MilitaryAircraft {
  icao24: string;
  callsign: string;
  type: string;
  desc: string;
  lat: number;
  lon: number;
  alt_m: number;
  speed_kmh: number;
  operator: string;
  hex?: string;
  flight?: string;
  alt?: number;
  speed?: number;
  squawk?: string;
}
interface Situation {
  id: string;
  title: string;
  severity: string;
  created_at: string;
  entities: { id: string; name?: string; type?: string }[];
  summary: string;
  location?: { lat: number; lon: number };
  type?: string;
}
interface AirQualityCity {
  city: string;
  aqi: number;
  pm25: number;
  lat: number;
  lon: number;
  time: string;
  pm10?: number;
}
interface GDACSAlert {
  id: string;
  name: string;
  type: string;
  severity: string;
  date: string;
  lat: number;
  lon: number;
  url: string;
  title?: string;
  description?: string;
  published?: string;
  link?: string;
}
interface RiverGauge {
  uuid: string;
  name: string;
  water: string;
  lat: number;
  lon: number;
  value: number;
  unit: string;
  severity: string;
  timestamp: string;
  state_mnw_mhw?: string;
  state_nsw_hsw?: string;
}
interface MarketQuote {
  symbol: string;
  label: string;
  name: string;
  price: number;
  currency?: string;
  trend_pct?: number;
  change_pct?: number;
  change_1d?: number;
  change_30d?: number;
  spark?: number[];
}
interface MarketCoin {
  id: string;
  symbol: string;
  name: string;
  price: number;
  market_cap_rank?: number;
  change_24h?: number;
  change_7d?: number;
  spark?: number[];
}
interface EnergyData {
  total_generation_mw?: number;
  co2_g_per_kwh?: number;
  load?: { latest_mw?: number };
  day_ahead_price?: { latest_eur_mwh?: number };
  generation?: Record<string, { latest_mw?: number }>;
}
interface StocksData {
  count?: number;
  source?: string;
  updated?: string;
  error?: string;
  indices?: MarketQuote[];
  commodities?: MarketQuote[];
  rates_fx?: MarketQuote[];
  risk?: {
    level: string;
    score: number;
    vix?: number;
    advancers?: number;
    decliners?: number;
    avg_change?: number;
    notes?: string[];
  };
}
interface MaritimeVessel {
  name?: string;
  mmsi?: string;
  type?: string;
  lat?: number;
  lon?: number;
  course?: number;
  speed?: number;
  destination?: string;
  flag?: string;
  length?: number;
}
interface EuPriceSlot {
  position: number;
  price_eur_mwh?: number;
}
interface WebcamEntry {
  id: string;
  name?: string;
  lat?: number;
  lon?: number;
  source?: string;
  category?: string;
  url?: string;
  embed?: string | null;
  detail_url?: string;
  country?: string;
}
interface CveEntry {
  cve_id: string;
  vendor?: string;
  product?: string;
  date_added?: string;
  ransomware?: string;
}

const SAT_GROUPS = ['starlink', 'stations', 'gps-ops', 'weather'];

import WebcamSection from './WebcamSection';
import PegelSparkline from './PegelSparkline';
import StacPanel from './StacPanel';
import SatellitePanel from './SatellitePanel';
import SanctionsPanel from './SanctionsPanel';
import IntelGraphPanel from './IntelGraphPanel';
import RelationshipExplorer from './RelationshipExplorer';
import CredentialManagerPanel from './CredentialManagerPanel';
import EdgePanel from './EdgePanel';
import WeatherSection from './WeatherSection';
import FeedsStatusPanel from './FeedsStatusPanel';
import {
  GdeltFeedPanel,
  OutagesPanel,
  HazardsPanel,
  VolcanoesPanel,
  TrafficPanel,
  LightningMapPanel,
} from './DataFeedPanels';
import WildfiresPanel from './WildfiresPanel';
import FeatureFlagsPanel from './FeatureFlagsPanel';
import DarkwebPanel from './DarkwebPanel';
import CiiPanel from './CiiPanel';
import TelegramPanel from './TelegramPanel';
import { ErrorBoundary } from './ErrorBoundary';
import { useHudSessionState } from '../lib/hudSessionState';

export const DATA_TABS = [
  'edge',
  'feeds',
  'aircraft',
  'satellites',
  'seismic',
  'events',
  'spaceweather',
  'geopolitics',
  'gdelt',
  'gdacs',
  'hazards',
  'outages',
  'military',
  'maritime',
  'situations',
  'airquality',
  'pegel',
  'weather',
  'wildfires',
  'lightning',
  'volcanoes',
  'energy',
  'eu-energy',
  'stocks',
  'traffic',
  'webcams',
  'cve',
  'satellite',
  'stac',
  'sanctions',
  'intel',
  'relationships',
  'credentials',
  'darkweb',
  'cii',
  'telegram',
  'flags',
] as const;
export type DataTab = (typeof DATA_TABS)[number];

export function isDataTab(v: unknown): v is DataTab {
  return typeof v === 'string' && (DATA_TABS as readonly string[]).includes(v);
}

export default function DataPanel({
  onFocus,
  onOpenWindyMap,
  intelEntityId,
}: {
  onFocus: (f: Omit<FocusTarget, 'ts'>) => void;
  onOpenWindyMap?: (lat: number, lon: number) => void;
  intelEntityId?: string | null;
}) {
  const fmtNum = (n: unknown, digits = 0): string => {
    const v = Number(n);
    return Number.isFinite(v) ? v.toFixed(digits) : '—';
  };
  const fmtCompact = (n: unknown): string => {
    const v = Number(n);
    if (!Number.isFinite(v)) return '—';
    const abs = Math.abs(v);
    if (abs >= 1e12) return (v / 1e12).toFixed(2) + 'T';
    if (abs >= 1e9) return (v / 1e9).toFixed(2) + 'B';
    if (abs >= 1e6) return (v / 1e6).toFixed(2) + 'M';
    if (abs >= 1e3) return (v / 1e3).toFixed(1) + 'K';
    return v.toFixed(0);
  };
  const fmtPrice = (n: unknown): string => {
    const v = Number(n);
    if (!Number.isFinite(v)) return '—';
    if (v >= 1000) return v.toLocaleString('en-US', { maximumFractionDigits: 0 });
    if (v >= 1) return v.toLocaleString('en-US', { maximumFractionDigits: 2 });
    return v.toLocaleString('en-US', { maximumFractionDigits: 6 });
  };
  const pctColor = (v: unknown): string => (Number(v) >= 0 ? '#00e5a0' : '#ff4d5e');
  const fmtPct = (v: unknown, digits = 2): string => {
    const n = Number(v);
    if (!Number.isFinite(n)) return '—';
    return (n >= 0 ? '+' : '') + n.toFixed(digits) + '%';
  };
  const riskColor = (level?: string): string => {
    switch (level) {
      case 'CALM':
        return '#00e5a0';
      case 'NORMAL':
        return '#22d3ee';
      case 'ELEVATED':
        return '#ffd23f';
      case 'HIGH':
        return '#ff8c42';
      case 'EXTREME':
        return '#ff4d5e';
      default:
        return '#6f8c84';
    }
  };
  const fngColor = (v: unknown): string => {
    const n = Number(v);
    if (!Number.isFinite(n)) return '#6f8c84';
    if (n < 25) return '#ff4d5e';
    if (n < 45) return '#ff8c42';
    if (n < 55) return '#ffd23f';
    if (n < 75) return '#7ed957';
    return '#00e5a0';
  };
  const [tab, setTab] = useHudSessionState<DataTab>('dataTab', 'aircraft', isDataTab);

  useEffect(() => {
    if (intelEntityId) setTab('intel');
  }, [intelEntityId, setTab]);
  const [aircraft, setAircraft] = useState<(string | number | null)[][]>([]);
  const [satellites, setSatellites] = useState<Sat[]>([]);
  const [satGroup, setSatGroup] = useHudSessionState(
    'dataSatGroup',
    'starlink',
    (v): v is string => typeof v === 'string' && v.length > 0,
  );
  const [quakes, setQuakes] = useState<Quake[]>([]);
  const [events, setEvents] = useState<WEvent[]>([]);
  const [iss, setIss] = useState<{
    latitude?: number;
    longitude?: number;
    altitude?: number;
    velocity?: number;
    visibility?: string;
    footprint?: number;
    lat?: number;
    lon?: number;
    alt_km?: number;
    vel_kms?: number;
    name?: string;
  } | null>(null);
  const [spaceweather, setSpaceweather] = useState<{
    k_index?: number;
    kp_index?: number;
    scale?: string;
    aurora_visible_midlat?: boolean;
    hf_radio_impact?: boolean;
    history?: unknown[];
    bz_gsm?: number;
    solar_wind_speed?: number;
    density?: number;
    updated?: string;
    error?: string;
  } | null>(null);
  const [geopolitics, setGeopolitics] = useState<{
    count: number;
    disasters: Disaster[];
    error?: string;
  } | null>(null);
  const [markets, setMarkets] = useState<{
    coins?: MarketCoin[];
    global?: { total_market_cap_usd?: number; market_cap_change_24h?: number };
    risk?: unknown;
    fear_greed?: { value?: number; label?: string };
    source?: string;
  } | null>(null);
  const [military, setMilitary] = useState<MilitaryAircraft[]>([]);
  const [situations, setSituations] = useState<Situation[]>([]);
  const [airquality, setAirquality] = useState<{
    cities: AirQualityCity[];
    updated: string;
    error?: string;
  } | null>(null);
  const [gdacs, setGdacs] = useState<{
    count: number;
    alerts: GDACSAlert[];
    error?: string;
  } | null>(null);
  const [pegel, setPegel] = useState<{
    count: number;
    alerts: number;
    gauges: RiverGauge[];
    error?: string;
  } | null>(null);
  const [energy, setEnergy] = useState<EnergyData | null>(null);
  const [stocks, setStocks] = useState<StocksData | null>(null);
  const [maritime, setMaritime] = useState<{
    count: number;
    vessels: MaritimeVessel[];
    stream_connected?: boolean;
    stream_buffer?: number;
    errors?: string[];
    cached_at: string;
    error?: string;
  } | null>(null);
  const [euEnergy, setEuEnergy] = useState<{
    country: string;
    prices: EuPriceSlot[];
    generation_by_source?: Record<string, number>;
    total_mw?: number;
    demo_mode?: boolean;
    error?: string;
  } | null>(null);
  const [euCountry, setEuCountry] = useHudSessionState(
    'dataEuCountry',
    'de',
    (v): v is string => typeof v === 'string' && v.length > 0,
  );
  const [webcams, setWebcams] = useState<{
    count: number;
    categories: string[];
    webcams: WebcamEntry[];
    cached_at: string;
  } | null>(null);
  const [webcamCategory, setWebcamCategory] = useHudSessionState(
    'dataWebcamCategory',
    '',
    (v): v is string => typeof v === 'string',
  );
  const [cve, setCve] = useState<{
    count: number;
    vulnerabilities: CveEntry[];
    date_released?: string;
    error?: string;
  } | null>(null);
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');

  const fetchFeed = async <T,>(key: string, url: string, setter: (d: T) => void) => {
    setLoading((l) => ({ ...l, [key]: true }));
    setError(null);
    try {
      const r = await fetchApi(url);
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      setter(await r.json());
    } catch (e) {
      setError(`${key}: ${(e as Error).message}`);
    } finally {
      setLoading((l) => ({ ...l, [key]: false }));
    }
  };

  const loadAircraft = () =>
    fetchFeed('aircraft', '/api/aircraft', (d: { states?: (string | number | null)[][] }) =>
      setAircraft(d.states || []),
    );
  const loadSatellites = (g = satGroup) =>
    fetchFeed('satellites', `/api/satellites?group=${g}&limit=500`, (d: { satellites?: Sat[] }) =>
      setSatellites(d.satellites || []),
    );
  const loadQuakes = () =>
    fetchFeed(
      'seismic',
      '/api/earthquakes?period=day&magnitude=2.5',
      (d: { earthquakes?: Quake[] }) => setQuakes(d.earthquakes || []),
    );
  const loadEvents = () =>
    fetchFeed('events', '/api/events?limit=120', (d: { events?: WEvent[] }) =>
      setEvents(d.events || []),
    );
  const loadSpaceweather = async () => {
    setLoading((l) => ({ ...l, spaceweather: true }));
    setError(null);
    try {
      const [swRes, issRes] = await Promise.all([
        fetchApi('/api/spaceweather'),
        fetchApi('/api/iss'),
      ]);
      if (!swRes.ok) throw new Error(`spaceweather ${swRes.status}`);
      if (!issRes.ok) throw new Error(`iss ${issRes.status}`);
      setSpaceweather(await swRes.json());
      setIss(await issRes.json());
    } catch (e) {
      setError(`spaceweather: ${(e as Error).message}`);
    } finally {
      setLoading((l) => ({ ...l, spaceweather: false }));
    }
  };
  const loadGeopolitics = () =>
    fetchFeed(
      'geopolitics',
      '/api/geopolitics',
      (d: { count: number; disasters: Disaster[]; error?: string }) => setGeopolitics(d),
    );
  const loadMilitary = () =>
    fetchFeed('military', '/api/military', (d: { aircraft?: MilitaryAircraft[] }) =>
      setMilitary(d.aircraft || []),
    );
  const loadSituations = () =>
    fetchFeed('situations', '/api/correlations', (d: { situations?: Situation[] }) =>
      setSituations(d.situations || []),
    );
  const loadAirquality = () =>
    fetchFeed(
      'airquality',
      '/api/airquality',
      (d: { cities: AirQualityCity[]; updated: string; error?: string }) => setAirquality(d),
    );
  const loadGdacs = () =>
    fetchFeed('gdacs', '/api/gdacs', (d: { count: number; alerts: GDACSAlert[]; error?: string }) =>
      setGdacs(d),
    );
  const loadPegel = () =>
    fetchFeed(
      'pegel',
      '/api/pegel',
      (d: { count: number; alerts: number; gauges: RiverGauge[]; error?: string }) => setPegel(d),
    );
  const loadEnergy = () => fetchFeed('energy', '/api/energy/de', (d: EnergyData) => setEnergy(d));
  const loadStocks = async () => {
    setLoading((l) => ({ ...l, stocks: true }));
    setError(null);
    try {
      const [stRes, cryptoRes] = await Promise.all([
        fetchApi('/api/markets/stocks'),
        fetchApi('/api/markets/crypto'),
      ]);
      if (!stRes.ok) throw new Error(`stocks ${stRes.status}`);
      if (!cryptoRes.ok) throw new Error(`crypto ${cryptoRes.status}`);
      setStocks(await stRes.json());
      setMarkets(await cryptoRes.json());
    } catch (e) {
      setError(`stocks: ${(e as Error).message}`);
    } finally {
      setLoading((l) => ({ ...l, stocks: false }));
    }
  };
  const loadMaritime = () =>
    fetchFeed(
      'maritime',
      '/api/maritime',
      (d: {
        count: number;
        vessels: MaritimeVessel[];
        stream_connected?: boolean;
        stream_buffer?: number;
        errors?: string[];
        cached_at: string;
        error?: string;
      }) => setMaritime(d),
    );
  const loadEuEnergy = async () => {
    setLoading((l) => ({ ...l, 'eu-energy': true }));
    setError(null);
    try {
      const [r1, r2] = await Promise.all([
        fetchApi(`/api/eu-energy/price/${euCountry}`),
        fetchApi(`/api/eu-energy/generation/${euCountry}`),
      ]);
      if (!r1.ok) throw new Error(`${r1.status} ${r1.statusText}`);
      if (!r2.ok) throw new Error(`${r2.status} ${r2.statusText}`);
      const priceData = await r1.json();
      const genData = await r2.json();
      setEuEnergy({
        ...priceData,
        generation_by_source: genData.generation_by_source,
        total_mw: genData.total_mw,
      });
    } catch (e) {
      setError(`eu-energy: ${(e as Error).message}`);
    } finally {
      setLoading((l) => ({ ...l, 'eu-energy': false }));
    }
  };
  const loadWebcams = () => {
    const url =
      webcamCategory && webcamCategory !== 'all'
        ? `/api/webcams?category=${encodeURIComponent(webcamCategory)}`
        : '/api/webcams';
    fetchFeed(
      'webcams',
      url,
      (d: { count: number; categories: string[]; webcams: WebcamEntry[]; cached_at: string }) =>
        setWebcams(d),
    );
  };
  const loadCve = () =>
    fetchFeed(
      'cve',
      '/api/cve?limit=40',
      (d: { count: number; vulnerabilities: CveEntry[]; date_released?: string; error?: string }) =>
        setCve(d),
    );

  // Auto-load on tab switch
  useEffect(() => {
    setQuery('');
    if (tab === 'edge') {
      /* EdgePanel self-loads */
    } else if (tab === 'aircraft') loadAircraft();
    else if (tab === 'satellites') loadSatellites();
    else if (tab === 'seismic') loadQuakes();
    else if (tab === 'events') loadEvents();
    else if (tab === 'spaceweather') loadSpaceweather();
    else if (tab === 'geopolitics') loadGeopolitics();
    else if (tab === 'military') loadMilitary();
    else if (tab === 'situations') loadSituations();
    else if (tab === 'airquality') loadAirquality();
    else if (tab === 'gdacs') loadGdacs();
    else if (tab === 'pegel') loadPegel();
    else if (tab === 'energy') loadEnergy();
    else if (tab === 'stocks') loadStocks();
    else if (tab === 'maritime') loadMaritime();
    else if (tab === 'eu-energy') loadEuEnergy();
    else if (tab === 'webcams') loadWebcams();
    else if (tab === 'cve') loadCve();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, euCountry, webcamCategory]);

  const q = query.toLowerCase();
  const fAircraft = aircraft.filter(
    (a) => !q || `${a[0]} ${a[1]} ${a[2]}`.toLowerCase().includes(q),
  );
  const fSats = satellites.filter((s) => !q || s.name.toLowerCase().includes(q));
  const fQuakes = quakes.filter((x) => !q || (x.place || '').toLowerCase().includes(q));
  const fEvents = events.filter((x) => !q || `${x.title} ${x.category}`.toLowerCase().includes(q));

  const magColor = (m: number) =>
    m >= 6 ? '#ff2d00' : m >= 4.5 ? '#ff6b35' : m >= 3 ? '#ffd23f' : '#8fb7a9';

  const eventFocus = (x: WEvent): Omit<FocusTarget, 'ts'> => {
    const lines = [
      x.category +
        (x.categories && x.categories.length > 1 ? ` · ${x.categories.slice(1).join(', ')}` : ''),
      `COORD: ${x.lat?.toFixed(3)}, ${x.lon?.toFixed(3)}`,
    ];
    if (x.magnitude != null) lines.push(`MAGNITUDE: ${x.magnitude} ${x.unit || ''}`.trim());
    if (x.date) lines.push(`UPDATED: ${new Date(x.date).toLocaleString()}`);
    if (x.points && x.points.length > 1) lines.push(`TRACK POINTS: ${x.points.length}`);
    lines.push(`STATUS: ${x.closed ? 'CLOSED' : 'ACTIVE'}`);
    return {
      kind: 'event',
      lon: x.lon,
      lat: x.lat,
      height: 450000,
      title: x.title,
      lines,
      link: x.sources?.[0] || x.link,
    };
  };

  const quakeFocus = (x: Quake): Omit<FocusTarget, 'ts'> => ({
    kind: 'quake',
    lon: x.lon,
    lat: x.lat,
    height: 300000,
    title: `M${x.mag?.toFixed(1)} · ${x.place}`,
    lines: [
      `MAGNITUDE: ${x.mag?.toFixed(1)}`,
      `DEPTH: ${x.depth?.toFixed(1)} km`,
      `COORD: ${x.lat?.toFixed(3)}, ${x.lon?.toFixed(3)}`,
      `TIME: ${new Date(x.time).toLocaleString()}`,
      x.tsunami ? 'TSUNAMI: ⚠ POTENTIAL' : 'TSUNAMI: none',
    ],
    link: x.url,
  });

  return (
    <div className={`panel${tab === 'lightning' ? ' panel-lightning' : ''}`}>
      <h2>Live Feeds</h2>

      <div className="data-tabs">
        {DATA_TABS.map((t) => (
          <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>
            {t.toUpperCase()}
          </button>
        ))}
      </div>

      {error && <div className="data-error">{error}</div>}

      {tab === 'edge' && <EdgePanel onFocus={onFocus} />}

      {tab === 'feeds' && <FeedsStatusPanel onFocus={onFocus} />}

      {tab === 'gdelt' && <GdeltFeedPanel />}

      {tab === 'outages' && <OutagesPanel onFocus={onFocus} />}

      {tab === 'hazards' && <HazardsPanel onFocus={onFocus} />}

      {tab === 'volcanoes' && <VolcanoesPanel onFocus={onFocus} />}

      {tab === 'traffic' && <TrafficPanel onFocus={onFocus} />}

      {tab === 'lightning' && <LightningMapPanel />}

      {(tab === 'aircraft' || tab === 'satellites' || tab === 'seismic' || tab === 'events') && (
        <div className="data-toolbar">
          <input
            className="data-search"
            placeholder="Filter…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {tab === 'satellites' && (
            <div className="data-groups">
              {SAT_GROUPS.map((g) => (
                <button
                  key={g}
                  className={satGroup === g ? 'on' : ''}
                  onClick={() => {
                    setSatGroup(g);
                    loadSatellites(g);
                  }}
                >
                  {g.toUpperCase()}
                </button>
              ))}
            </div>
          )}
          <button
            className="data-refresh"
            onClick={() => {
              if (tab === 'aircraft') loadAircraft();
              else if (tab === 'satellites') loadSatellites();
              else if (tab === 'seismic') loadQuakes();
              else loadEvents();
            }}
          >
            ↻ REFRESH
          </button>
        </div>
      )}

      {tab === 'aircraft' && (
        <section>
          <span className="data-count">
            {fAircraft.length} / {aircraft.length} aircraft
          </span>
          <table className="data-table">
            <thead>
              <tr>
                <th>ICAO24</th>
                <th>Callsign</th>
                <th>Country</th>
                <th>Lat</th>
                <th>Lon</th>
                <th>Alt (m)</th>
                <th>Vel (m/s)</th>
                <th>Hdg</th>
              </tr>
            </thead>
            <tbody>
              {fAircraft.slice(0, 100).map((a, i) => (
                <tr key={i}>
                  <td>{a[0]}</td>
                  <td>{a[1] || '—'}</td>
                  <td>{a[2]}</td>
                  <td>{a[6] != null ? Number(a[6]).toFixed(2) : '—'}</td>
                  <td>{a[5] != null ? Number(a[5]).toFixed(2) : '—'}</td>
                  <td>{a[7] != null ? Math.round(Number(a[7])) : '—'}</td>
                  <td>{a[9] != null ? Number(a[9]).toFixed(1) : '—'}</td>
                  <td>{a[10] != null ? Math.round(Number(a[10])) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'satellites' && (
        <section>
          <span className="data-count">
            {fSats.length} / {satellites.length} sats · {satGroup}
          </span>
          <table className="data-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>NORAD</th>
                <th>Inclination</th>
                <th>Period (min)</th>
              </tr>
            </thead>
            <tbody>
              {fSats.slice(0, 100).map((s, i) => {
                const t2 = s.tle2 || '';
                const norad = t2.substring(2, 7).trim();
                const inc = t2.substring(8, 16).trim();
                const mm = parseFloat(t2.substring(52, 63).trim());
                const period = mm ? (1440 / mm).toFixed(1) : '—';
                return (
                  <tr key={i}>
                    <td>{s.name}</td>
                    <td>{norad}</td>
                    <td>{inc}°</td>
                    <td>{period}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'seismic' && (
        <section>
          <span className="data-count">
            {fQuakes.length} / {quakes.length} earthquakes · 24h · click to locate
          </span>
          <table className="data-table clickable">
            <thead>
              <tr>
                <th>Mag</th>
                <th>Place</th>
                <th>Depth (km)</th>
                <th>Time</th>
                <th>Tsunami</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {fQuakes.slice(0, 100).map((x) => (
                <tr key={x.id} onClick={() => onFocus(quakeFocus(x))}>
                  <td style={{ color: magColor(x.mag), fontWeight: 'bold' }}>
                    {x.mag?.toFixed(1)}
                  </td>
                  <td>{x.place}</td>
                  <td>{x.depth != null ? x.depth.toFixed(1) : '—'}</td>
                  <td>{new Date(x.time).toLocaleString()}</td>
                  <td>{x.tsunami ? '⚠ YES' : '—'}</td>
                  <td className="locate-cell">◎ LOCATE</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'events' && (
        <section>
          <span className="data-count">
            {fEvents.length} / {events.length} natural events · click to locate
          </span>
          <table className="data-table clickable">
            <thead>
              <tr>
                <th>Category</th>
                <th>Title</th>
                <th>Lat</th>
                <th>Lon</th>
                <th>Date</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {fEvents.slice(0, 100).map((x) => (
                <tr key={x.id} onClick={() => onFocus(eventFocus(x))}>
                  <td>{x.category}</td>
                  <td>{x.title}</td>
                  <td>{x.lat?.toFixed(2)}</td>
                  <td>{x.lon?.toFixed(2)}</td>
                  <td>{x.date ? new Date(x.date).toLocaleDateString() : '—'}</td>
                  <td className="locate-cell">◎ LOCATE</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'spaceweather' && (
        <section>
          <button onClick={loadSpaceweather} disabled={loading['spaceweather']}>
            {loading['spaceweather'] ? 'Loading…' : '↻ Refresh'}
          </button>
          {iss && (
            <>
              <span className="data-count">ISS position</span>
              <div className="iss-grid" style={{ marginBottom: 12 }}>
                <div className="iss-card">
                  <span>LATITUDE</span>
                  <strong>{Number(iss.latitude).toFixed(4)}°</strong>
                </div>
                <div className="iss-card">
                  <span>LONGITUDE</span>
                  <strong>{Number(iss.longitude).toFixed(4)}°</strong>
                </div>
                <div className="iss-card">
                  <span>ALTITUDE</span>
                  <strong>{Number(iss.altitude).toFixed(1)} km</strong>
                </div>
                <div className="iss-card">
                  <span>VELOCITY</span>
                  <strong>{Number(iss.velocity).toFixed(0)} km/h</strong>
                </div>
                <div className="iss-card">
                  <span>VISIBILITY</span>
                  <strong>{iss.visibility}</strong>
                </div>
                <div className="iss-card">
                  <span>FOOTPRINT</span>
                  <strong>{Number(iss.footprint).toFixed(0)} km</strong>
                </div>
              </div>
            </>
          )}
          {spaceweather ? (
            <div className="iss-grid">
              <div className="iss-card">
                <span>KP INDEX</span>
                <strong>{spaceweather.kp_index ?? '—'}</strong>
              </div>
              <div className="iss-card">
                <span>SCALE</span>
                <strong>{spaceweather.scale ?? '—'}</strong>
              </div>
              <div className="iss-card">
                <span>AURORA MID-LAT</span>
                <strong>{spaceweather.aurora_visible_midlat ? 'VISIBLE' : 'none'}</strong>
              </div>
              <div className="iss-card">
                <span>HF RADIO</span>
                <strong>{spaceweather.hf_radio_impact ? 'IMPACTED' : 'OK'}</strong>
              </div>
              <div className="iss-card">
                <span>HISTORY</span>
                <strong>{spaceweather.history?.length ?? 0} pts</strong>
              </div>
            </div>
          ) : (
            !iss && <div className="health-status pending">NO DATA</div>
          )}
        </section>
      )}

      {tab === 'geopolitics' && (
        <section>
          <button onClick={loadGeopolitics} disabled={loading['geopolitics']}>
            {loading['geopolitics'] ? 'Loading…' : '↻ Refresh'}
          </button>
          <span className="data-count">{geopolitics?.count ?? 0} disasters · click to locate</span>
          {geopolitics?.error && <div className="data-error">{geopolitics.error}</div>}
          <table className="data-table clickable">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Severity</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(geopolitics?.disasters || []).map((d: Disaster) => (
                <tr
                  key={d.id}
                  onClick={() =>
                    d.lat != null &&
                    d.lon != null &&
                    onFocus({
                      kind: 'geopolitics',
                      lon: d.lon,
                      lat: d.lat,
                      height: 450000,
                      title: d.name,
                      lines: [
                        `Type: ${d.type}`,
                        `Severity: ${d.severity}`,
                        `Status: ${d.status || '—'}`,
                        `Source: ${d.source || '—'}`,
                      ],
                    })
                  }
                >
                  <td>{d.name}</td>
                  <td>{d.type}</td>
                  <td>{d.severity}</td>
                  <td>{d.status}</td>
                  <td className="locate-cell">◎</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'military' && (
        <section>
          <button onClick={loadMilitary} disabled={loading['military']}>
            {loading['military'] ? 'Loading…' : '↻ Refresh'}
          </button>
          <span className="data-count">{military.length} military aircraft</span>
          <table className="data-table clickable">
            <thead>
              <tr>
                <th>Hex</th>
                <th>Flight</th>
                <th>Type</th>
                <th>Lat</th>
                <th>Lon</th>
                <th>Alt (m)</th>
                <th>Speed</th>
                <th>Squawk</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {military.map((a: MilitaryAircraft, i: number) => (
                <tr
                  key={i}
                  onClick={() =>
                    a.lat &&
                    a.lon &&
                    onFocus({
                      kind: 'aircraft',
                      lon: a.lon,
                      lat: a.lat,
                      height: 300000,
                      title: a.flight || a.hex || 'Unknown',
                      lines: [
                        `TYPE: ${a.type || '—'}`,
                        `ALT: ${a.alt ?? '—'} m`,
                        `SPEED: ${a.speed ?? '—'} m/s`,
                        `SQUAWK: ${a.squawk || '—'}`,
                      ],
                    })
                  }
                >
                  <td>{a.hex}</td>
                  <td>{a.flight || '—'}</td>
                  <td>{a.type || '—'}</td>
                  <td>{fmtNum(a.lat, 2)}</td>
                  <td>{fmtNum(a.lon, 2)}</td>
                  <td>{fmtNum(a.alt, 0)}</td>
                  <td>{fmtNum(a.speed, 1)}</td>
                  <td
                    style={{
                      color: ['7500', '7600', '7700'].includes(a.squawk || '')
                        ? '#ff2d00'
                        : 'inherit',
                      fontWeight: ['7500', '7600', '7700'].includes(a.squawk || '')
                        ? 'bold'
                        : 'normal',
                    }}
                  >
                    {a.squawk || '—'}
                  </td>
                  <td className="locate-cell">◎ LOCATE</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'situations' && (
        <section>
          <button onClick={loadSituations} disabled={loading['situations']}>
            {loading['situations'] ? 'Loading…' : '↻ Refresh'}
          </button>
          <span className="data-count">{situations.length} developing situations</span>
          {situations.length === 0 && (
            <div className="health-status pending">No active correlations detected</div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {situations.map((s: Situation, i: number) => (
              <div
                key={i}
                className="iss-card"
                style={{
                  cursor: 'pointer',
                  borderLeft: `3px solid ${s.severity === 'high' ? '#ff2d00' : '#ff6b35'}`,
                }}
                onClick={() =>
                  s.location?.lon &&
                  s.location?.lat &&
                  onFocus({
                    kind: 'situation',
                    lon: s.location.lon,
                    lat: s.location.lat,
                    height: 400000,
                    title: s.title,
                    lines: [`TYPE: ${s.type}`, `SEVERITY: ${s.severity.toUpperCase()}`],
                  })
                }
              >
                <span
                  style={{
                    color: s.severity === 'high' ? '#ff2d00' : '#ff6b35',
                    fontWeight: 'bold',
                  }}
                >
                  {s.severity.toUpperCase()}
                </span>
                <strong>{s.title}</strong>
                <small style={{ color: '#6f8c84' }}>{s.type}</small>
              </div>
            ))}
          </div>
        </section>
      )}

      {tab === 'airquality' && (
        <section>
          <button onClick={loadAirquality} disabled={loading['airquality']}>
            {loading['airquality'] ? 'Loading…' : '↻ Refresh'}
          </button>
          <span className="data-count">
            {airquality?.cities?.length || 0} cities · ASEAN + global · click to locate
          </span>
          {airquality?.updated && (
            <div style={{ fontSize: 11, color: '#6f8c84', marginBottom: 8 }}>
              Updated: {new Date(airquality.updated).toLocaleString()}
            </div>
          )}
          {!airquality?.cities?.length && (
            <div className="health-status pending">No air quality data</div>
          )}
          <table className="data-table clickable">
            <thead>
              <tr>
                <th>City</th>
                <th>PM2.5</th>
                <th>PM10</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(airquality?.cities || []).map((c: AirQualityCity, i: number) => {
                const pm25 = c.pm25 ?? null;
                const color =
                  pm25 == null
                    ? '#6f8c84'
                    : pm25 <= 12
                      ? '#00e5a0'
                      : pm25 <= 35
                        ? '#ffd23f'
                        : pm25 <= 55
                          ? '#ff6b35'
                          : '#ff2d00';
                const label =
                  pm25 == null
                    ? '—'
                    : pm25 <= 12
                      ? 'Good'
                      : pm25 <= 35
                        ? 'Moderate'
                        : pm25 <= 55
                          ? 'Unhealthy'
                          : 'Hazardous';
                return (
                  <tr
                    key={i}
                    onClick={() =>
                      c.lat != null &&
                      c.lon != null &&
                      onFocus({
                        kind: 'airquality',
                        lon: c.lon,
                        lat: c.lat,
                        height: 350000,
                        title: `${c.city} air quality`,
                        lines: [
                          `PM2.5: ${pm25 ?? '—'} µg/m³`,
                          `PM10: ${c.pm10 ?? '—'} µg/m³`,
                          `Status: ${label}`,
                        ],
                      })
                    }
                  >
                    <td>{c.city}</td>
                    <td style={{ color }}>{pm25 ?? '—'} µg/m³</td>
                    <td>{c.pm10 ?? '—'} µg/m³</td>
                    <td style={{ color, fontWeight: 'bold' }}>{label}</td>
                    <td className="locate-cell">◎</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'gdacs' && (
        <section>
          <button onClick={loadGdacs} disabled={loading['gdacs']}>
            {loading['gdacs'] ? 'Loading…' : '↻ Refresh'}
          </button>
          <span className="data-count">{gdacs?.alerts?.length || 0} alerts</span>
          {!gdacs?.alerts?.length && <div className="health-status pending">No GDACS alerts</div>}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {(gdacs?.alerts || []).map((a: GDACSAlert, i: number) => {
              const t = (a.title || '').toLowerCase();
              const type = t.includes('earthquake')
                ? { label: 'EQ', color: '#ff6b35' }
                : t.includes('flood')
                  ? { label: 'FLD', color: '#22d3ee' }
                  : t.includes('cyclone') || t.includes('typhoon') || t.includes('hurricane')
                    ? { label: 'CY', color: '#ffd23f' }
                    : t.includes('tsunami')
                      ? { label: 'TSU', color: '#ff2d00' }
                      : t.includes('drought')
                        ? { label: 'DR', color: '#6f8c84' }
                        : t.includes('volcano')
                          ? { label: 'VOL', color: '#ff4d5e' }
                          : { label: 'ALR', color: '#ff6b35' };
              return (
                <div
                  key={i}
                  className="iss-card"
                  style={{ cursor: 'pointer', borderLeft: `3px solid ${type.color}` }}
                  onClick={() =>
                    a.lon != null &&
                    a.lat != null &&
                    onFocus({
                      kind: 'gdacs',
                      lon: a.lon,
                      lat: a.lat,
                      height: 400000,
                      title: a.title || 'Unknown',
                      lines: [a.description?.slice(0, 120) || ''],
                    })
                  }
                >
                  <span style={{ color: type.color, fontWeight: 'bold' }}>{type.label}</span>
                  <strong>{a.title}</strong>
                  <small style={{ color: '#6f8c84' }}>{a.published?.slice(0, 16) || ''}</small>
                  {a.link && (
                    <a className="tp-link" href={a.link} target="_blank" rel="noreferrer">
                      OPEN SOURCE ↗
                    </a>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      )}

      {tab === 'pegel' && (
        <section>
          <button onClick={loadPegel} disabled={loading['pegel']}>
            {loading['pegel'] ? 'Loading…' : '↻ Refresh'}
          </button>
          <span className="data-count">{pegel?.count ?? 0} gauges (DE)</span>
          {(pegel?.alerts ?? 0) > 0 && (
            <span className="data-count" style={{ color: '#ff6b35' }}>
              {pegel?.alerts} elevated
            </span>
          )}
          {pegel?.error && <div className="data-error">{pegel.error}</div>}
          {!pegel?.gauges?.length && !pegel?.error && (
            <div className="health-status pending">No gauge data</div>
          )}
          <div className="pegel-grid">
            {(pegel?.gauges || []).map((g: RiverGauge) => {
              const color =
                g.severity === 'critical'
                  ? '#ff2d00'
                  : g.severity === 'high'
                    ? '#ff6b35'
                    : g.severity === 'low'
                      ? '#88aaff'
                      : '#4fc3f7';
              return (
                <div
                  key={g.uuid}
                  className="pegel-card"
                  style={{ borderLeft: `3px solid ${color}` }}
                >
                  <div className="pegel-card-head">
                    <div>
                      <strong>{g.name}</strong>
                      <span className="pegel-water">{g.water}</span>
                    </div>
                    <button
                      className="locate-mini"
                      onClick={() =>
                        onFocus({
                          kind: 'pegel',
                          lon: g.lon,
                          lat: g.lat,
                          height: 350000,
                          title: `${g.name} (${g.water})`,
                          lines: [
                            `${g.value} ${g.unit}`,
                            `${g.state_mnw_mhw || '—'} / ${g.state_nsw_hsw || '—'}`,
                            g.timestamp || '',
                          ],
                        })
                      }
                    >
                      ◎
                    </button>
                  </div>
                  <div className="pegel-now" style={{ color }}>
                    {g.value} <span className="pegel-unit">{g.unit}</span>
                    <span className="pegel-sev" style={{ color }}>
                      {g.severity}
                    </span>
                  </div>
                  <PegelSparkline uuid={g.uuid} hours={24} width={240} height={48} color={color} />
                </div>
              );
            })}
          </div>
          <div style={{ marginTop: 8, fontSize: 11, color: '#6f8c84' }}>
            Source: Pegelonline (WSV) · sparklines /api/pegel/{'{uuid}'}/history
          </div>
        </section>
      )}

      {tab === 'weather' && (
        <WeatherSection
          onFocus={onFocus}
          onOpenWindyMap={(lat, lon) => onOpenWindyMap?.(lat, lon)}
        />
      )}

      {tab === 'wildfires' && <WildfiresPanel onFocus={onFocus} />}

      {tab === 'energy' && (
        <section>
          <button onClick={loadEnergy} disabled={loading['energy']}>
            {loading['energy'] ? 'Loading…' : '↻ Refresh'}
          </button>
          {!energy && <div className="health-status pending">No energy data</div>}
          {energy && (
            <>
              <div className="iss-card">
                <strong>Germany — Live Generation</strong>
                <div>Total: {energy.total_generation_mw?.toLocaleString()} MW</div>
                <div>CO₂: {energy.co2_g_per_kwh} g/kWh</div>
                <div>Load: {energy.load?.latest_mw?.toLocaleString()} MW</div>
                <div>Price: {energy.day_ahead_price?.latest_eur_mwh} EUR/MWh</div>
              </div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>MW</th>
                    <th>Share</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(energy.generation || {}).map(
                    ([key, val]: [string, { latest_mw?: number }]) => {
                      const mw = val.latest_mw ?? 0;
                      const share = energy.total_generation_mw
                        ? ((mw / energy.total_generation_mw) * 100).toFixed(1)
                        : '—';
                      const color = [
                        'solar',
                        'wind_onshore',
                        'wind_offshore',
                        'hydro',
                        'biomass',
                      ].includes(key)
                        ? '#00e5a0'
                        : ['natural_gas'].includes(key)
                          ? '#ffd23f'
                          : '#ff6b35';
                      return (
                        <tr key={key}>
                          <td style={{ textTransform: 'capitalize', color }}>
                            {key.replace(/_/g, ' ')}
                          </td>
                          <td>{val.latest_mw?.toLocaleString()}</td>
                          <td>{share}%</td>
                        </tr>
                      );
                    },
                  )}
                </tbody>
              </table>
            </>
          )}
        </section>
      )}

      {tab === 'stocks' && (
        <section>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <button onClick={loadStocks} disabled={loading['stocks']}>
              {loading['stocks'] ? 'Loading…' : '↻ Refresh'}
            </button>
            <span className="data-count">{stocks?.count ?? 0} assets · MARKETS OVERVIEW</span>
          </div>
          {stocks?.error && <div className="data-error">{stocks.error}</div>}

          {/* Risk header */}
          {stocks?.risk && (
            <div className="market-head">
              <div className="market-stat" style={{ borderColor: riskColor(stocks.risk.level) }}>
                <span className="mh-label">MARKET STRESS</span>
                <strong style={{ color: riskColor(stocks.risk.level) }}>{stocks.risk.level}</strong>
                <small style={{ color: '#6f8c84' }}>score {stocks.risk.score}/100</small>
              </div>
              <div className="market-stat" style={{ borderColor: riskColor(stocks.risk.level) }}>
                <span className="mh-label">VIX · FEAR</span>
                <strong style={{ color: riskColor(stocks.risk.level), fontSize: 28 }}>
                  {fmtNum(stocks.risk.vix, 2)}
                </strong>
                <small style={{ color: '#6f8c84' }}>volatility index</small>
              </div>
              <div className="market-stat">
                <span className="mh-label">INDEX BREADTH</span>
                <strong>
                  <span style={{ color: '#00e5a0' }}>{stocks.risk.advancers}↑</span> /{' '}
                  <span style={{ color: '#ff4d5e' }}>{stocks.risk.decliners}↓</span>
                </strong>
                <small style={{ color: pctColor(stocks.risk.avg_change) }}>
                  avg {fmtPct(stocks.risk.avg_change)}
                </small>
              </div>
              <div className="market-stat" style={{ minWidth: 200, alignItems: 'flex-start' }}>
                <span className="mh-label">SIGNALS</span>
                <small style={{ color: '#9fc4b8', lineHeight: 1.5 }}>
                  {(stocks.risk.notes || []).join(' · ')}
                </small>
              </div>
            </div>
          )}

          {/* Sections: indices, commodities, rates & FX */}
          {[
            { title: 'INDICES', items: stocks?.indices },
            { title: 'COMMODITIES', items: stocks?.commodities },
            { title: 'RATES & FX', items: stocks?.rates_fx },
          ].map((grp) =>
            grp.items?.length ? (
              <div className="market-section" key={grp.title}>
                <h4>{grp.title}</h4>
                <div className="market-cards">
                  {grp.items.map((q: MarketQuote) => (
                    <div className="market-card" key={q.symbol}>
                      <div className="mc-top">
                        <div>
                          <strong className="mc-sym">{q.label}</strong>
                          <span className="mc-name">{q.name}</span>
                        </div>
                        <span className="mc-rank" style={{ color: pctColor(q.trend_pct) }}>
                          {fmtPct(q.trend_pct, 1)} 30d
                        </span>
                      </div>
                      <div className="mc-price">
                        {fmtPrice(q.price)}{' '}
                        <small style={{ fontSize: 11, color: '#6f8c84' }}>{q.currency || ''}</small>
                      </div>
                      <div className="mc-chips">
                        <span style={{ color: pctColor(q.change_pct) }}>
                          {fmtPct(q.change_pct)} 24h
                        </span>
                      </div>
                      <Sparkline data={q.spark || []} width={150} height={40} />
                    </div>
                  ))}
                </div>
              </div>
            ) : null,
          )}

          {!stocks?.count && !stocks?.error ? (
            <div className="health-status pending">No market data</div>
          ) : null}
          <div style={{ marginTop: 10, fontSize: 11, color: '#6f8c84' }}>
            Source: {stocks?.source ?? 'yahoo-finance'} · Updated: {stocks?.updated ?? '—'}
          </div>

          {markets?.risk != null && (
            <>
              <h4 style={{ letterSpacing: 2, fontSize: 12, color: '#8fb7a9', marginTop: 20 }}>
                CRYPTO
              </h4>
              <div className="market-head">
                <div
                  className="market-gauge"
                  style={{ borderColor: fngColor(markets.fear_greed?.value) }}
                >
                  <span className="mh-label">FEAR &amp; GREED</span>
                  <strong style={{ color: fngColor(markets.fear_greed?.value), fontSize: 30 }}>
                    {markets.fear_greed?.value ?? '—'}
                  </strong>
                  <small style={{ color: fngColor(markets.fear_greed?.value) }}>
                    {markets.fear_greed?.label ?? 'n/a'}
                  </small>
                </div>
                <div className="market-stat">
                  <span className="mh-label">TOTAL CAP</span>
                  <strong>${fmtCompact(markets.global?.total_market_cap_usd)}</strong>
                  <small style={{ color: pctColor(markets.global?.market_cap_change_24h) }}>
                    {fmtPct(markets.global?.market_cap_change_24h)} 24h
                  </small>
                </div>
              </div>
              {markets?.coins?.length ? (
                <div className="market-cards">
                  {markets.coins.map((c: MarketCoin) => (
                    <div className="market-card" key={c.id}>
                      <div className="mc-top">
                        <div>
                          <strong className="mc-sym">{c.symbol}</strong>
                          <span className="mc-name">{c.name}</span>
                        </div>
                        <span className="mc-rank">#{c.market_cap_rank ?? '—'}</span>
                      </div>
                      <div className="mc-price">${fmtPrice(c.price)}</div>
                      <div className="mc-chips">
                        <span style={{ color: pctColor(c.change_24h) }}>
                          24h {fmtPct(c.change_24h)}
                        </span>
                        <span style={{ color: pctColor(c.change_7d) }}>
                          7d {fmtPct(c.change_7d)}
                        </span>
                      </div>
                      <Sparkline data={c.spark || []} width={150} height={40} />
                    </div>
                  ))}
                </div>
              ) : null}
              <div style={{ marginTop: 8, fontSize: 11, color: '#6f8c84' }}>
                Crypto: {markets?.source ?? 'coingecko'}
              </div>
            </>
          )}
        </section>
      )}

      {tab === 'maritime' && (
        <section>
          <button onClick={loadMaritime} disabled={loading['maritime']}>
            {loading['maritime'] ? 'Loading…' : '↻ Refresh'}
          </button>
          {maritime?.stream_connected != null && (
            <div className="health-status pending" style={{ marginTop: 8 }}>
              AISstream {maritime.stream_connected ? 'connected' : 'disconnected'}
              {maritime.stream_buffer != null ? ` · buffer ${maritime.stream_buffer}` : ''}
            </div>
          )}
          {(maritime?.errors?.length ?? 0) > 0 && (
            <div className="data-error">{maritime!.errors!.join(' · ')}</div>
          )}
          {maritime?.error && <div className="data-error">{maritime.error}</div>}
          <span className="data-count">{maritime?.count ?? 0} vessels</span>
          {!maritime?.vessels?.length && (
            <div className="health-status pending">No live vessel data</div>
          )}
          <table className="data-table clickable">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Lat</th>
                <th>Lon</th>
                <th>Course</th>
                <th>Speed</th>
                <th>Destination</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {(maritime?.vessels || []).slice(0, 100).map((v: MaritimeVessel, i: number) => (
                <tr
                  key={i}
                  onClick={() =>
                    v.lon != null &&
                    v.lat != null &&
                    onFocus({
                      kind: 'maritime',
                      lon: v.lon,
                      lat: v.lat,
                      height: 200000,
                      title: v.name || 'Vessel',
                      lines: [
                        `MMSI: ${v.mmsi || '—'}`,
                        `Type: ${v.type || '—'}`,
                        `Course: ${v.course ?? '—'}°`,
                        `Speed: ${v.speed != null ? v.speed + ' kn' : '—'}`,
                        `Destination: ${v.destination || '—'}`,
                        `Flag: ${v.flag || '—'}`,
                        `Length: ${v.length != null ? v.length + ' m' : '—'}`,
                      ],
                    })
                  }
                >
                  <td>
                    <strong>{v.name || '—'}</strong>
                  </td>
                  <td>{v.type || '—'}</td>
                  <td>{v.lat?.toFixed(4) ?? '—'}</td>
                  <td>{v.lon?.toFixed(4) ?? '—'}</td>
                  <td>{v.course != null ? v.course + '°' : '—'}</td>
                  <td>{v.speed != null ? v.speed + ' kn' : '—'}</td>
                  <td>{v.destination || '—'}</td>
                  <td className="locate-cell">◎ LOCATE</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'eu-energy' && (
        <section>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
            <select
              className="poi-select"
              value={euCountry}
              onChange={(e) => setEuCountry(e.target.value)}
            >
              <option value="de">Germany</option>
              <option value="fr">France</option>
              <option value="nl">Netherlands</option>
              <option value="at">Austria</option>
              <option value="pl">Poland</option>
              <option value="es">Spain</option>
              <option value="it">Italy</option>
              <option value="se">Sweden</option>
              <option value="dk">Denmark</option>
              <option value="no">Norway</option>
              <option value="be">Belgium</option>
              <option value="ch">Switzerland</option>
              <option value="cz">Czechia</option>
              <option value="fi">Finland</option>
            </select>
            <button onClick={loadEuEnergy} disabled={loading['eu-energy']}>
              {loading['eu-energy'] ? 'Loading…' : '↻ Refresh'}
            </button>
          </div>
          {euEnergy?.demo_mode && (
            <div className="health-status pending">
              ⚠ DEMO MODE — set ENTSOE_SECURITY_TOKEN for live data
            </div>
          )}
          {euEnergy?.error && !euEnergy.demo_mode && (
            <div className="data-error">{euEnergy.error}</div>
          )}
          {euEnergy?.prices && (
            <>
              <div className="iss-card" style={{ marginBottom: 8 }}>
                <strong>{euCountry.toUpperCase()} — Day Ahead Prices (EUR/MWh)</strong>
                <div style={{ marginTop: 4, fontSize: 12, color: '#6f8c84' }}>
                  {euEnergy.prices.length} hourly slots
                </div>
              </div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Hour</th>
                    <th>Price</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {euEnergy.prices.slice(0, 24).map((p: EuPriceSlot, i: number) => {
                    const price = p.price_eur_mwh ?? 0;
                    const color =
                      price < 0
                        ? '#22d3ee'
                        : price < 50
                          ? '#00e5a0'
                          : price < 100
                            ? '#ffd23f'
                            : price < 200
                              ? '#ff6b35'
                              : '#ff2d00';
                    const label =
                      price < 0
                        ? 'NEGATIVE'
                        : price < 50
                          ? 'Low'
                          : price < 100
                            ? 'Normal'
                            : price < 200
                              ? 'High'
                              : 'Extreme';
                    return (
                      <tr key={i}>
                        <td>{p.position}</td>
                        <td style={{ color, fontWeight: 'bold' }}>{price.toFixed(2)}</td>
                        <td style={{ color }}>{label}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </>
          )}
          {euEnergy?.generation_by_source && (
            <div style={{ marginTop: 12 }}>
              <div className="iss-card">
                <strong>Generation Mix — Latest Hour</strong>
              </div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th>MW</th>
                    <th>Share</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(euEnergy.generation_by_source).map(
                    ([key, val]: [string, number]) => {
                      const share = euEnergy.total_mw
                        ? ((val / euEnergy.total_mw) * 100).toFixed(1)
                        : '—';
                      const color = [
                        'Solar',
                        'Wind Offshore',
                        'Wind Onshore',
                        'Hydro Run-of-river',
                        'Hydro Water Reservoir',
                        'Biomass',
                        'Geothermal',
                      ].includes(key)
                        ? '#00e5a0'
                        : ['Nuclear'].includes(key)
                          ? '#ffd23f'
                          : '#ff6b35';
                      return (
                        <tr key={key}>
                          <td style={{ color }}>{key}</td>
                          <td>{val.toLocaleString()}</td>
                          <td>{share}%</td>
                        </tr>
                      );
                    },
                  )}
                </tbody>
              </table>
            </div>
          )}
          {!euEnergy?.prices?.length && !euEnergy?.error && (
            <div className="health-status pending">No EU energy data</div>
          )}
        </section>
      )}

      {tab === 'cve' && (
        <section>
          <button onClick={loadCve} disabled={loading['cve']}>
            {loading['cve'] ? 'Loading…' : '↻ Refresh'}
          </button>
          <span className="data-count">{cve?.count ?? 0} CISA KEV entries</span>
          {cve?.error && <div className="data-error">{cve.error}</div>}
          {!cve?.vulnerabilities?.length && !cve?.error && (
            <div className="health-status pending">No CVE data</div>
          )}
          <table className="data-table">
            <thead>
              <tr>
                <th>CVE</th>
                <th>Vendor</th>
                <th>Product</th>
                <th>Added</th>
                <th>Ransomware</th>
              </tr>
            </thead>
            <tbody>
              {(cve?.vulnerabilities || []).map((v: CveEntry, i: number) => (
                <tr key={i}>
                  <td>
                    <strong>{v.cve_id}</strong>
                  </td>
                  <td>{v.vendor || '—'}</td>
                  <td>{v.product || '—'}</td>
                  <td>{v.date_added || '—'}</td>
                  <td style={{ color: v.ransomware === 'Known' ? '#ff2d00' : '#6f8c84' }}>
                    {v.ransomware || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {cve?.date_released && (
            <div style={{ marginTop: 8, fontSize: 11, color: '#6f8c84' }}>
              Catalog: {cve.date_released}
            </div>
          )}
        </section>
      )}

      {tab === 'webcams' && (
        <WebcamSection
          webcams={webcams}
          webcamCategory={webcamCategory}
          setWebcamCategory={setWebcamCategory}
          onLoad={loadWebcams}
          loading={loading['webcams']}
          onFocus={onFocus}
        />
      )}

      {tab === 'satellite' && <SatellitePanel onFocus={onFocus} />}

      {tab === 'stac' && <StacPanel onFocus={onFocus} />}

      {tab === 'sanctions' && <SanctionsPanel onFocus={onFocus} />}

      {tab === 'intel' && (
        <ErrorBoundary name="IntelGraph">
          <IntelGraphPanel onFocus={onFocus} initialEntityId={intelEntityId} />
        </ErrorBoundary>
      )}

      {tab === 'relationships' && (
        <ErrorBoundary name="RelationshipExplorer">
          <RelationshipExplorer initialEntityId={intelEntityId} />
        </ErrorBoundary>
      )}

      {tab === 'credentials' && (
        <ErrorBoundary name="CredentialManager">
          <CredentialManagerPanel />
        </ErrorBoundary>
      )}

      {tab === 'darkweb' && <DarkwebPanel />}
      {tab === 'cii' && <CiiPanel />}
      {tab === 'telegram' && <TelegramPanel />}
      {tab === 'flags' && <FeatureFlagsPanel />}
    </div>
  );
}
