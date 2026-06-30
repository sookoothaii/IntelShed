import { useCallback, useEffect, useState } from 'react';
import { fetchApi } from '../lib/networkFetch';
import LayerTree from './LayerTree';

/* ── Types ────────────────────────────────────────────────────────────────── */

type HealthResponse = {
  status?: string;
  feeds_fresh?: number;
  feeds_stale?: number;
  feed_count?: number | string;
  feeds?: Record<string, Record<string, unknown>>;
  ftm?: { ready?: boolean; entities?: number | string };
  [key: string]: unknown;
};

type FeedRow = {
  key: string;
  status?: string;
  fresh?: boolean;
  age_sec?: number;
  count?: number | null;
  error?: string | null;
};

/* ── Component ─────────────────────────────────────────────────────────────── */

export default function SidebarLeft({
  layers,
  onToggleLayer,
  collapsed,
  onToggleCollapse,
  stats,
}: {
  layers: Record<string, boolean>;
  onToggleLayer: (k: string) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
  stats?: Record<string, number>;
}) {
  const [health, setHealth] = useState<HealthResponse | null>(null);

  const loadHealth = useCallback(async () => {
    try {
      const r = await fetchApi('/api/health');
      if (r.ok) setHealth(await r.json());
    } catch {
      /* fail-soft */
    }
  }, []);

  useEffect(() => {
    loadHealth();
    const t = setInterval(loadHealth, 60_000);
    return () => clearInterval(t);
  }, [loadHealth]);

  const feeds: FeedRow[] = health?.feeds
    ? Object.entries(health.feeds).map(([key, val]) => ({ key, ...val }))
    : [];
  const freshCount = feeds.filter(
    (f) => f.fresh !== false && f.status !== 'stale' && f.status !== 'error',
  ).length;
  const staleCount = feeds.filter((f) => f.fresh === false || f.status === 'stale').length;
  const errorCount = feeds.filter((f) => f.status === 'error').length;

  if (collapsed) {
    return (
      <aside className="hud-sidebar hud-sidebar--left hud-sidebar--collapsed">
        <button
          className="sidebar-expand-btn"
          onClick={onToggleCollapse}
          title="Expand left sidebar"
        >
          ▸
        </button>
      </aside>
    );
  }

  return (
    <aside className="hud-sidebar hud-sidebar--left">
      <div className="sidebar-header">
        <span className="sidebar-title">LAYERS &amp; FEEDS</span>
        <button className="sidebar-collapse-btn" onClick={onToggleCollapse} title="Collapse">
          ◂
        </button>
      </div>

      {/* Layer tree */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">LAYER TREE</div>
        <LayerTree layers={layers} onToggleLayer={onToggleLayer} stats={stats} />
      </div>

      {/* Feed status summary */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">FEED STATUS</div>
        <div className="sidebar-feed-summary">
          <span className="sidebar-feed-pill sidebar-feed-pill--ok">{freshCount} fresh</span>
          {staleCount > 0 && (
            <span className="sidebar-feed-pill sidebar-feed-pill--warn">{staleCount} stale</span>
          )}
          {errorCount > 0 && (
            <span className="sidebar-feed-pill sidebar-feed-pill--err">{errorCount} error</span>
          )}
        </div>
        <div className="sidebar-feed-list">
          {feeds.slice(0, 12).map((f) => (
            <div key={f.key} className="sidebar-feed-row">
              <span
                className="sidebar-feed-dot"
                style={{
                  background:
                    f.status === 'error'
                      ? '#ff4d5e'
                      : f.fresh === false || f.status === 'stale'
                        ? '#ffd23f'
                        : 'var(--accent)',
                }}
              />
              <span className="sidebar-feed-name">{f.key}</span>
              <span className="sidebar-feed-count">{f.count ?? '—'}</span>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}
