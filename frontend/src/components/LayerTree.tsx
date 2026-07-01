import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { fetchApi } from '../lib/networkFetch';

/* ── Types ────────────────────────────────────────────────────────────────── */

interface LayerDef {
  key: string;
  label: string;
  color?: string;
  /** Feed key in /api/health feeds dict — used for status dot + item count */
  feedKey?: string;
  /** Stat key from Globe stats — used for item count badge */
  statKey?: string;
}

interface LayerGroup {
  group: string;
  layers: LayerDef[];
}

export interface FeedHealthInfo {
  status?: string;
  fresh?: boolean;
  count?: number | null;
  age_sec?: number;
}

/* ── Layer definitions (matches GlobeLayers keys) ─────────────────────────── */

const LAYER_GROUPS: LayerGroup[] = [
  {
    group: 'Live Tracking',
    layers: [
      {
        key: 'aircraft',
        label: 'Aircraft',
        color: '#ffd23f',
        feedKey: 'aircraft',
        statKey: 'aircraft',
      },
      { key: 'satellites', label: 'Satellites', color: '#00e5ff', statKey: 'satellites' },
      { key: 'military', label: 'Military', color: '#ff6b35', statKey: 'military' },
      {
        key: 'maritime',
        label: 'Maritime AIS',
        color: '#00e5ff',
        feedKey: 'maritime',
        statKey: 'maritime',
      },
      { key: 'piAis', label: 'Pi AIS Coverage', color: '#00e5ff', statKey: 'piAis' },
      { key: 'transit', label: 'Transit', color: '#ffd23f', statKey: 'transit' },
    ],
  },
  {
    group: 'Geo Hazards',
    layers: [
      { key: 'quakes', label: 'Earthquakes', feedKey: 'quakes', statKey: 'quakes' },
      { key: 'wildfires', label: 'Wildfires', feedKey: 'wildfires', statKey: 'wildfires' },
      { key: 'volcanoes', label: 'Volcanoes', statKey: 'volcanoes' },
      { key: 'lightning', label: 'Lightning', feedKey: 'lightning', statKey: 'lightning' },
      { key: 'hazards', label: 'Hazards', feedKey: 'hazards', statKey: 'hazards' },
      { key: 'outages', label: 'Outages', feedKey: 'outages', statKey: 'outages' },
    ],
  },
  {
    group: 'Environment',
    layers: [
      { key: 'weather', label: 'Weather', statKey: 'weather' },
      { key: 'airquality', label: 'Air Quality', statKey: 'airquality' },
      { key: 'pegel', label: 'Water Levels', feedKey: 'pegel', statKey: 'pegel' },
      { key: 'energy', label: 'Energy', feedKey: 'energy', statKey: 'energy' },
      { key: 'spaceweather', label: 'Space Weather', statKey: 'spaceweather' },
    ],
  },
  {
    group: 'Intelligence',
    layers: [
      { key: 'intelFt', label: 'Intel Entities', color: '#c084fc', statKey: 'intelFt' },
      { key: 'flowsint', label: 'Flowsint Pins', color: '#ff6b35', statKey: 'flowsint' },
      { key: 'osint', label: 'OSINT Pins', statKey: 'osint' },
      { key: 'darkweb', label: 'Dark Web', statKey: 'darkweb' },
      {
        key: 'detectionBoxes',
        label: 'Detection Boxes',
        color: '#FACC15',
        statKey: 'detectionBoxes',
      },
      { key: 'geopolitics', label: 'Geopolitics', statKey: 'geopolitics' },
      { key: 'satelliteChange', label: 'Sat Change' },
      { key: 'cii', label: 'Instability Index', color: '#ff4d5e', statKey: 'cii' },
    ],
  },
  {
    group: 'Disasters & Events',
    layers: [
      { key: 'gdacs', label: 'GDACS Alerts', feedKey: 'gdacs', statKey: 'gdacs' },
      { key: 'events', label: 'GDELT Events', feedKey: 'gdelt', statKey: 'events' },
      { key: 'nodes', label: 'Node Sync', statKey: 'nodes' },
      { key: 'orbits', label: 'Orbits' },
      { key: 'trafficCams', label: 'Traffic Cams', statKey: 'trafficCams' },
    ],
  },
];

/* ── Helpers ──────────────────────────────────────────────────────────────── */

function statusColor(feed?: FeedHealthInfo): string {
  if (!feed) return 'var(--txt-dim)';
  if (feed.status === 'error') return '#ff4d5e';
  if (feed.fresh === false || feed.status === 'stale') return '#ffd23f';
  return 'var(--accent)';
}

function statusLabel(feed?: FeedHealthInfo): string {
  if (!feed) return 'no feed';
  if (feed.status === 'error') return 'error';
  if (feed.fresh === false || feed.status === 'stale') return 'stale';
  return 'fresh';
}

/* ── Component ─────────────────────────────────────────────────────────────── */

export interface LayerTreeProps {
  layers: Record<string, boolean>;
  onToggleLayer: (key: string) => void;
  /** Optional stats from Globe (item counts) */
  stats?: Record<string, number>;
}

export default function LayerTree({ layers, onToggleLayer, stats }: LayerTreeProps) {
  const treeId = useId();
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({});
  const [feedHealth, setFeedHealth] = useState<Record<string, FeedHealthInfo>>({});
  const itemRefs = useRef<Map<string, HTMLDivElement>>(new Map());

  /* Fetch feed health */
  const loadHealth = useCallback(async () => {
    try {
      const r = await fetchApi('/api/health');
      if (!r.ok) return;
      const d = await r.json();
      if (d?.feeds) setFeedHealth(d.feeds as Record<string, FeedHealthInfo>);
    } catch {
      /* fail-soft */
    }
  }, []);

  useEffect(() => {
    loadHealth();
    const t = setInterval(loadHealth, 60_000);
    return () => clearInterval(t);
  }, [loadHealth]);

  const toggleGroup = useCallback((group: string) => {
    setCollapsedGroups((prev) => ({ ...prev, [group]: !prev[group] }));
  }, []);

  /* Select All / Deselect All for a group */
  const setGroupAll = useCallback(
    (grp: LayerGroup, on: boolean) => {
      grp.layers.forEach((lyr) => {
        const current = layers[lyr.key] ?? false;
        if (on && !current) onToggleLayer(lyr.key);
        if (!on && current) onToggleLayer(lyr.key);
      });
    },
    [layers, onToggleLayer],
  );

  /* Flatten visible items for arrow-key navigation */
  const flatItems = useMemo(() => {
    const items: { group: string; layerKey: string }[] = [];
    for (const grp of LAYER_GROUPS) {
      if (collapsedGroups[grp.group]) continue;
      for (const lyr of grp.layers) {
        items.push({ group: grp.group, layerKey: lyr.key });
      }
    }
    return items;
  }, [collapsedGroups]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent, layerKey: string) => {
      const idx = flatItems.findIndex((it) => it.layerKey === layerKey);
      if (idx === -1) return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        const next = flatItems[idx + 1];
        if (next) itemRefs.current.get(next.layerKey)?.focus();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        const prev = flatItems[idx - 1];
        if (prev) itemRefs.current.get(prev.layerKey)?.focus();
      } else if (e.key === ' ' || e.key === 'Enter') {
        e.preventDefault();
        onToggleLayer(layerKey);
      }
    },
    [flatItems, onToggleLayer],
  );

  return (
    <div className="layer-tree" role="tree" aria-label="Globe layers" id={treeId}>
      {LAYER_GROUPS.map((grp) => {
        const isCollapsed = collapsedGroups[grp.group] ?? false;
        const activeCount = grp.layers.filter((l) => layers[l.key] ?? false).length;
        const allOn = activeCount === grp.layers.length;

        return (
          <div key={grp.group} className="layer-tree-group" role="group" aria-label={grp.group}>
            <div
              className="layer-tree-group-header"
              role="treeitem"
              aria-expanded={!isCollapsed}
              tabIndex={0}
              onClick={() => toggleGroup(grp.group)}
              onKeyDown={(e) => {
                if (e.key === ' ' || e.key === 'Enter') {
                  e.preventDefault();
                  toggleGroup(grp.group);
                }
              }}
            >
              <span
                className={`layer-tree-chevron${isCollapsed ? ' layer-tree-chevron--collapsed' : ''}`}
              >
                ▾
              </span>
              <span className="layer-tree-group-label">{grp.group}</span>
              <span className="layer-tree-group-count">
                {activeCount}/{grp.layers.length}
              </span>
              <button
                className="layer-tree-bulk-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  setGroupAll(grp, !allOn);
                }}
                title={allOn ? 'Deselect all' : 'Select all'}
                aria-label={allOn ? `Deselect all in ${grp.group}` : `Select all in ${grp.group}`}
              >
                {allOn ? '◐' : '○'}
              </button>
            </div>

            {!isCollapsed && (
              <div className="layer-tree-items">
                {grp.layers.map((lyr) => {
                  const on = layers[lyr.key] ?? false;
                  const feed = lyr.feedKey ? feedHealth[lyr.feedKey] : undefined;
                  const count = stats?.[lyr.statKey ?? ''];
                  const dotColor = on ? statusColor(feed) : 'var(--txt-dim)';
                  const dotOpacity = on ? 1 : 0.3;

                  return (
                    <div
                      key={lyr.key}
                      ref={(el) => {
                        if (el) itemRefs.current.set(lyr.key, el);
                        else itemRefs.current.delete(lyr.key);
                      }}
                      role="treeitem"
                      aria-selected={on}
                      aria-label={lyr.label}
                      tabIndex={on ? 0 : -1}
                      className={`layer-tree-item${on ? ' layer-tree-item--on' : ''}`}
                      onClick={() => onToggleLayer(lyr.key)}
                      onKeyDown={(e) => handleKeyDown(e, lyr.key)}
                    >
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={() => onToggleLayer(lyr.key)}
                        onClick={(e) => e.stopPropagation()}
                        aria-label={lyr.label}
                        className="layer-tree-checkbox"
                      />
                      <span
                        className="layer-tree-dot"
                        style={{ background: lyr.color || dotColor, opacity: dotOpacity }}
                        title={feed ? statusLabel(feed) : undefined}
                      />
                      <span className="layer-tree-label">{lyr.label}</span>
                      {count != null && count > 0 && (
                        <span className="layer-tree-badge">{count}</span>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
