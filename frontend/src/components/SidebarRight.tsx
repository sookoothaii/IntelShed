import { useCallback, useEffect, useState } from 'react'
import { fetchApi } from '../lib/networkFetch'
import { useBriefingQuery } from '../hooks/useSharedFeeds'
import ActionBar from './ActionBar'

/* ── Types ────────────────────────────────────────────────────────────────── */

interface WatchItem {
  id?: string
  horizon_h?: number
  title?: string
  confidence?: number
  sources?: string[]
  bucket?: string
  lat?: number
  lon?: number
}

interface BriefingData {
  text?: string
  quality?: { score?: number }
  watch_items?: WatchItem[]
  insights?: { title?: string; summary?: string; severity?: string }[]
  created_at?: string
}

/* ── Component ─────────────────────────────────────────────────────────────── */

export default function SidebarRight({
  collapsed,
  onToggleCollapse,
  onFocus,
}: {
  collapsed: boolean
  onToggleCollapse: () => void
  onFocus?: (lat: number, lon: number, title: string) => void
}) {
  const { data: briefing } = useBriefingQuery()
  const [trustScore, setTrustScore] = useState<number | null>(null)

  const loadTrust = useCallback(async () => {
    try {
      const r = await fetchApi('/api/trust')
      if (r.ok) {
        const d = await r.json()
        setTrustScore(d?.score ?? d?.overall ?? null)
      }
    } catch { /* fail-soft */ }
  }, [])

  useEffect(() => {
    loadTrust()
    const t = setInterval(loadTrust, 60_000)
    return () => clearInterval(t)
  }, [loadTrust])

  const b = briefing as BriefingData | undefined
  const watchItems = b?.watch_items ?? []
  const insights = b?.insights ?? []
  const qualityScore = b?.quality?.score
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null)
  const selectedInsight = selectedIdx != null ? insights[selectedIdx] : null

  if (collapsed) {
    return (
      <aside className="hud-sidebar hud-sidebar--right hud-sidebar--collapsed">
        <button className="sidebar-expand-btn" onClick={onToggleCollapse} title="Expand right sidebar">
          ◂
        </button>
      </aside>
    )
  }

  return (
    <aside className="hud-sidebar hud-sidebar--right">
      <div className="sidebar-header">
        <span className="sidebar-title">BRIEFING &amp; TRUST</span>
        <button className="sidebar-collapse-btn" onClick={onToggleCollapse} title="Collapse">
          ▸
        </button>
      </div>

      {/* Trust score */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">TRUST SCORE</div>
        <div className="sidebar-trust-gauge">
          <div className="sidebar-trust-value">
            {trustScore != null ? `${Math.round(trustScore * 100)}%` : '—'}
          </div>
          <div className="sidebar-trust-bar">
            <div
              className="sidebar-trust-fill"
              style={{ width: `${trustScore != null ? Math.round(trustScore * 100) : 0}%` }}
            />
          </div>
        </div>
        {qualityScore != null && (
          <div className="sidebar-meta-row">
            <span>Briefing quality</span>
            <strong>{(qualityScore * 100).toFixed(0)}%</strong>
          </div>
        )}
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
                    onFocus(w.lat, w.lon, w.title || 'Watch item')
                  }
                }}
                style={{ cursor: onFocus && w.lat != null ? 'pointer' : 'default' }}
              >
                <span className="sidebar-watch-horizon">{w.horizon_h ?? '—'}h</span>
                <span className="sidebar-watch-title">{w.title || 'Untitled'}</span>
                {w.confidence != null && (
                  <span className="sidebar-watch-conf">
                    {(w.confidence * 100).toFixed(0)}%
                  </span>
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
                {ins.summary && (
                  <div className="sidebar-insight-summary">{ins.summary}</div>
                )}
                {ins.severity && (
                  <span className={`sidebar-insight-severity sidebar-insight-severity--${ins.severity}`}>
                    {ins.severity.toUpperCase()}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

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
  )
}
