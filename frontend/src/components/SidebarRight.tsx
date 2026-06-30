import { lazy, Suspense, useCallback, useEffect, useState } from 'react';
import { fetchApi } from '../lib/networkFetch';
import { useBriefingQuery } from '../hooks/useSharedFeeds';
import ActionBar from './ActionBar';
import TrustGauge from './TrustGauge';

const EntityDetailPanel = lazy(() => import('./EntityDetailPanel'));

/* ── Types ────────────────────────────────────────────────────────────────── */

interface WatchItem {
  id?: string;
  horizon_h?: number;
  title?: string;
  confidence?: number;
  sources?: string[];
  bucket?: string;
  lat?: number;
  lon?: number;
}

interface BriefingData {
  text?: string;
  quality?: { score?: number };
  watch_items?: WatchItem[];
  insights?: { title?: string; summary?: string; severity?: string }[];
  created_at?: string;
  digest_line_meta?: { sources?: string[]; corroboration?: number }[];
}

interface TrustData {
  score?: number;
  max_score?: number;
}

interface FeedHealthEntry {
  fresh?: boolean;
}
interface HealthData {
  feeds?: Record<string, FeedHealthEntry>;
}

/* ── Component ─────────────────────────────────────────────────────────────── */

export default function SidebarRight({
  collapsed,
  onToggleCollapse,
  onFocus,
  entityId,
  onSelectEntity,
}: {
  collapsed: boolean;
  onToggleCollapse: () => void;
  onFocus?: (lat: number, lon: number, title: string) => void;
  entityId?: string | null;
  onSelectEntity?: (id: string) => void;
}) {
  const { data: briefing } = useBriefingQuery();
  const [trustData, setTrustData] = useState<TrustData | null>(null);
  const [healthData, setHealthData] = useState<HealthData | null>(null);

  const loadTrustAndHealth = useCallback(async () => {
    try {
      const [tr, hr] = await Promise.all([fetchApi('/api/trust'), fetchApi('/api/health')]);
      if (tr.ok) setTrustData(await tr.json());
      if (hr.ok) setHealthData(await hr.json());
    } catch {
      /* fail-soft */
    }
  }, []);

  useEffect(() => {
    loadTrustAndHealth();
    const t = setInterval(loadTrustAndHealth, 60_000);
    return () => clearInterval(t);
  }, [loadTrustAndHealth]);

  const b = briefing as BriefingData | undefined;
  const watchItems = b?.watch_items ?? [];
  const insights = b?.insights ?? [];
  const qualityScore = b?.quality?.score;
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const selectedInsight = selectedIdx != null ? insights[selectedIdx] : null;

  const fieldTrustVal =
    trustData?.score != null && trustData?.max_score != null
      ? trustData.score / trustData.max_score
      : null;
  const digestMeta = b?.digest_line_meta ?? [];
  const distinctSources = new Set<string>();
  for (const row of digestMeta) {
    if (row.sources) for (const s of row.sources) distinctSources.add(s);
  }
  const sourceDiversityVal = digestMeta.length > 0 ? Math.min(distinctSources.size / 10, 1) : null;
  const corrobVals = digestMeta.map((r) => Number(r.corroboration ?? 0)).filter((n) => !isNaN(n));
  const corroborationVal =
    corrobVals.length > 0 ? corrobVals.reduce((a, c) => a + c, 0) / corrobVals.length : null;
  const feedEntries = healthData?.feeds ? Object.values(healthData.feeds) : [];
  const feedHealthVal =
    feedEntries.length > 0 ? feedEntries.filter((f) => f.fresh).length / feedEntries.length : null;

  if (collapsed) {
    return (
      <aside className="hud-sidebar hud-sidebar--right hud-sidebar--collapsed">
        <button
          className="sidebar-expand-btn"
          onClick={onToggleCollapse}
          title="Expand right sidebar"
        >
          ◂
        </button>
      </aside>
    );
  }

  return (
    <aside className="hud-sidebar hud-sidebar--right">
      <div className="sidebar-header">
        <span className="sidebar-title">BRIEFING &amp; TRUST</span>
        <button className="sidebar-collapse-btn" onClick={onToggleCollapse} title="Collapse">
          ▸
        </button>
      </div>

      {/* Trust gauges */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">TRUST METRICS</div>
        <div className="trust-gauge-row trust-gauge-row--compact">
          <TrustGauge value={fieldTrustVal} label="Field" size={48} compact />
          <TrustGauge value={qualityScore ?? null} label="Quality" size={48} compact />
          <TrustGauge value={sourceDiversityVal} label="Sources" size={48} compact />
          <TrustGauge value={corroborationVal} label="Corrob" size={48} compact />
          <TrustGauge value={feedHealthVal} label="Feeds" size={48} compact />
        </div>
        {b?.created_at && (
          <div className="sidebar-meta-row">
            <span>Updated</span>
            <strong>{new Date(b.created_at).toLocaleTimeString()}</strong>
          </div>
        )}
      </div>

      {/* Watch items */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">
          WATCH ITEMS{watchItems.length > 0 && ` (${watchItems.length})`}
        </div>
        {watchItems.length === 0 ? (
          <div className="sidebar-empty">No active watch items</div>
        ) : (
          <div className="sidebar-watch-list">
            {watchItems.slice(0, 8).map((w, i) => (
              <div
                key={w.id || i}
                className="sidebar-watch-row"
                onClick={() => {
                  if (onFocus && w.lat != null && w.lon != null) {
                    onFocus(w.lat, w.lon, w.title || 'Watch item');
                  }
                }}
                style={{ cursor: onFocus && w.lat != null ? 'pointer' : 'default' }}
              >
                <span className="sidebar-watch-horizon">{w.horizon_h ?? '—'}h</span>
                <span className="sidebar-watch-title">{w.title || 'Untitled'}</span>
                {w.confidence != null && (
                  <span className="sidebar-watch-conf">{(w.confidence * 100).toFixed(0)}%</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Insights */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">
          INSIGHTS{insights.length > 0 && ` (${insights.length})`}
        </div>
        {insights.length === 0 ? (
          <div className="sidebar-empty">No insights available</div>
        ) : (
          <div className="sidebar-insight-list">
            {insights.slice(0, 5).map((ins, i) => (
              <div
                key={i}
                className={`sidebar-insight-row${selectedIdx === i ? ' sidebar-insight-row--selected' : ''}`}
                onClick={() => setSelectedIdx(selectedIdx === i ? null : i)}
                style={{ cursor: 'pointer' }}
              >
                <div className="sidebar-insight-title">{ins.title || 'Untitled'}</div>
                {ins.summary && <div className="sidebar-insight-summary">{ins.summary}</div>}
                {ins.severity && (
                  <span
                    className={`sidebar-insight-severity sidebar-insight-severity--${ins.severity}`}
                  >
                    {ins.severity.toUpperCase()}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Entity detail panel */}
      {entityId && (
        <Suspense fallback={<div className="sidebar-empty">Loading entity…</div>}>
          <EntityDetailPanel
            entityId={entityId}
            onSelectEntity={onSelectEntity}
            onFocus={onFocus}
          />
        </Suspense>
      )}

      {selectedInsight && (
        <div className="sidebar-section">
          <div className="sidebar-section-title">ACTIONS</div>
          <div className="action-bar action-bar--compact">
            <ActionBar
              itemId={`insight:${selectedInsight.title || 'untitled'}`}
              itemTitle={selectedInsight.title}
              showPublish={false}
            />
          </div>
        </div>
      )}
    </aside>
  );
}
