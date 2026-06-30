import { useCallback, useEffect, useState, type ReactNode } from 'react';
import type { FocusTarget } from '../lib/focus';
import { fetchApi } from '../lib/networkFetch';
import type {
  HazardsAlert,
  HazardsApiResponse,
  Volcano,
  VolcanoesApiResponse,
  TrafficCamera,
  TrafficCamsApiResponse,
  OutageItem,
  OutagesApiResponse,
  GdeltArticle,
  GdeltPulseApiResponse,
} from '../lib/types';

const BLITZORTUNG_MAP = 'https://maps.blitzortung.org/en/#5/13/100';

type FocusFn = (f: Omit<FocusTarget, 'ts'>) => void;

function FeedSection({
  title,
  countLabel,
  loading,
  error,
  onRefresh,
  children,
}: {
  title: string;
  countLabel?: string;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
  children: ReactNode;
}) {
  return (
    <section>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          flexWrap: 'wrap',
          marginBottom: 8,
        }}
      >
        <button onClick={onRefresh} disabled={loading}>
          {loading ? 'Loading…' : '↻ REFRESH'}
        </button>
        {countLabel && <span className="data-count">{countLabel}</span>}
      </div>
      {error && <div className="data-error">{error}</div>}
      {children}
      <div style={{ marginTop: 8, fontSize: 11, color: '#6f8c84' }}>{title}</div>
    </section>
  );
}

export function GdeltFeedPanel() {
  const [data, setData] = useState<GdeltPulseApiResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetchApi('/api/gdelt/pulse/local');
      if (!r.ok) throw new Error(`${r.status}`);
      const d = await r.json();
      setData(d);
      if (d.error) setError(String(d.error));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <FeedSection
      title={`Region: ${data?.region ?? 'local'} · GDELT DOC 2.0`}
      countLabel={`${data?.count ?? 0} headlines${data?.stale ? ' · stale cache' : ''}`}
      loading={loading}
      error={error}
      onRefresh={load}
    >
      {!data?.articles?.length && !loading && (
        <div className="health-status pending">No headlines</div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {(data?.articles || []).slice(0, 40).map((a: GdeltArticle, i: number) => (
          <div key={i} className="iss-card">
            <strong>{a.title}</strong>
            <small style={{ color: '#6f8c84' }}>
              {a.domain || a.sourcecountry || '—'} · {a.seendate?.slice(0, 8) || ''}
            </small>
            {a.url && (
              <a className="tp-link" href={a.url} target="_blank" rel="noreferrer">
                OPEN ARTICLE ↗
              </a>
            )}
          </div>
        ))}
      </div>
    </FeedSection>
  );
}

export function OutagesPanel({ onFocus }: { onFocus: FocusFn }) {
  const [data, setData] = useState<OutagesApiResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetchApi('/api/outages?limit=40');
      if (!r.ok) throw new Error(`${r.status}`);
      setData(await r.json());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <FeedSection
      title="Sources: IODA (free) · optional Cloudflare Radar"
      countLabel={`${data?.count ?? 0} outage signals · ${data?.geocoded ?? 0} geocoded`}
      loading={loading}
      error={error || data?.error || null}
      onRefresh={load}
    >
      {!data?.items?.length && !loading && (
        <div className="health-status pending">No outage signals</div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {(data?.items || []).map((item: OutageItem, i: number) => (
          <div
            key={i}
            className="iss-card"
            style={{
              cursor: item.lat != null ? 'pointer' : 'default',
              borderLeft: '3px solid #ff6b35',
            }}
            onClick={() =>
              item.lat != null &&
              item.lon != null &&
              onFocus({
                kind: 'outage',
                lon: item.lon,
                lat: item.lat,
                height: 800000,
                title: item.title || 'Internet outage',
                lines: [
                  `Source: ${item.source || 'ioda'}`,
                  `Status: ${item.status || '—'}`,
                  `Type: ${item.type || '—'}`,
                ],
              })
            }
          >
            <span style={{ color: '#ff6b35', fontWeight: 'bold' }}>
              {(item.source || 'IODA').toUpperCase()}
            </span>
            <strong>{item.title}</strong>
            <small style={{ color: '#6f8c84' }}>{item.start || item.type || ''}</small>
          </div>
        ))}
      </div>
    </FeedSection>
  );
}

export function HazardsPanel({ onFocus }: { onFocus: FocusFn }) {
  const [data, setData] = useState<HazardsApiResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetchApi('/api/hazards?limit=60');
      if (!r.ok) throw new Error(`${r.status}`);
      setData(await r.json());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <FeedSection
      title="NWS GeoJSON + Meteoalarm CAP · no API key"
      countLabel={`${data?.count ?? 0} active alerts`}
      loading={loading}
      error={error}
      onRefresh={load}
    >
      {!data?.alerts?.length && !loading && (
        <div className="health-status pending">No hazard alerts</div>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {(data?.alerts || []).slice(0, 50).map((a: HazardsAlert, i: number) => (
          <div
            key={i}
            className="iss-card"
            style={{
              cursor: a.lat != null ? 'pointer' : 'default',
              borderLeft: '3px solid #ffd23f',
            }}
            onClick={() =>
              a.lat != null &&
              a.lon != null &&
              onFocus({
                kind: 'hazard',
                lon: a.lon,
                lat: a.lat,
                height: 400000,
                title: a.title || a.event || 'Weather alert',
                lines: [
                  `Source: ${a.source || '—'}`,
                  `Severity: ${a.severity || '—'}`,
                  a.area || '',
                ],
              })
            }
          >
            <span style={{ color: '#ffd23f', fontWeight: 'bold' }}>
              {(a.source || 'CAP').toUpperCase()}
            </span>
            <strong>{a.title || a.event}</strong>
            <small style={{ color: '#6f8c84' }}>{a.area || a.severity || ''}</small>
          </div>
        ))}
      </div>
    </FeedSection>
  );
}

export function VolcanoesPanel({ onFocus }: { onFocus: FocusFn }) {
  const [activeOnly, setActiveOnly] = useState(false);
  const [data, setData] = useState<VolcanoesApiResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetchApi(
        `/api/volcanoes?active_only=${activeOnly ? 'true' : 'false'}&limit=200`,
      );
      if (!r.ok) throw new Error(`${r.status}`);
      setData(await r.json());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [activeOnly]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <FeedSection
      title="Smithsonian GVP holocene volcanoes · WFS"
      countLabel={`${data?.count ?? 0} volcanoes · ${data?.active_count ?? 0} active`}
      loading={loading}
      error={error || data?.error || null}
      onRefresh={load}
    >
      <label
        style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, fontSize: 12 }}
      >
        <input
          type="checkbox"
          checked={activeOnly}
          onChange={(e) => setActiveOnly(e.target.checked)}
        />
        Active only (eruption since 2020 or observed)
      </label>
      <table className="data-table clickable">
        <thead>
          <tr>
            <th>Name</th>
            <th>Country</th>
            <th>Type</th>
            <th>Last eruption</th>
            <th>Ele (m)</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(data?.volcanoes || []).slice(0, 100).map((v: Volcano) => (
            <tr
              key={v.number || v.name}
              onClick={() =>
                v.lon != null &&
                v.lat != null &&
                onFocus({
                  kind: 'volcano',
                  lon: v.lon,
                  lat: v.lat,
                  height: 350000,
                  title: v.name || 'Volcano',
                  lines: [
                    `Country: ${v.country || '—'}`,
                    `Type: ${v.type || '—'}`,
                    `Last: ${v.last_eruption ?? '—'}`,
                    `Evidence: ${v.evidence || '—'}`,
                  ],
                })
              }
            >
              <td>
                <strong>{v.name}</strong>
              </td>
              <td>{v.country || '—'}</td>
              <td>{v.type || '—'}</td>
              <td>{v.last_eruption ?? '—'}</td>
              <td>{v.elevation_m ?? '—'}</td>
              <td className="locate-cell">◎</td>
            </tr>
          ))}
        </tbody>
      </table>
    </FeedSection>
  );
}

export function TrafficPanel({ onFocus }: { onFocus: FocusFn }) {
  const [scope, setScope] = useState('regional');
  const [data, setData] = useState<TrafficCamsApiResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetchApi(`/api/traffic/cams?scope=${encodeURIComponent(scope)}&limit=120`);
      if (!r.ok) throw new Error(`${r.status}`);
      setData(await r.json());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [scope]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <FeedSection
      title={`Source: ${data?.source || '—'} · Singapore regional free · Thailand iTIC needs token`}
      countLabel={`${data?.count ?? 0} cameras · ${scope.toUpperCase()}`}
      loading={loading}
      error={error || data?.error || null}
      onRefresh={load}
    >
      <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
        {(['regional', 'global', 'all'] as const).map((s) => (
          <button
            key={s}
            className={scope === s ? 'on' : ''}
            onClick={() => setScope(s)}
            style={{ opacity: scope === s ? 1 : 0.6, marginRight: 6 }}
          >
            {s.toUpperCase()}
          </button>
        ))}
      </div>
      <table className="data-table clickable">
        <thead>
          <tr>
            <th>Name</th>
            <th>Source</th>
            <th>Lat</th>
            <th>Lon</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {(data?.cameras || []).slice(0, 80).map((c: TrafficCamera) => (
            <tr
              key={c.id}
              onClick={() =>
                c.lat != null &&
                c.lon != null &&
                onFocus({
                  kind: 'traffic_cam',
                  lon: c.lon,
                  lat: c.lat,
                  height: 120000,
                  title: c.name || c.id,
                  lines: [`ID: ${c.id}`, `Source: ${c.source || '—'}`, c.road || ''],
                  link: c.detail_url,
                })
              }
            >
              <td>{c.name || c.id}</td>
              <td>{c.source || '—'}</td>
              <td>{c.lat?.toFixed(4) ?? '—'}</td>
              <td>{c.lon?.toFixed(4) ?? '—'}</td>
              <td className="locate-cell">◎</td>
            </tr>
          ))}
        </tbody>
      </table>
    </FeedSection>
  );
}

export function LightningMapPanel() {
  return (
    <section className="lightning-panel">
      <p className="data-embed-note lightning-panel-note">
        Live map by{' '}
        <a href={BLITZORTUNG_MAP} target="_blank" rel="noreferrer">
          Blitzortung.org
        </a>{' '}
        · entertainment only — not for life-safety ·{' '}
        <a href={BLITZORTUNG_MAP} target="_blank" rel="noreferrer">
          OPEN FULL MAP ↗
        </a>
      </p>
      <iframe
        src={BLITZORTUNG_MAP}
        title="Blitzortung live lightning map"
        className="lightning-embed-map"
        allow="fullscreen"
      />
    </section>
  );
}
