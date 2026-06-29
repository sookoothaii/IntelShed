import { useCallback, useEffect, useState } from 'react'
import { fetchApi } from '../lib/networkFetch'

/* ── Types ────────────────────────────────────────────────────────────────── */

type HealthResponse = {
  status?: string
  feeds_fresh?: number
  feeds_stale?: number
  feed_count?: number | string
  feeds?: Record<string, Record<string, unknown>>
  ftm?: { ready?: boolean; entities?: number | string }
  [key: string]: unknown
}

type FeedRow = {
  key: string
  status?: string
  fresh?: boolean
  age_sec?: number
  count?: number | null
  error?: string | null
}

type LayerDef = {
  key: string
  label: string
  color?: string
}

const LAYER_GROUPS: { group: string; layers: LayerDef[] }[] = [
  {
    group: 'LIVE TRACKING',
    layers: [
      { key: 'aircraft', label: 'Aircraft', color: '#ffd23f' },
      { key: 'satellites', label: 'Satellites', color: '#00e5ff' },
      { key: 'military', label: 'Military', color: '#ff6b35' },
      { key: 'maritime', label: 'Maritime', color: '#00e5ff' },
      { key: 'transit', label: 'Transit', color: '#ffd23f' },
    ],
  },
  {
    group: 'GEO HAZARDS',
    layers: [
      { key: 'quakes', label: 'Earthquakes' },
      { key: 'wildfires', label: 'Wildfires' },
      { key: 'volcanoes', label: 'Volcanoes' },
      { key: 'lightning', label: 'Lightning' },
      { key: 'hazards', label: 'Hazards' },
      { key: 'outages', label: 'Outages' },
    ],
  },
  {
    group: 'ENVIRONMENT',
    layers: [
      { key: 'weather', label: 'Weather' },
      { key: 'airquality', label: 'Air Quality' },
      { key: 'pegel', label: 'Water Levels' },
      { key: 'energy', label: 'Energy' },
      { key: 'spaceweather', label: 'Space Weather' },
    ],
  },
  {
    group: 'INTELLIGENCE',
    layers: [
      { key: 'intelFt', label: 'Intel Entities', color: '#c084fc' },
      { key: 'osint', label: 'OSINT Pins' },
      { key: 'darkweb', label: 'Dark Web' },
      { key: 'detectionBoxes', label: 'Detection Boxes', color: '#FACC15' },
      { key: 'geopolitics', label: 'Geopolitics' },
      { key: 'satelliteChange', label: 'Sat Change' },
    ],
  },
  {
    group: 'SYSTEM',
    layers: [
      { key: 'events', label: 'Events' },
      { key: 'nodes', label: 'Node Sync' },
      { key: 'gdacs', label: 'GDACS' },
      { key: 'orbits', label: 'Orbits' },
      { key: 'trafficCams', label: 'Traffic Cams' },
    ],
  },
]

/* ── Component ─────────────────────────────────────────────────────────────── */

export default function SidebarLeft({
  layers,
  onToggleLayer,
  collapsed,
  onToggleCollapse,
}: {
  layers: Record<string, boolean>
  onToggleLayer: (k: string) => void
  collapsed: boolean
  onToggleCollapse: () => void
}) {
  const [health, setHealth] = useState<HealthResponse | null>(null)

  const loadHealth = useCallback(async () => {
    try {
      const r = await fetchApi('/api/health')
      if (r.ok) setHealth(await r.json())
    } catch { /* fail-soft */ }
  }, [])

  useEffect(() => {
    loadHealth()
    const t = setInterval(loadHealth, 60_000)
    return () => clearInterval(t)
  }, [loadHealth])

  const feeds: FeedRow[] = health?.feeds
    ? Object.entries(health.feeds).map(([key, val]) => ({ key, ...val }))
    : []
  const freshCount = feeds.filter((f) => f.fresh !== false && f.status !== 'stale' && f.status !== 'error').length
  const staleCount = feeds.filter((f) => f.fresh === false || f.status === 'stale').length
  const errorCount = feeds.filter((f) => f.status === 'error').length

  if (collapsed) {
    return (
      <aside className="hud-sidebar hud-sidebar--left hud-sidebar--collapsed">
        <button className="sidebar-expand-btn" onClick={onToggleCollapse} title="Expand left sidebar">
          ▸
        </button>
      </aside>
    )
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
        {LAYER_GROUPS.map((grp) => (
          <div key={grp.group} className="sidebar-layer-group">
            <div className="sidebar-layer-group-label">{grp.group}</div>
            {grp.layers.map((lyr) => {
              const on = layers[lyr.key] ?? false
              return (
                <label key={lyr.key} className={`sidebar-layer-row ${on ? 'on' : ''}`}>
                  <input
                    type="checkbox"
                    checked={on}
                    onChange={() => onToggleLayer(lyr.key)}
                  />
                  <span
                    className="sidebar-layer-dot"
                    style={{ background: lyr.color || 'var(--accent-dim)' }}
                  />
                  {lyr.label}
                </label>
              )
            })}
          </div>
        ))}
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
                    f.status === 'error' ? '#ff4d5e'
                    : f.fresh === false || f.status === 'stale' ? '#ffd23f'
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
  )
}
