import { useCallback, useEffect, useState } from 'react';
import { fetchApi } from '../lib/networkFetch';

interface CiiCountry {
  country_code: string;
  country_name: string;
  iso3: string;
  score: number;
  risk_band: string;
  conflict: number;
  economy: number;
  climate: number;
  governance: number;
  article_count: number;
  event_count: number;
  computed_at: string;
  delta_24h?: number | null;
  trend_7d?: string;
  trend_series?: number[];
}

interface CiiRankings {
  count: number;
  updated: string;
  countries: CiiCountry[];
}

function bandColor(band: string): string {
  switch (band) {
    case 'critical': return '#ff2d00';
    case 'high': return '#ff6b35';
    case 'elevated': return '#ffd23f';
    case 'moderate': return '#4fc3f7';
    default: return '#00e5a0';
  }
}

function bandLabel(band: string): string {
  return band.charAt(0).toUpperCase() + band.slice(1);
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.min(100, score);
  const hue = (1 - pct / 100) * 120;
  return (
    <div style={{ display: 'inline-block', width: 60, height: 6, background: '#222', borderRadius: 3, verticalAlign: 'middle', marginLeft: 6 }}>
      <div style={{ width: `${pct}%`, height: '100%', background: `hsl(${hue}, 85%, 50%)`, borderRadius: 3 }} />
    </div>
  );
}

function FamilyBar({ label, value }: { label: string; value: number }) {
  const pct = Math.min(100, value);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, marginBottom: 2 }}>
      <span style={{ width: 70, color: '#8fa8a0', textTransform: 'uppercase', fontSize: 10 }}>{label}</span>
      <div style={{ flex: 1, height: 4, background: '#222', borderRadius: 2 }}>
        <div style={{ width: `${pct}%`, height: '100%', background: `hsl(${(1 - pct / 100) * 120}, 70%, 45%)`, borderRadius: 2 }} />
      </div>
      <span style={{ width: 28, textAlign: 'right', color: '#ccc', fontVariantNumeric: 'tabular-nums' }}>{value.toFixed(0)}</span>
    </div>
  );
}

function CountryRow({ c }: { c: CiiCountry }) {
  const [expanded, setExpanded] = useState(false);
  const delta = c.delta_24h;
  const deltaColor = delta != null ? (delta > 0 ? '#ff6b35' : delta < 0 ? '#00e5a0' : '#888') : '#888';
  const deltaStr = delta != null ? `${delta > 0 ? '+' : ''}${delta.toFixed(1)}` : '—';

  return (
    <div
      style={{
        borderBottom: '1px solid #1a2a28',
        padding: '6px 0',
        cursor: 'pointer',
      }}
      onClick={() => setExpanded((v) => !v)}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span
          style={{
            display: 'inline-block',
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: bandColor(c.risk_band),
            flexShrink: 0,
          }}
        />
        <span style={{ flex: 1, fontWeight: 600, fontSize: 12 }}>{c.country_name}</span>
        <span style={{ color: '#ccc', fontVariantNumeric: 'tabular-nums', fontWeight: 700, fontSize: 13 }}>
          {c.score.toFixed(0)}
        </span>
        <ScoreBar score={c.score} />
        <span style={{ color: deltaColor, fontSize: 11, width: 40, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
          {deltaStr}
        </span>
        <span style={{ color: '#6f8c84', fontSize: 10, width: 50, textAlign: 'right' }}>
          {bandLabel(c.risk_band)}
        </span>
      </div>
      {expanded && (
        <div style={{ marginLeft: 16, marginTop: 6, padding: '4px 8px', background: '#0d1514', borderRadius: 4 }}>
          <div style={{ display: 'flex', gap: 16, marginBottom: 6, fontSize: 10, color: '#6f8c84' }}>
            <span>Articles: {c.article_count}</span>
            <span>Events: {c.event_count}</span>
            <span>ISO2: {c.country_code}</span>
            <span>ISO3: {c.iso3}</span>
            {c.trend_7d && c.trend_7d !== 'insufficient_data' && <span>Trend: {c.trend_7d}</span>}
          </div>
          <FamilyBar label="Conflict" value={c.conflict} />
          <FamilyBar label="Economy" value={c.economy} />
          <FamilyBar label="Climate" value={c.climate} />
          <FamilyBar label="Governance" value={c.governance} />
        </div>
      )}
    </div>
  );
}

export default function CiiPanel() {
  const [data, setData] = useState<CiiRankings | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetchApi('/api/cii/rankings?limit=100');
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
    const t = setInterval(load, 300000);
    return () => clearInterval(t);
  }, [load]);

  const countries = data?.countries || [];
  const critical = countries.filter((c) => c.risk_band === 'critical');
  const high = countries.filter((c) => c.risk_band === 'high');

  return (
    <div className="data-panel">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
        <button onClick={load} disabled={loading}>
          {loading ? 'Loading…' : '↻ REFRESH'}
        </button>
        <span className="data-count">{data?.count ?? 0} countries</span>
        {critical.length > 0 && (
          <span style={{ color: '#ff2d00', fontSize: 11 }}>
            {critical.length} CRITICAL
          </span>
        )}
        {high.length > 0 && (
          <span style={{ color: '#ff6b35', fontSize: 11 }}>
            {high.length} HIGH
          </span>
        )}
      </div>

      {error && <div className="data-error">{error}</div>}

      <div style={{ display: 'flex', gap: 6, fontSize: 10, color: '#6f8c84', marginBottom: 4, fontWeight: 600, textTransform: 'uppercase' }}>
        <span style={{ flex: 1 }}>Country</span>
        <span style={{ width: 30, textAlign: 'right' }}>CII</span>
        <span style={{ width: 60 }} />
        <span style={{ width: 40, textAlign: 'right' }}>Δ24h</span>
        <span style={{ width: 50, textAlign: 'right' }}>Band</span>
      </div>

      {countries.length === 0 && !loading && !error && (
        <div style={{ color: '#6f8c84', fontSize: 12, padding: 20, textAlign: 'center' }}>
          No CII data. Ensure feeds are active and WORLDBASE_CII=1.
        </div>
      )}

      {countries.map((c) => (
        <CountryRow key={c.country_code} c={c} />
      ))}

      {data?.updated && (
        <div style={{ marginTop: 8, fontSize: 10, color: '#4a6058' }}>
          Updated: {new Date(data.updated).toLocaleString()}
        </div>
      )}
    </div>
  );
}
