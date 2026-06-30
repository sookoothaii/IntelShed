import { useState, useEffect, useRef, type ReactNode } from 'react';
import { useQueries, useQueryClient } from '@tanstack/react-query';
import { fetchApi } from '../lib/networkFetch';
import type { FocusTarget } from '../lib/focus';
import { useHudSessionState } from '../lib/hudSessionState';
import { useBriefingQuery } from '../hooks/useSharedFeeds';
import type { AgenticTrace } from '../lib/agentic';
import TrustGauge from './TrustGauge';
import { ProvenanceGlobalStats } from './ProvenanceChain';

type BriefLang = 'en' | 'de';
type AnalysisTab = 'operator' | 'alerts' | 'feeds';

const ANALYSIS_TABS: AnalysisTab[] = ['operator', 'alerts', 'feeds'];
const ANALYSIS_FETCH_TIMEOUT_MS = 15_000;

// ---------- API response types ----------

interface FeedHealthEntry {
  status?: string;
  fresh?: boolean;
  age_sec?: number;
}

interface HealthResponse {
  feeds?: Record<string, FeedHealthEntry>;
}

interface SituationEntry {
  severity?: string;
  title?: string;
  type?: string;
  location?: { lon?: number; lat?: number };
}

interface CorrelationsResponse {
  situations?: SituationEntry[];
}

interface DigestMeta {
  region_label?: string;
  window?: string;
  local_count?: number;
  regional_count?: number;
  global_count?: number;
}

interface BriefingQualityMeta {
  gdelt_collected?: number;
  gdelt_digest_lines?: number;
  gdelt_pipeline_blocker?: string;
  gdelt_pipeline_placed_ok?: boolean;
  pipeline_blocker?: string;
  pipeline_placed_ok?: boolean;
  watch_count?: number;
  corroboration_avg_local?: number;
  corroboration_blocker?: string;
  prediction_accuracy_30d?: number;
  prediction_pending?: number;
  prediction_sample_30d?: number;
}

interface BriefingQuality {
  score?: number;
  meta?: BriefingQualityMeta;
}

interface WatchItem {
  id?: string;
  horizon_h?: number;
  title?: string;
  confidence?: number;
  sources?: string[];
  delta_score?: number;
  lat?: number;
  lon?: number;
  bucket?: string;
}

interface IntelEntity {
  id?: string;
  caption?: string;
  schema?: string;
  bucket?: string;
  lat?: number;
  lon?: number;
  datasets?: string[];
}

interface IntelBlock {
  count?: number;
  entities?: IntelEntity[];
  by_bucket?: { local?: number; regional?: number; global?: number };
}

interface FusionHotspot {
  label?: string;
  summary?: string;
  lat?: number;
  lon?: number;
  score?: number;
}

interface DigestLineMeta {
  label?: string;
  text?: string;
  observed_at?: string;
  corroboration?: number;
  sources?: string[];
}

interface BriefingResponse {
  text?: string;
  digest?: DigestMeta;
  quality?: BriefingQuality;
  watch_items?: WatchItem[];
  fusion_hotspots?: FusionHotspot[];
  intel?: IntelBlock;
  digest_line_meta?: DigestLineMeta[];
  created_at?: string;
  agentic?: unknown;
}

interface TrustProbe {
  name?: string;
  ok?: boolean;
  detail?: string;
}

interface FeedDriftEntry {
  cache_key?: string;
  previous_count?: number;
  current_count?: number;
  drop_pct?: number;
}

interface FreshnessEntry {
  cache_key?: string;
  connector_name?: string;
  connector_id?: string;
  source?: string | string[];
  license?: string;
  bridge?: string;
  endpoint?: string;
  status?: string;
  count?: number;
  age_sec?: number;
  error?: string;
}

interface FeedDrift {
  ok?: boolean;
  detail?: string;
  degradation?: unknown;
  offline_pct?: number;
  warn?: boolean;
  offline_keys?: string[];
  drifting?: FeedDriftEntry[];
  freshness?: FreshnessEntry[];
}

interface TrustResponse {
  score?: number;
  max_score?: number;
  degraded?: boolean;
  field_warn?: boolean;
  feed_warn?: boolean;
  probes?: TrustProbe[];
  feed_drift?: FeedDrift;
  briefing_pipeline?: BriefingQualityMeta;
  failed_probes?: string[];
}

interface PredictionEntry {
  id?: string;
  watch_id?: string;
  overdue?: boolean;
  due_at?: string;
  claim?: string;
  prefix?: string;
  horizon_h?: number;
  hit?: boolean;
  outcome?: string;
}

interface PredictionStats {
  pending?: number;
  sample_size?: number;
  accuracy?: number;
}

interface PredictionsResponse {
  enabled?: boolean;
  pending?: PredictionEntry[];
  resolved_recent?: PredictionEntry[];
  stats?: PredictionStats;
  overdue_count?: number;
  due_next?: string;
}

interface CveVulnerability {
  cve_id?: string;
  vendor?: string;
  product?: string;
  due_date?: string;
  ransomware?: string;
}

interface CveResponse {
  vulnerabilities?: CveVulnerability[];
}

interface QuakeEntry {
  mag?: number;
  place?: string;
  depth?: number;
  lon?: number;
  lat?: number;
  time?: string;
  tsunami?: boolean;
}

interface EarthquakesResponse {
  earthquakes?: QuakeEntry[];
}

interface EventEntry {
  category?: string;
  title?: string;
  date?: string;
  lon?: number;
  lat?: number;
  magnitude?: number;
}

interface EventsResponse {
  events?: EventEntry[];
}

interface MilitaryAircraft {
  flight?: string;
  hex?: string;
  type?: string;
  alt?: number;
  speed?: number;
  squawk?: string;
  lon?: number;
  lat?: number;
}

interface MilitaryResponse {
  count?: number;
  aircraft?: MilitaryAircraft[];
}

interface GdacsAlert {
  title?: string;
  published?: string;
  lat?: number;
  lon?: number;
  description?: string;
}

interface GdacsResponse {
  alerts?: GdacsAlert[];
}

interface AnomalyEntry {
  callsign?: string;
  icao24?: string;
  reasons?: string[];
  lon?: number;
  lat?: number;
}

interface AnomaliesResponse {
  count?: number;
  anomalies?: AnomalyEntry[];
}

interface AirQualityCity {
  city?: string;
  pm25?: number;
  pm10?: number;
}

interface AirQualityResponse {
  cities?: AirQualityCity[];
}

interface PegelGauge {
  name?: string;
  water?: string;
  value?: number;
  unit?: string;
  severity?: string;
  lon?: number;
  lat?: number;
  state_mnw_mhw?: string;
  state_nsw_hsw?: string;
}

interface PegelResponse {
  gauges?: PegelGauge[];
}

interface NodeHealth {
  disk_pct?: number;
  cpu_temp_c?: number;
  load_1m?: number;
  ram_pct?: number;
}

interface NodeEntry {
  name?: string;
  node_id?: string;
  online?: boolean;
  age_seconds?: number;
  lat?: number;
  lon?: number;
  health?: NodeHealth;
}

interface NodesResponse {
  count?: number;
  nodes?: NodeEntry[];
}

interface CryptoEntry {
  usd?: number;
  price?: number;
  usd_24h_change?: number;
  change_24h?: number;
}

interface SpaceWeatherResponse {
  kp_index?: number;
  scale?: string;
  aurora_visible_midlat?: boolean;
  hf_radio_impact?: boolean;
  history?: unknown[];
}

interface StatementStatsResponse {
  total_statements?: number;
  by_dataset?: Record<string, number>;
  by_prop?: Record<string, number>;
}

interface AnalysisResults {
  health?: HealthResponse;
  correlations?: CorrelationsResponse;
  briefing?: BriefingResponse;
  trust?: TrustResponse;
  predictions?: PredictionsResponse;
  cve?: CveResponse;
  earthquakes?: EarthquakesResponse;
  events?: EventsResponse;
  military?: MilitaryResponse;
  gdacs?: GdacsResponse;
  anomalies?: AnomaliesResponse;
  airquality?: AirQualityResponse;
  pegel?: PegelResponse;
  nodes?: NodesResponse;
  markets?: { crypto?: Record<string, CryptoEntry> };
  spaceweather?: SpaceWeatherResponse;
  statements?: StatementStatsResponse;
}

const ANALYSIS_ENDPOINTS: { key: string; url: string }[] = [
  { key: 'health', url: '/api/health' },
  { key: 'nodes', url: '/api/nodes' },
  { key: 'spaceweather', url: '/api/spaceweather' },
  { key: 'earthquakes', url: '/api/earthquakes?period=day&magnitude=2.5' },
  { key: 'events', url: '/api/events?limit=80' },
  { key: 'military', url: '/api/military' },
  { key: 'geopolitics', url: '/api/geopolitics?limit=20' },
  { key: 'markets', url: '/api/markets' },
  { key: 'correlations', url: '/api/correlations' },
  { key: 'anomalies', url: '/api/anomalies' },
  { key: 'airquality', url: '/api/airquality' },
  { key: 'gdacs', url: '/api/gdacs' },
  { key: 'predictions', url: '/api/predictions' },
  { key: 'trust', url: '/api/trust' },
  { key: 'cve', url: '/api/cve?limit=15' },
  { key: 'pegel', url: '/api/pegel' },
  { key: 'statements', url: '/api/intel/statements/stats' },
];

function isBool(v: unknown): v is boolean {
  return typeof v === 'boolean';
}

async function fetchAnalysisEndpoint(url: string): Promise<Response> {
  const ctrl = new AbortController();
  const timer = window.setTimeout(() => ctrl.abort(), ANALYSIS_FETCH_TIMEOUT_MS);
  try {
    return await fetchApi(url, { signal: ctrl.signal });
  } finally {
    window.clearTimeout(timer);
  }
}

function isAnalysisTab(v: unknown): v is AnalysisTab {
  return typeof v === 'string' && (ANALYSIS_TABS as readonly string[]).includes(v as AnalysisTab);
}

function fmtFeedAge(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec)) return '—';
  if (sec < 60) return `${Math.round(sec)}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  return `${(sec / 3600).toFixed(1)}h`;
}

function feedHealthStyle(v: { status?: string; fresh?: boolean; age_sec?: number }) {
  const st = v.status || (v.fresh ? 'fresh' : 'stale');
  if (st === 'fresh') return { border: '#00e5a0', color: '#00e5a0', label: 'FRESH' };
  if (st === 'warn') return { border: '#ffd23f', color: '#ffd23f', label: 'WARN' };
  if (st === 'stale') return { border: '#ff6b35', color: '#ff6b35', label: 'STALE' };
  return { border: '#6f8c84', color: '#6f8c84', label: '—' };
}

function AnalysisCollapsible({
  title,
  count,
  defaultOpen = true,
  children,
}: {
  title: string;
  count?: number;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`analysis-section analysis-collapsible${open ? '' : ' is-closed'}`}>
      <button type="button" className="analysis-section-toggle" onClick={() => setOpen((v) => !v)}>
        <span>
          {title}
          {count != null ? ` (${count})` : ''}
        </span>
        <span className="analysis-section-chevron" aria-hidden>
          {open ? '▾' : '▸'}
        </span>
      </button>
      {open ? <div className="analysis-collapsible-body">{children}</div> : null}
    </div>
  );
}

function AgenticLoopPanel({ agentic }: { agentic: AgenticTrace }) {
  if (agentic.enabled === false) {
    return (
      <div className="analysis-section analysis-agentic">
        <h3>⟳ AGENTIC LOOP</h3>
        <div className="analysis-row" style={{ fontSize: 11, color: '#6f8c84' }}>
          Disabled — set BRIEFING_AGENTIC_LOOP=1 to enable coverage → retrieve → corroboration.
        </div>
      </div>
    );
  }
  const rounds = agentic.rounds ?? 0;
  const maxR = agentic.max_rounds ?? 3;
  const final = agentic.final_counts || {};
  return (
    <div className="analysis-section analysis-agentic">
      <h3>
        ⟳ AGENTIC LOOP{' '}
        <span className="analysis-agentic-rounds">
          {rounds}/{maxR}
        </span>
      </h3>
      {(agentic.phases || []).map((phase, i) => {
        const name = String(phase.phase || 'phase');
        if (name === 'coverage') {
          const counts = (phase.counts || {}) as Record<string, number>;
          const gaps = Array.isArray(phase.gaps) ? phase.gaps : [];
          return (
            <div key={i} className="analysis-agentic-phase">
              <span className="analysis-agentic-phase-label">COVERAGE</span>
              <span>
                L{counts.local ?? '—'} · R{counts.regional ?? '—'} · G{counts.global ?? '—'}
              </span>
              {gaps.length > 0 ? (
                <span className="analysis-agentic-warn">gaps: {gaps.join(', ')}</span>
              ) : (
                <span className="analysis-agentic-ok">OK</span>
              )}
            </div>
          );
        }
        if (name === 'retrieve') {
          const perBucket = (phase.per_bucket || {}) as Record<string, number>;
          const retrieved = Number(phase.retrieved ?? 0);
          const errors = Array.isArray(phase.errors) ? phase.errors : [];
          return (
            <div key={i} className="analysis-agentic-phase">
              <span className="analysis-agentic-phase-label">RETRIEVE</span>
              <span>{retrieved} line(s)</span>
              {Object.keys(perBucket).length > 0 && (
                <span style={{ color: '#8fb7a9' }}>
                  {Object.entries(perBucket)
                    .map(([b, n]) => `${b}:${n}`)
                    .join(' · ')}
                </span>
              )}
              {errors.length > 0 && (
                <span className="analysis-agentic-warn" title={errors.join('; ')}>
                  {errors.length} error(s)
                </span>
              )}
            </div>
          );
        }
        if (name === 'corroboration') {
          const summary = (phase.corroboration || {}) as Record<string, unknown>;
          const avg = summary.corroboration_avg_local;
          const weak = Number(phase.weak_local_lines ?? 0);
          const ragN = Number(phase.rag_corroborated ?? 0);
          return (
            <div key={i} className="analysis-agentic-phase">
              <span className="analysis-agentic-phase-label">CORROBORATE</span>
              {avg != null && (
                <span
                  style={{
                    color:
                      Number(avg) >= 0.75 ? '#00e5a0' : Number(avg) >= 0.5 ? '#ffd23f' : '#ff6b35',
                  }}
                >
                  LOCAL {Math.round(Number(avg) * 100)}%
                </span>
              )}
              <span style={{ color: '#8fb7a9' }}>
                weak {weak} · RAG +{ragN}
              </span>
            </div>
          );
        }
        return null;
      })}
      {Object.keys(final).length > 0 && (
        <div className="analysis-agentic-final">
          FINAL L{final.local ?? '—'} · R{final.regional ?? '—'} · G{final.global ?? '—'}
          {agentic.status ? ` · ${String(agentic.status).toUpperCase()}` : ''}
        </div>
      )}
    </div>
  );
}

export default function FullAnalysisOverlay({
  onClose,
  onFocus,
}: {
  onClose: () => void;
  onFocus: (f: Omit<FocusTarget, 'ts'>) => void;
}) {
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [analysisTab, setAnalysisTab] = useHudSessionState<AnalysisTab>(
    'analysisTab',
    'operator',
    isAnalysisTab,
  );
  const [trustExpanded, setTrustExpanded] = useHudSessionState(
    'analysisTrustExpanded',
    false,
    isBool,
  );
  const [briefLang, setBriefLang] = useState<BriefLang>(() => {
    const saved = (typeof window !== 'undefined' &&
      window.localStorage?.getItem('worldbase_briefing_lang')) as BriefLang | null;
    return saved === 'de' || saved === 'en' ? saved : 'en';
  });
  const [briefBusy, setBriefBusy] = useState(false);
  const [briefError, setBriefError] = useState<string | null>(null);
  const queryClient = useQueryClient();
  const closeRef = useRef<HTMLButtonElement>(null);

  const queries = useQueries({
    queries: ANALYSIS_ENDPOINTS.map((ep) => ({
      queryKey: ['analysis', ep.key],
      queryFn: () =>
        fetchAnalysisEndpoint(ep.url).then(async (r) =>
          r.ok ? r.json() : { error: `HTTP ${r.status}` },
        ),
      staleTime: 30_000,
      refetchInterval: autoRefresh ? (30_000 as number) : (false as const),
    })),
  });
  const briefingQ = useBriefingQuery({ refetchInterval: autoRefresh ? 30_000 : 60_000 });

  const results: Partial<AnalysisResults> = {};
  ANALYSIS_ENDPOINTS.forEach((ep, i) => {
    const q = queries[i];
    if (q.data !== undefined) results[ep.key as keyof AnalysisResults] = q.data as never;
    else if (q.isError)
      results[ep.key as keyof AnalysisResults] = { error: 'unavailable' } as never;
  });
  results.briefing = (briefingQ.data ??
    (briefingQ.isError ? { error: 'unavailable' } : undefined)) as BriefingResponse | undefined;
  const loading = queries.some((q) => q.isLoading) || briefingQ.isLoading;

  const generateBriefing = async () => {
    setBriefBusy(true);
    setBriefError(null);
    try {
      const r = await fetchApi(`/api/briefing/generate?lang=${briefLang}`, { method: 'POST' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await r.json().catch(() => null);
      await queryClient.invalidateQueries({ queryKey: ['briefing'] });
      await queryClient.invalidateQueries({ queryKey: ['analysis'] });
    } catch (e: unknown) {
      setBriefError((e as Error)?.message || 'briefing failed');
    } finally {
      setBriefBusy(false);
    }
  };

  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage?.setItem('worldbase_briefing_lang', briefLang);
  }, [briefLang]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    closeRef.current?.focus();
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const health = results.health;
  const correlations = results.correlations;
  const briefing = results.briefing;
  const digest = briefing?.digest;
  const briefingQuality = briefing?.quality;
  const trust = results.trust;
  const predictions = results.predictions;
  const fusionHotspots = briefing?.fusion_hotspots || [];
  const agenticTrace = briefing?.agentic as AgenticTrace | undefined;
  const cveFeed = results.cve;
  const quakes = (results.earthquakes?.earthquakes || []).slice(0, 15);
  const wildfires = (results.events?.events || [])
    .filter(
      (e: EventEntry) =>
        (e.category || '').toLowerCase().includes('fire') ||
        (e.title || '').toLowerCase().includes('fire'),
    )
    .slice(0, 8);
  const allEvents = (results.events?.events || [])
    .filter(
      (e: EventEntry) =>
        !(
          (e.category || '').toLowerCase().includes('fire') ||
          (e.title || '').toLowerCase().includes('fire')
        ),
    )
    .slice(0, 10);
  const military = results.military;
  const gdacs = (results.gdacs?.alerts || []).slice(0, 15);
  const anomalies = results.anomalies;
  const air = results.airquality;
  const pegel = results.pegel;
  const nodes = results.nodes;

  const severityColor = (s: string) => {
    if (!s) return '#00e5a0';
    if (s === 'critical' || s === 'high') return '#ff2d00';
    if (s === 'warning' || s === 'medium') return '#ff6b35';
    return '#00e5a0';
  };
  const aqColor = (pm25: number | null | undefined) => {
    if (pm25 == null) return '#6f8c84';
    if (pm25 <= 12) return '#00e5a0';
    if (pm25 <= 35) return '#ffd23f';
    if (pm25 <= 55) return '#ff6b35';
    return '#ff2d00';
  };
  const formatPredDue = (iso: string | null | undefined, overdue?: boolean) => {
    if (!iso) return '—';
    if (overdue) return 'OVERDUE';
    try {
      const ms = new Date(iso).getTime() - Date.now();
      const h = Math.round(ms / 3600000);
      if (h <= 0) return 'due now';
      return `${h}h left`;
    } catch {
      return '—';
    }
  };
  const gdacsType = (title: string) => {
    const t = (title || '').toLowerCase();
    if (t.includes('earthquake')) return { label: 'EQ', color: '#ff6b35' };
    if (t.includes('flood')) return { label: 'FLD', color: '#22d3ee' };
    if (t.includes('cyclone') || t.includes('typhoon') || t.includes('hurricane'))
      return { label: 'CY', color: '#ffd23f' };
    if (t.includes('tsunami')) return { label: 'TSU', color: '#ff2d00' };
    if (t.includes('drought')) return { label: 'DR', color: '#6f8c84' };
    if (t.includes('volcano')) return { label: 'VOL', color: '#ff4d5e' };
    return { label: 'ALR', color: '#ff6b35' };
  };

  const alertCount =
    (correlations?.situations?.length || 0) +
    (briefing?.watch_items?.length || 0) +
    gdacs.length +
    ((anomalies?.count || 0) > 0 ? 1 : 0);
  const feedCount =
    (military?.count || 0) +
    quakes.length +
    allEvents.length +
    wildfires.length +
    (cveFeed?.vulnerabilities?.length ?? 0) +
    (air?.cities?.length ?? 0);

  const digestMeta = briefing?.digest_line_meta || [];
  const weakDigestCount = digestMeta.filter(
    (row: DigestLineMeta) =>
      row.label === 'single-source' ||
      row.label === 'contradictory' ||
      Number(row.corroboration ?? 1) < 0.5,
  ).length;
  const feedDegrade = trust?.feed_drift;
  const showDegradeBanner =
    analysisTab === 'operator' && (trust?.degraded || trust?.field_warn || trust?.feed_warn);
  const degradeCritical = (trust?.score ?? 4) < 2;

  const fieldTrustVal =
    trust?.score != null && trust?.max_score != null ? trust.score / trust.max_score : null;
  const briefingQualityVal = briefingQuality?.score ?? null;
  const distinctSources = new Set<string>();
  for (const row of digestMeta) {
    if (row.sources) for (const s of row.sources) distinctSources.add(s);
  }
  const sourceDiversityVal = digestMeta.length > 0 ? Math.min(distinctSources.size / 10, 1) : null;
  const corroborationVals = digestMeta
    .map((r) => Number(r.corroboration ?? 0))
    .filter((n) => !isNaN(n));
  const corroborationVal =
    corroborationVals.length > 0
      ? corroborationVals.reduce((a, b) => a + b, 0) / corroborationVals.length
      : null;
  const feedEntries = health?.feeds ? Object.values(health.feeds) : [];
  const feedHealthVal =
    feedEntries.length > 0 ? feedEntries.filter((f) => f.fresh).length / feedEntries.length : null;

  return (
    <div className="analysis-overlay" onClick={onClose}>
      <div
        className="analysis-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Full situation analysis"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="analysis-head">
          <h2>🌍 FULL SITUATION ANALYSIS</h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <label
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 11,
                color: '#6f8c84',
                cursor: 'pointer',
              }}
            >
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
              />
              AUTO-REFRESH 30s
            </label>
            <button ref={closeRef} onClick={onClose} aria-label="Close analysis">
              ✕
            </button>
          </div>
        </div>

        {loading ? (
          <div className="analysis-loading">
            <div className="analysis-spinner" />
            <p>Scanning all feeds…</p>
          </div>
        ) : (
          <>
            <div className="analysis-tabs" role="tablist" aria-label="Full situation views">
              <button
                type="button"
                role="tab"
                aria-selected={analysisTab === 'operator'}
                className={analysisTab === 'operator' ? 'on' : ''}
                onClick={() => setAnalysisTab('operator')}
              >
                OPERATOR
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={analysisTab === 'alerts'}
                className={analysisTab === 'alerts' ? 'on' : ''}
                onClick={() => setAnalysisTab('alerts')}
              >
                ALERTS{alertCount > 0 ? ` · ${alertCount}` : ''}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={analysisTab === 'feeds'}
                className={analysisTab === 'feeds' ? 'on' : ''}
                onClick={() => setAnalysisTab('feeds')}
              >
                FEEDS{feedCount > 0 ? ` · ${feedCount}` : ''}
              </button>
            </div>
            {analysisTab === 'operator' && (trust || briefingQuality) && (
              <div className="trust-gauge-row">
                <TrustGauge value={fieldTrustVal} label="Field Trust" />
                <TrustGauge value={briefingQualityVal} label="Quality" />
                <TrustGauge value={sourceDiversityVal} label="Sources" />
                <TrustGauge value={corroborationVal} label="Corroboration" />
                <TrustGauge value={feedHealthVal} label="Feed Health" />
              </div>
            )}
            {showDegradeBanner && (
              <div
                className={`analysis-degrade-banner${degradeCritical ? ' analysis-degrade-banner--critical' : ''}`}
                role="status"
              >
                <strong>{degradeCritical ? 'FIELD TRUST LOW' : 'DEGRADED MODE'}</strong>
                {' — '}
                {(trust?.failed_probes || []).length > 0 && (
                  <span>probes down: {(trust.failed_probes as string[]).join(', ')}. </span>
                )}
                {feedDegrade?.warn && (
                  <span>
                    {feedDegrade.offline_pct}% watch feeds offline/stale
                    {(feedDegrade.offline_keys?.length ?? 0) > 0
                      ? ` (${(feedDegrade.offline_keys as string[]).slice(0, 4).join(', ')})`
                      : ''}
                    .{' '}
                  </span>
                )}
                Briefing may be incomplete — expand TRUST DETAIL for provenance.
              </div>
            )}
            {analysisTab === 'feeds' && (
              <div className="analysis-summary-strip analysis-summary-strip--feeds">
                <span>MILITARY {military?.count ?? 0}</span>
                <span>SEISMIC {quakes.length}</span>
                <span>EVENTS {allEvents.length + wildfires.length}</span>
                <span>CVE {cveFeed?.vulnerabilities?.length ?? 0}</span>
                <span style={{ color: '#6f8c84' }}>
                  Expand sections below — all collapsed by default
                </span>
              </div>
            )}
            <div className="analysis-body analysis-body--tabbed">
              {analysisTab === 'operator' && (trust || briefingQuality) && (
                <div
                  className="analysis-section"
                  style={{
                    marginBottom: 12,
                    borderLeft: `4px solid ${(trust?.score ?? 0) >= 3 ? '#00e5a0' : (trust?.score ?? 0) >= 2 ? '#ffd23f' : '#ff6b35'}`,
                  }}
                >
                  <h3>TRUST</h3>
                  <div className="analysis-row" style={{ alignItems: 'center' }}>
                    <div className="trust-gauge-row" style={{ padding: 0 }}>
                      <TrustGauge value={fieldTrustVal} label="Field Trust" size={64} />
                      <TrustGauge value={briefingQualityVal} label="Quality" size={64} />
                      <TrustGauge value={sourceDiversityVal} label="Sources" size={64} />
                      <TrustGauge value={corroborationVal} label="Corroboration" size={64} />
                      <TrustGauge value={feedHealthVal} label="Feed Health" size={64} />
                    </div>
                    <button
                      type="button"
                      className="analysis-trust-toggle"
                      onClick={() => setTrustExpanded((v) => !v)}
                    >
                      {trustExpanded ? 'LESS' : 'DETAIL'}
                    </button>
                  </div>
                  {trustExpanded &&
                    trust?.probes?.map((p: TrustProbe) => (
                      <div key={p.name} className="analysis-row" style={{ fontSize: 11 }}>
                        <span style={{ color: p.ok ? '#00e5a0' : '#ff6b35', fontWeight: 'bold' }}>
                          {p.ok ? 'OK' : 'FAIL'}
                        </span>
                        <span>
                          {p.name}: {p.detail}
                        </span>
                      </div>
                    ))}
                  {trustExpanded && trust?.feed_drift && (
                    <div className="analysis-row" style={{ fontSize: 11, marginTop: 6 }}>
                      <span
                        style={{
                          color: trust.feed_drift.ok ? '#00e5a0' : '#ffd23f',
                          fontWeight: 'bold',
                        }}
                      >
                        {trust.feed_drift.ok ? 'OK' : 'DRIFT'}
                      </span>
                      <span>feeds: {trust.feed_drift.detail}</span>
                    </div>
                  )}
                  {trustExpanded &&
                    trust?.feed_drift?.drifting &&
                    trust.feed_drift.drifting.length > 0 &&
                    trust.feed_drift.drifting.map((d: FeedDriftEntry) => (
                      <div
                        key={d.cache_key}
                        className="analysis-row"
                        style={{ fontSize: 10, color: '#ffd23f' }}
                      >
                        <span style={{ fontWeight: 'bold' }}>{d.cache_key}</span>
                        <span>
                          {d.previous_count} → {d.current_count} (−{d.drop_pct}%)
                        </span>
                      </div>
                    ))}
                  {trustExpanded &&
                    trust?.feed_drift?.freshness &&
                    trust.feed_drift.freshness.length > 0 && (
                      <div style={{ marginTop: 8, fontSize: 10, color: '#8fb7a9' }}>
                        {trust.feed_drift.freshness.map((f: FreshnessEntry) => {
                          const label = f.connector_name || f.connector_id || f.cache_key;
                          const src = Array.isArray(f.source) ? f.source.join(', ') : f.source;
                          const tip = [
                            f.connector_id && `id=${f.connector_id}`,
                            f.license && `license=${f.license}`,
                            f.bridge && `bridge=${f.bridge}`,
                            f.endpoint && `api=${f.endpoint}`,
                            src && `source=${src}`,
                            `status=${f.status}`,
                            f.count != null && `count=${f.count}`,
                            f.age_sec != null && `age=${f.age_sec}s`,
                            f.error && `error=${f.error}`,
                          ]
                            .filter(Boolean)
                            .join(' · ');
                          return (
                            <span
                              key={f.cache_key}
                              style={{
                                display: 'inline-block',
                                marginRight: 8,
                                marginBottom: 4,
                                color:
                                  f.status === 'fresh'
                                    ? '#00e5a0'
                                    : f.status === 'error' || f.status === 'missing'
                                      ? '#ff6b35'
                                      : '#ffd23f',
                              }}
                              title={tip}
                            >
                              {label}:{f.count ?? '—'}
                            </span>
                          );
                        })}
                      </div>
                    )}
                  {(trust?.briefing_pipeline || briefingQuality?.meta) &&
                    (() => {
                      const pipe = trust?.briefing_pipeline || {};
                      const meta = briefingQuality?.meta || {};
                      const collected = pipe.gdelt_collected ?? meta.gdelt_collected;
                      const placed = pipe.gdelt_digest_lines ?? meta.gdelt_digest_lines;
                      const blocker = pipe.pipeline_blocker ?? meta.gdelt_pipeline_blocker;
                      const placedOk = pipe.pipeline_placed_ok ?? meta.gdelt_pipeline_placed_ok;
                      const watchCount =
                        pipe.watch_count ?? meta.watch_count ?? briefing?.watch_items?.length;
                      const corroAvg = pipe.corroboration_avg_local ?? meta.corroboration_avg_local;
                      const corroBlocker = pipe.corroboration_blocker ?? meta.corroboration_blocker;
                      const predAcc = pipe.prediction_accuracy_30d ?? meta.prediction_accuracy_30d;
                      const predPending = pipe.prediction_pending ?? meta.prediction_pending;
                      const predSample = pipe.prediction_sample_30d ?? meta.prediction_sample_30d;
                      const blockerHint =
                        blocker === 'empty_feed_body'
                          ? 'GDELT rate limit or empty body — wait for disk cache'
                          : blocker === 'bucket_cap'
                            ? 'LOCAL bucket full — GDELT slots env may help'
                            : blocker === 'single_source_local'
                              ? 'LOCAL digest lines share one feed family only'
                              : blocker || '';
                      if (
                        collected == null &&
                        placed == null &&
                        !blocker &&
                        watchCount == null &&
                        corroAvg == null &&
                        predPending == null
                      )
                        return null;
                      return (
                        <div className="analysis-row" style={{ fontSize: 11, marginTop: 8 }}>
                          <span
                            style={{
                              color: placedOk === false ? '#ffd23f' : '#00e5a0',
                              fontWeight: 'bold',
                            }}
                          >
                            GDELT {collected ?? '—'}→{placed ?? '—'}
                          </span>
                          {watchCount != null && (
                            <span
                              style={{ color: '#7ec8ff' }}
                              title="Anticipatory watch items (24–72h)"
                            >
                              WATCH {watchCount}
                            </span>
                          )}
                          {corroAvg != null && (
                            <span
                              style={{
                                color:
                                  corroAvg >= 0.75
                                    ? '#00e5a0'
                                    : corroAvg >= 0.5
                                      ? '#ffd23f'
                                      : '#ff6b35',
                              }}
                              title="LOCAL digest corroboration (multi-source verification)"
                            >
                              VERIFY {Math.round(corroAvg * 100)}%
                            </span>
                          )}
                          {predPending != null && (
                            <span
                              style={{
                                color: predAcc != null && predAcc >= 0.6 ? '#00e5a0' : '#7ec8ff',
                              }}
                              title="Watch-item outcomes after 24–72h horizon (Track 4 ledger)"
                            >
                              PRED {predAcc != null ? `${Math.round(predAcc * 100)}%` : '—'}
                              {predSample != null ? ` n=${predSample}` : ''} · {predPending} pending
                            </span>
                          )}
                          {blocker || corroBlocker ? (
                            <span style={{ color: '#ffd23f' }} title={blockerHint}>
                              BLOCKER: {blocker || corroBlocker}
                            </span>
                          ) : (
                            <span style={{ color: '#8fb7a9' }}>pipeline OK</span>
                          )}
                        </div>
                      );
                    })()}
                </div>
              )}
              <div className="analysis-col analysis-col--single">
                {analysisTab === 'operator' &&
                  results.statements?.total_statements != null &&
                  results.statements.total_statements > 0 && (
                    <div className="analysis-section">
                      <h3>PROVENANCE OVERVIEW</h3>
                      <ProvenanceGlobalStats />
                    </div>
                  )}

                {analysisTab === 'alerts' &&
                  nodes?.nodes?.some((n: NodeEntry) => (n.health?.disk_pct ?? 0) >= 85) && (
                    <div className="analysis-section critical">
                      <h3>⚠ EDGE NODE DISK</h3>
                      {nodes.nodes
                        .filter((n: NodeEntry) => (n.health?.disk_pct ?? 0) >= 85)
                        .map((n: NodeEntry, i: number) => (
                          <div
                            key={i}
                            className="analysis-row"
                            style={{ borderLeft: '3px solid #ffd23f' }}
                          >
                            <span style={{ color: '#ffd23f', fontWeight: 'bold' }}>DISK</span>
                            <span>
                              {n.name}: {n.health?.disk_pct}% — run `sudo bash
                              ~/pi-disk-maintenance.sh` on Pi
                            </span>
                          </div>
                        ))}
                    </div>
                  )}

                {analysisTab === 'alerts' &&
                  ((correlations?.situations?.length ?? 0) > 0 || (anomalies?.count ?? 0) > 0) && (
                    <div className="analysis-section critical">
                      <h3>
                        🚨 CRITICAL ALERTS (
                        {(correlations?.situations?.length || 0) + (anomalies?.count || 0)})
                      </h3>
                      {correlations?.situations?.map((s: SituationEntry, i: number) => (
                        <div
                          key={i}
                          className="analysis-row"
                          style={{ borderLeft: `3px solid ${severityColor(s.severity || '')}` }}
                        >
                          <span
                            style={{
                              color: severityColor(s.severity || ''),
                              fontWeight: 'bold',
                              minWidth: 70,
                            }}
                          >
                            {s.severity?.toUpperCase()}
                          </span>
                          <span>{s.title}</span>
                          {s.location?.lon != null && (
                            <button
                              className="locate-mini"
                              onClick={() => {
                                onClose();
                                onFocus({
                                  kind: 'situation',
                                  lon: s.location!.lon!,
                                  lat: s.location!.lat!,
                                  height: 400000,
                                  title: s.title || '',
                                  lines: [
                                    `TYPE: ${s.type || '—'}`,
                                    `SEVERITY: ${s.severity || '—'}`,
                                  ],
                                });
                              }}
                            >
                              ◎
                            </button>
                          )}
                        </div>
                      ))}
                      {anomalies?.anomalies?.slice(0, 8).map((a: AnomalyEntry, i: number) => (
                        <div
                          key={i}
                          className="analysis-row"
                          style={{ borderLeft: '3px solid #ff2d00' }}
                        >
                          <span style={{ color: '#ff2d00', fontWeight: 'bold', minWidth: 70 }}>
                            ANOMALY
                          </span>
                          <span>
                            {a.callsign || a.icao24} — {a.reasons?.join(', ')}
                          </span>
                          <button
                            className="locate-mini"
                            onClick={() => {
                              onClose();
                              onFocus({
                                kind: 'anomaly',
                                lon: a.lon || 0,
                                lat: a.lat || 0,
                                height: 400000,
                                title: `Anomaly ${a.icao24}`,
                                lines: a.reasons || [],
                              });
                            }}
                          >
                            ◎
                          </button>
                        </div>
                      ))}
                    </div>
                  )}

                {analysisTab === 'alerts' &&
                  briefing?.watch_items &&
                  briefing.watch_items.length > 0 && (
                    <div className="analysis-section">
                      <h3>👁 WATCH ITEMS ({briefing.watch_items.length})</h3>
                      {briefing.watch_items.map((w: WatchItem, i: number) => (
                        <div
                          key={w.id || i}
                          className="analysis-row"
                          style={{ borderLeft: '3px solid #7ec8ff' }}
                        >
                          <span style={{ color: '#7ec8ff', fontWeight: 'bold', minWidth: 52 }}>
                            {w.horizon_h}h
                          </span>
                          <span>{w.title}</span>
                          <span style={{ color: '#8fb7a9', fontSize: 10 }}>
                            {Math.round((w.confidence ?? 0) * 100)}% ·{' '}
                            {(w.sources || []).join(', ')}
                            {w.delta_score != null ? ` · Δ${Number(w.delta_score).toFixed(2)}` : ''}
                          </span>
                          {w.lat != null && w.lon != null && (
                            <button
                              className="locate-mini"
                              title="Fly to watch cell on globe"
                              onClick={() => {
                                onClose();
                                onFocus({
                                  kind: 'watch',
                                  lon: w.lon!,
                                  lat: w.lat!,
                                  height: 800000,
                                  title: w.title || '',
                                  lines: [
                                    `HORIZON: ${w.horizon_h}h`,
                                    `CONFIDENCE: ${Math.round((w.confidence ?? 0) * 100)}%`,
                                    `BUCKET: ${w.bucket || '—'}`,
                                    `SOURCES: ${(w.sources || []).join(', ') || '—'}`,
                                  ],
                                });
                              }}
                            >
                              ◎
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                {analysisTab === 'alerts' &&
                  predictions?.enabled &&
                  ((predictions.pending?.length ?? 0) > 0 ||
                    (predictions.resolved_recent?.length ?? 0) > 0) && (
                    <div className="analysis-section">
                      <h3>
                        📊 PREDICTION LEDGER ({predictions.stats?.pending ?? 0} pending
                        {(predictions.overdue_count ?? 0) > 0
                          ? ` · ${predictions.overdue_count} overdue`
                          : ''}
                        {predictions.due_next
                          ? ` · next ${formatPredDue(predictions.due_next)}`
                          : ''}
                        )
                      </h3>
                      {(predictions.stats?.sample_size ?? 0) > 0 && (
                        <div className="analysis-row" style={{ fontSize: 10, color: '#8fb7a9' }}>
                          30d hit rate {Math.round((predictions.stats?.accuracy ?? 0) * 100)}% · n=
                          {predictions.stats?.sample_size}
                        </div>
                      )}
                      {predictions.pending?.slice(0, 6).map((p: PredictionEntry) => (
                        <div
                          key={p.id ?? p.watch_id}
                          className="analysis-row"
                          style={{ borderLeft: `3px solid ${p.overdue ? '#ffd23f' : '#7ec8ff'}` }}
                        >
                          <span
                            style={{
                              color: p.overdue ? '#ffd23f' : '#7ec8ff',
                              fontWeight: 'bold',
                              minWidth: 72,
                            }}
                          >
                            {formatPredDue(p.due_at, p.overdue)}
                          </span>
                          <span style={{ flex: 1 }}>{p.claim}</span>
                          <span style={{ color: '#8fb7a9', fontSize: 10 }}>
                            {(p.prefix || '—').toUpperCase()} · {p.horizon_h}h
                          </span>
                        </div>
                      ))}
                      {predictions.resolved_recent?.slice(0, 4).map((p: PredictionEntry) => (
                        <div
                          key={`r-${p.id}`}
                          className="analysis-row"
                          style={{ borderLeft: `3px solid ${p.hit ? '#00e5a0' : '#ff6b35'}` }}
                        >
                          <span
                            style={{
                              color: p.hit ? '#00e5a0' : '#ff6b35',
                              fontWeight: 'bold',
                              minWidth: 72,
                            }}
                          >
                            {p.hit ? 'HIT' : 'MISS'}
                          </span>
                          <span style={{ flex: 1 }} title={p.outcome || ''}>
                            {p.claim}
                          </span>
                          <span style={{ color: '#8fb7a9', fontSize: 10 }}>
                            {(p.prefix || '—').toUpperCase()}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                {analysisTab === 'alerts' &&
                  briefing?.intel?.entities &&
                  briefing.intel.entities.length > 0 && (
                    <div className="analysis-section">
                      <h3>
                        🕸 INTEL ENTITIES ({briefing.intel.count ?? briefing.intel.entities.length})
                      </h3>
                      {briefing.intel.by_bucket && (
                        <div className="analysis-row" style={{ fontSize: 10, color: '#8fb7a9' }}>
                          LOCAL {briefing.intel.by_bucket.local ?? 0} · REGION{' '}
                          {briefing.intel.by_bucket.regional ?? 0} · GLOBAL{' '}
                          {briefing.intel.by_bucket.global ?? 0}
                        </div>
                      )}
                      {briefing.intel.entities.slice(0, 6).map((e: IntelEntity, i: number) => (
                        <div
                          key={e.id || i}
                          className="analysis-row"
                          style={{ borderLeft: '3px solid #c084fc' }}
                        >
                          <span
                            style={{
                              color: '#c084fc',
                              fontWeight: 'bold',
                              minWidth: 52,
                              textTransform: 'uppercase',
                              fontSize: 10,
                            }}
                          >
                            {(e.bucket || '—').slice(0, 6)}
                          </span>
                          <span style={{ flex: 1 }}>{e.caption || e.id}</span>
                          <span style={{ color: '#8fb7a9', fontSize: 10 }}>
                            {e.schema || 'Entity'}
                          </span>
                          {e.lat != null && e.lon != null && (
                            <button
                              className="locate-mini"
                              title="Fly to entity on globe"
                              onClick={() => {
                                onClose();
                                onFocus({
                                  kind: 'intel',
                                  lon: e.lon!,
                                  lat: e.lat!,
                                  height: 600000,
                                  title: e.caption || e.id || '',
                                  lines: [
                                    `SCHEMA: ${e.schema || '—'}`,
                                    `BUCKET: ${e.bucket || '—'}`,
                                    `DATASETS: ${(e.datasets || []).join(', ') || '—'}`,
                                  ],
                                });
                              }}
                            >
                              ◎
                            </button>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                {analysisTab === 'alerts' && gdacs.length > 0 && (
                  <div className="analysis-section">
                    <h3>🌊 HUMANITARIAN ALERTS ({gdacs.length})</h3>
                    {gdacs.slice(0, 8).map((a: GdacsAlert, i: number) => {
                      const gt = gdacsType(a.title || '');
                      return (
                        <div
                          key={i}
                          className="analysis-row"
                          style={{ borderLeft: `3px solid ${gt.color}` }}
                        >
                          <span style={{ color: gt.color, fontWeight: 'bold', minWidth: 40 }}>
                            {gt.label}
                          </span>
                          <span style={{ flex: 1 }}>{a.title || '—'}</span>
                          <span style={{ color: '#6f8c84', fontSize: 10 }}>
                            {a.published ? new Date(a.published).toLocaleDateString() : '—'}
                          </span>
                          {a.lat != null && (
                            <button
                              className="locate-mini"
                              onClick={() => {
                                onClose();
                                onFocus({
                                  kind: 'gdacs',
                                  lon: a.lon!,
                                  lat: a.lat!,
                                  height: 400000,
                                  title: a.title || '',
                                  lines: [a.description?.substring(0, 100) || ''],
                                });
                              }}
                            >
                              ◎
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                {analysisTab === 'operator' && agenticTrace && (
                  <AgenticLoopPanel agentic={agenticTrace} />
                )}

                {analysisTab === 'operator' &&
                  briefing?.digest_line_meta &&
                  briefing.digest_line_meta.length > 0 && (
                    <AnalysisCollapsible
                      title="✓ DIGEST VERIFICATION"
                      count={briefing.digest_line_meta.length}
                      defaultOpen={weakDigestCount > 0}
                    >
                      {briefing.digest_line_meta
                        .slice(0, 8)
                        .map((row: DigestLineMeta, i: number) => (
                          <div
                            key={i}
                            className="analysis-row"
                            style={{
                              borderLeft: `3px solid ${
                                row.label === 'corroborated'
                                  ? '#00e5a0'
                                  : row.label === 'contradictory'
                                    ? '#ff2d00'
                                    : '#ffd23f'
                              }`,
                            }}
                          >
                            <span
                              style={{
                                fontWeight: 'bold',
                                minWidth: 88,
                                textTransform: 'uppercase',
                                fontSize: 10,
                              }}
                            >
                              {row.label || 'single-source'}
                            </span>
                            <span style={{ flex: 1 }}>
                              {String(row.text || '')
                                .replace(/^-\s*/, '')
                                .slice(0, 120)}
                            </span>
                            {row.observed_at && (
                              <span
                                style={{
                                  color: '#6a9a8c',
                                  fontSize: 10,
                                  minWidth: 72,
                                  textAlign: 'right',
                                }}
                              >
                                {new Date(row.observed_at).toLocaleString(undefined, {
                                  month: 'short',
                                  day: 'numeric',
                                  hour: '2-digit',
                                  minute: '2-digit',
                                })}
                              </span>
                            )}
                            <span style={{ color: '#8fb7a9', fontSize: 10 }}>
                              {Math.round((row.corroboration ?? 0) * 100)}% ·{' '}
                              {(row.sources || []).slice(0, 3).join(', ')}
                            </span>
                          </div>
                        ))}
                    </AnalysisCollapsible>
                  )}

                {analysisTab === 'operator' && briefing?.text && (
                  <div className="analysis-section">
                    <div className="analysis-section-head">
                      <h3>📋 24H SECURITY DIGEST</h3>
                      <div className="brief-controls">
                        <div className="brief-lang" role="group" aria-label="Briefing language">
                          <button
                            type="button"
                            className={briefLang === 'en' ? 'on' : ''}
                            onClick={() => setBriefLang('en')}
                            disabled={briefBusy}
                          >
                            EN
                          </button>
                          <button
                            type="button"
                            className={briefLang === 'de' ? 'on' : ''}
                            onClick={() => setBriefLang('de')}
                            disabled={briefBusy}
                          >
                            DE
                          </button>
                        </div>
                        <button
                          type="button"
                          className="brief-generate"
                          onClick={generateBriefing}
                          disabled={briefBusy}
                          title="Re-run briefing pipeline now"
                        >
                          {briefBusy ? 'GENERATING…' : 'GENERATE'}
                        </button>
                        <button
                          type="button"
                          className="brief-export"
                          onClick={() => window.open('/api/briefing/export?format=pdf', '_blank')}
                          title="Download briefing as PDF"
                        >
                          PDF
                        </button>
                        <button
                          type="button"
                          className="brief-export"
                          onClick={() => window.open('/api/briefing/export?format=docx', '_blank')}
                          title="Download briefing as Word document"
                        >
                          DOCX
                        </button>
                        <button
                          type="button"
                          className="brief-export"
                          onClick={() => window.open('/api/briefing/export?format=pptx', '_blank')}
                          title="Download briefing as PowerPoint slides"
                        >
                          PPTX
                        </button>
                      </div>
                    </div>
                    {briefError && <div className="brief-error">{briefError}</div>}
                    {(digest || fusionHotspots.length > 0) && (
                      <>
                        {digest && (
                          <div className="analysis-digest-meta">
                            {digest.region_label && (
                              <span className="analysis-digest-chip">
                                REGION <strong>{digest.region_label}</strong>
                              </span>
                            )}
                            {digest.window && (
                              <span className="analysis-digest-chip">
                                WINDOW <strong>{digest.window}</strong>
                              </span>
                            )}
                            <span className="analysis-digest-chip local">
                              LOCAL <strong>{digest.local_count ?? 0}</strong>
                            </span>
                            <span className="analysis-digest-chip regional">
                              REGIONAL <strong>{digest.regional_count ?? 0}</strong>
                            </span>
                            <span className="analysis-digest-chip global">
                              GLOBAL <strong>{digest.global_count ?? 0}</strong>
                            </span>
                            {briefing.created_at && (
                              <span className="analysis-digest-chip">
                                UPDATED{' '}
                                <strong>{new Date(briefing.created_at).toLocaleString()}</strong>
                              </span>
                            )}
                          </div>
                        )}
                        {fusionHotspots.slice(0, 3).map((h: FusionHotspot, i: number) => (
                          <div key={i} className="analysis-fusion-row">
                            <span style={{ color: '#ff6b35', fontWeight: 'bold' }}>
                              FUSION #{i + 1}
                            </span>
                            <span>
                              {h.label || h.summary || `${h.lat?.toFixed(1)}, ${h.lon?.toFixed(1)}`}
                            </span>
                            {h.score != null && <span>score {Number(h.score).toFixed(1)}</span>}
                            {h.lat != null && h.lon != null && (
                              <button
                                className="locate-mini"
                                onClick={() => {
                                  onClose();
                                  onFocus({
                                    kind: 'fusion',
                                    lon: h.lon!,
                                    lat: h.lat!,
                                    height: 800000,
                                    title: h.label || `Fusion hotspot ${i + 1}`,
                                    lines: [`Score: ${h.score ?? '—'}`, h.summary].filter(
                                      Boolean,
                                    ) as string[],
                                  });
                                }}
                              >
                                ◎
                              </button>
                            )}
                          </div>
                        ))}
                      </>
                    )}
                    <div className="analysis-briefing">{briefing.text}</div>
                  </div>
                )}

                {analysisTab === 'feeds' && (cveFeed?.vulnerabilities?.length ?? 0) > 0 && (
                  <AnalysisCollapsible
                    title="🔐 CISA KEV"
                    count={cveFeed!.vulnerabilities!.length}
                    defaultOpen={false}
                  >
                    {cveFeed!.vulnerabilities!.slice(0, 8).map((v: CveVulnerability, i: number) => (
                      <div
                        key={i}
                        className="analysis-row"
                        style={{
                          borderLeft: `3px solid ${v.ransomware === 'Known' ? '#ff2d00' : '#ff6b35'}`,
                        }}
                      >
                        <span style={{ fontWeight: 'bold', minWidth: 120 }}>{v.cve_id}</span>
                        <span style={{ flex: 1 }}>
                          {v.vendor} — {v.product}
                        </span>
                        <span style={{ color: '#6f8c84', fontSize: 10 }}>
                          due {v.due_date || '—'}
                        </span>
                      </div>
                    ))}
                  </AnalysisCollapsible>
                )}

                {analysisTab === 'feeds' && quakes.length > 0 && (
                  <AnalysisCollapsible title="🌋 SEISMIC" count={quakes.length} defaultOpen={false}>
                    {quakes.slice(0, 6).map((q: QuakeEntry, i: number) => (
                      <div
                        key={i}
                        className="analysis-row"
                        style={{
                          borderLeft: `3px solid ${(q.mag ?? 0) >= 5 ? '#ff2d00' : (q.mag ?? 0) >= 3.5 ? '#ff6b35' : '#00e5a0'}`,
                        }}
                      >
                        <span style={{ fontWeight: 'bold', minWidth: 50 }}>
                          M{q.mag?.toFixed(1) ?? '—'}
                        </span>
                        <span style={{ flex: 1 }}>{q.place || '—'}</span>
                        <span style={{ color: '#6f8c84', minWidth: 70 }}>
                          {q.depth != null ? q.depth.toFixed(1) + ' km' : '—'}
                        </span>
                        <span style={{ color: '#6f8c84', minWidth: 50 }}>
                          {q.tsunami ? 'TSU' : ''}
                        </span>
                        <button
                          className="locate-mini"
                          onClick={() => {
                            onClose();
                            onFocus({
                              kind: 'quake',
                              lon: q.lon!,
                              lat: q.lat!,
                              height: 400000,
                              title: `M${q.mag} ${q.place}`,
                              lines: [
                                `Depth: ${q.depth} km`,
                                `Time: ${new Date(q.time || '').toLocaleString()}`,
                                `Tsunami: ${q.tsunami ? 'YES' : 'no'}`,
                              ],
                            });
                          }}
                        >
                          ◎
                        </button>
                      </div>
                    ))}
                  </AnalysisCollapsible>
                )}

                {analysisTab === 'feeds' && results.spaceweather && (
                  <AnalysisCollapsible title="☀️ SPACE WEATHER" defaultOpen={false}>
                    <div className="analysis-row">
                      <span>
                        Kp: <strong>{results.spaceweather.kp_index ?? '—'}</strong>
                      </span>
                      <span>Scale: {results.spaceweather.scale ?? '—'}</span>
                      <span
                        style={{
                          color: results.spaceweather.aurora_visible_midlat ? '#ff6b35' : '#6f8c84',
                        }}
                      >
                        Aurora: {results.spaceweather.aurora_visible_midlat ? 'VISIBLE' : 'none'}
                      </span>
                      <span
                        style={{
                          color: results.spaceweather.hf_radio_impact ? '#ff6b35' : '#6f8c84',
                        }}
                      >
                        HF: {results.spaceweather.hf_radio_impact ? 'IMPACTED' : 'OK'}
                      </span>
                      <span style={{ color: '#6f8c84' }}>
                        History: {results.spaceweather.history?.length ?? 0} pts
                      </span>
                    </div>
                  </AnalysisCollapsible>
                )}

                {analysisTab === 'feeds' && allEvents.length > 0 && (
                  <AnalysisCollapsible
                    title="🔔 EVENTS"
                    count={allEvents.length}
                    defaultOpen={false}
                  >
                    {allEvents.slice(0, 5).map((e: EventEntry, i: number) => (
                      <div
                        key={i}
                        className="analysis-row"
                        style={{
                          borderLeft: `3px solid ${(e.magnitude || 0) > 6 ? '#ff2d00' : '#ff6b35'}`,
                        }}
                      >
                        <span style={{ minWidth: 90, fontWeight: 'bold' }}>
                          {e.category || 'EVENT'}
                        </span>
                        <span style={{ flex: 1 }}>{e.title || '—'}</span>
                        <span style={{ color: '#6f8c84' }}>
                          {e.date ? new Date(e.date).toLocaleDateString() : '—'}
                        </span>
                        {e.lon != null && (
                          <button
                            className="locate-mini"
                            onClick={() => {
                              onClose();
                              onFocus({
                                kind: 'event',
                                lon: e.lon!,
                                lat: e.lat!,
                                height: 400000,
                                title: e.title || '',
                                lines: [`Category: ${e.category || '—'}`, `Date: ${e.date || '—'}`],
                              });
                            }}
                          >
                            ◎
                          </button>
                        )}
                      </div>
                    ))}
                  </AnalysisCollapsible>
                )}

                {analysisTab === 'feeds' && wildfires.length > 0 && (
                  <AnalysisCollapsible
                    title="🔥 WILDFIRES"
                    count={wildfires.length}
                    defaultOpen={false}
                  >
                    {wildfires.slice(0, 5).map((e: EventEntry, i: number) => (
                      <div
                        key={i}
                        className="analysis-row"
                        style={{ borderLeft: '3px solid #ff2d00' }}
                      >
                        <span style={{ flex: 1 }}>{e.title || '—'}</span>
                        <span style={{ color: '#6f8c84' }}>
                          {e.date ? new Date(e.date).toLocaleDateString() : '—'}
                        </span>
                        {e.lon != null && (
                          <button
                            className="locate-mini"
                            onClick={() => {
                              onClose();
                              onFocus({
                                kind: 'wildfire',
                                lon: e.lon!,
                                lat: e.lat!,
                                height: 400000,
                                title: e.title || '',
                                lines: [`Category: ${e.category || '—'}`, `Date: ${e.date || '—'}`],
                              });
                            }}
                          >
                            ◎
                          </button>
                        )}
                      </div>
                    ))}
                  </AnalysisCollapsible>
                )}

                {analysisTab === 'feeds' && (military?.count ?? 0) > 0 && (
                  <AnalysisCollapsible
                    title="✈️ MILITARY AIRCRAFT"
                    count={military!.count}
                    defaultOpen={false}
                  >
                    {military!.aircraft?.slice(0, 8).map((a: MilitaryAircraft, i: number) => (
                      <div
                        key={i}
                        className="analysis-row"
                        style={{
                          borderLeft: ['7500', '7600', '7700'].includes(a.squawk || '')
                            ? '3px solid #ff2d00'
                            : '3px solid #ff6b35',
                        }}
                      >
                        <span style={{ fontWeight: 'bold', minWidth: 80 }}>
                          {a.flight || a.hex}
                        </span>
                        <span style={{ minWidth: 50 }}>{a.type || '—'}</span>
                        <span style={{ color: '#6f8c84', minWidth: 90 }}>
                          Alt:{' '}
                          {a.alt != null && !isNaN(Number(a.alt))
                            ? Number(a.alt).toFixed(0) + ' m'
                            : '—'}
                        </span>
                        <span style={{ color: '#6f8c84', minWidth: 90 }}>
                          Spd:{' '}
                          {a.speed != null && !isNaN(Number(a.speed))
                            ? Number(a.speed).toFixed(0) + ' m/s'
                            : '—'}
                        </span>
                        {a.squawk && (
                          <span style={{ color: '#ff2d00', fontWeight: 'bold', minWidth: 80 }}>
                            SQ {a.squawk}
                          </span>
                        )}
                        <button
                          className="locate-mini"
                          onClick={() => {
                            onClose();
                            onFocus({
                              kind: 'military',
                              lon: a.lon!,
                              lat: a.lat!,
                              height: 400000,
                              title: a.flight || a.hex || '',
                              lines: [
                                `Type: ${a.type || '—'}`,
                                `Alt: ${a.alt} m`,
                                `Speed: ${a.speed} m/s`,
                                `Squawk: ${a.squawk || '—'}`,
                              ],
                            });
                          }}
                        >
                          ◎
                        </button>
                      </div>
                    ))}
                  </AnalysisCollapsible>
                )}

                {analysisTab === 'feeds' && air?.cities && air.cities.length > 0 && (
                  <AnalysisCollapsible
                    title="💨 AIR QUALITY"
                    count={air.cities.length}
                    defaultOpen={false}
                  >
                    <div className="analysis-grid">
                      {air.cities.map((c: AirQualityCity, i: number) => (
                        <div
                          key={i}
                          className="analysis-card"
                          style={{ borderLeft: `3px solid ${aqColor(c.pm25)}` }}
                        >
                          <strong>{c.city}</strong>
                          <span style={{ color: aqColor(c.pm25) }}>
                            PM2.5: {c.pm25 != null ? c.pm25.toFixed(1) : '—'}
                          </span>
                          <span>PM10: {c.pm10 != null ? c.pm10.toFixed(1) : '—'}</span>
                        </div>
                      ))}
                    </div>
                  </AnalysisCollapsible>
                )}

                {analysisTab === 'feeds' && pegel?.gauges && pegel.gauges.length > 0 && (
                  <AnalysisCollapsible
                    title="🌊 RIVER GAUGES DE"
                    count={pegel.gauges.length}
                    defaultOpen={false}
                  >
                    {pegel.gauges
                      .filter((g: PegelGauge) => g.severity === 'critical' || g.severity === 'high')
                      .map((g: PegelGauge, i: number) => (
                        <div
                          key={`a-${i}`}
                          className="analysis-row"
                          style={{ borderLeft: '3px solid #ff6b35' }}
                        >
                          <span style={{ fontWeight: 'bold', minWidth: 100 }}>{g.name}</span>
                          <span style={{ minWidth: 60 }}>{g.water}</span>
                          <span>
                            {g.value} {g.unit}
                          </span>
                          <span style={{ color: '#ff6b35' }}>{g.severity}</span>
                          <button
                            className="locate-mini"
                            onClick={() => {
                              onClose();
                              onFocus({
                                kind: 'pegel',
                                lon: g.lon!,
                                lat: g.lat!,
                                height: 350000,
                                title: `${g.name} (${g.water})`,
                                lines: [
                                  `Level: ${g.value} ${g.unit}`,
                                  `State: ${g.state_mnw_mhw || '—'} / ${g.state_nsw_hsw || '—'}`,
                                ],
                              });
                            }}
                          >
                            ◎
                          </button>
                        </div>
                      ))}
                    {pegel.gauges
                      .filter((g: PegelGauge) => g.severity === 'normal' || g.severity === 'low')
                      .slice(0, 6)
                      .map((g: PegelGauge, i: number) => (
                        <div
                          key={`n-${i}`}
                          className="analysis-row"
                          style={{ borderLeft: '3px solid #4fc3f7' }}
                        >
                          <span style={{ fontWeight: 'bold', minWidth: 100 }}>{g.name}</span>
                          <span style={{ minWidth: 60 }}>{g.water}</span>
                          <span>
                            {g.value} {g.unit}
                          </span>
                          <button
                            className="locate-mini"
                            onClick={() => {
                              onClose();
                              onFocus({
                                kind: 'pegel',
                                lon: g.lon!,
                                lat: g.lat!,
                                height: 350000,
                                title: `${g.name} (${g.water})`,
                                lines: [`Level: ${g.value} ${g.unit}`],
                              });
                            }}
                          >
                            ◎
                          </button>
                        </div>
                      ))}
                  </AnalysisCollapsible>
                )}

                {analysisTab === 'feeds' && results.markets?.crypto && (
                  <AnalysisCollapsible title="📈 CRYPTO MARKETS" defaultOpen={false}>
                    <div className="analysis-grid">
                      {Object.entries(results.markets.crypto).map(
                        ([k, v]: [string, CryptoEntry]) => {
                          const price = v.usd ?? v.price ?? null;
                          const change = v.usd_24h_change ?? v.change_24h ?? null;
                          return (
                            <div key={k} className="analysis-card">
                              <strong>{k.toUpperCase()}</strong>
                              <span>${price != null ? price.toLocaleString('en-US') : '—'}</span>
                              <span style={{ color: (change ?? 0) >= 0 ? '#00e5a0' : '#ff2d00' }}>
                                {change != null ? change.toFixed(2) : '—'}%
                              </span>
                            </div>
                          );
                        },
                      )}
                    </div>
                  </AnalysisCollapsible>
                )}

                {analysisTab === 'feeds' && nodes?.nodes && nodes.nodes.length > 0 && (
                  <AnalysisCollapsible title="📡 NODES" count={nodes.count} defaultOpen={false}>
                    {nodes.nodes.map((n: NodeEntry, i: number) => {
                      const disk = n.health?.disk_pct;
                      const diskWarn = disk != null && disk >= 85;
                      return (
                        <div
                          key={i}
                          className="analysis-row"
                          style={{
                            borderLeft: n.online
                              ? diskWarn
                                ? '3px solid #ffd23f'
                                : '3px solid #00e5a0'
                              : '3px solid #ff2d00',
                          }}
                        >
                          <span style={{ fontWeight: 'bold' }}>{n.name}</span>
                          <span style={{ color: n.online ? '#00e5a0' : '#ff2d00' }}>
                            {n.online ? 'ONLINE' : 'OFFLINE'}
                          </span>
                          <span style={{ color: '#6f8c84' }}>
                            {Math.round(n.age_seconds || 0)}s ago
                          </span>
                          <span style={{ color: '#6f8c84' }}>
                            CPU: {n.health?.cpu_temp_c != null ? n.health.cpu_temp_c + '°C' : '—'}
                          </span>
                          <span style={{ color: '#6f8c84' }}>
                            Load: {n.health?.load_1m != null ? n.health.load_1m : '—'}
                          </span>
                          <span style={{ color: '#6f8c84' }}>
                            RAM: {n.health?.ram_pct != null ? n.health.ram_pct + '%' : '—'}
                          </span>
                          <span
                            style={{
                              color: diskWarn ? '#ffd23f' : '#6f8c84',
                              fontWeight: diskWarn ? 'bold' : 'normal',
                            }}
                          >
                            Disk: {disk != null ? disk + '%' : '—'}
                            {diskWarn ? ' ⚠' : ''}
                          </span>
                          {n.lat && (
                            <button
                              className="locate-mini"
                              onClick={() => {
                                onClose();
                                onFocus({
                                  kind: 'node',
                                  lon: n.lon!,
                                  lat: n.lat!,
                                  height: 400000,
                                  title: n.name || '',
                                  lines: [
                                    `Node: ${n.node_id || '—'}`,
                                    `CPU: ${n.health?.cpu_temp_c ?? '—'}°C`,
                                    `RAM: ${n.health?.ram_pct ?? '—'}%`,
                                    `Disk: ${disk ?? '—'}%`,
                                  ],
                                });
                              }}
                            >
                              ◎
                            </button>
                          )}
                        </div>
                      );
                    })}
                  </AnalysisCollapsible>
                )}

                {analysisTab === 'feeds' && health?.feeds && (
                  <AnalysisCollapsible
                    title="🔌 FEED HEALTH"
                    count={Object.keys(health.feeds).length}
                    defaultOpen={false}
                  >
                    <div className="analysis-grid">
                      {Object.entries(health.feeds)
                        .sort(
                          ([, a]: [string, FeedHealthEntry], [, b]: [string, FeedHealthEntry]) =>
                            (b.age_sec || 0) - (a.age_sec || 0),
                        )
                        .map(([k, v]: [string, FeedHealthEntry]) => {
                          const st = feedHealthStyle(v);
                          return (
                            <div
                              key={k}
                              className="analysis-card"
                              style={{ borderLeft: `3px solid ${st.border}` }}
                            >
                              <strong>{k}</strong>
                              <span style={{ color: st.color }}>
                                {st.label} · {fmtFeedAge(v.age_sec)}
                              </span>
                            </div>
                          );
                        })}
                    </div>
                  </AnalysisCollapsible>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
