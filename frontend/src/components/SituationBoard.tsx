import { useEffect, useState } from 'react'
import type { FocusTarget } from '../lib/focus'
import type { OsintPin } from '../lib/osintPins'
import { fetchApi } from '../lib/networkFetch';

export type SituationItem = {
  id: string
  entity_id?: string
  category: string
  severity: string
  type: string
  title: string
  source: string
  location?: { lat: number; lon: number; place?: string } | null
  details?: Record<string, unknown>
}

type Props = {
  onClose: () => void
  onFocus: (f: Omit<FocusTarget, 'ts'>) => void
  osintPins: OsintPin[]
  onAddPin: (pin: Omit<OsintPin, 'ts'>) => void
  onAskAI: (title: string, lines: string[]) => void
}

function sevClass(sev: string): string {
  if (sev === 'critical' || sev === 'high') return 'sit-sev-high'
  if (sev === 'medium' || sev === 'warn') return 'sit-sev-med'
  return 'sit-sev-low'
}

type FusionHotspot = {
  lat?: number
  lon?: number
  label?: string
  summary?: string
  score?: number
}

type InsightEntity = { id?: string; name?: string; schema?: string }

type InsightCard = {
  id: string
  rank?: number
  headline: string
  so_what: string
  center?: { lat?: number; lon?: number; place?: string }
  score?: number
  delta_score?: number
  rising?: boolean
  sources?: string[]
  entities?: InsightEntity[]
  confidence?: number
  confidence_basis?: string
  narrative_source?: string
}

export default function SituationBoard({ onClose, onFocus, osintPins, onAddPin, onAskAI }: Props) {
  const [items, setItems] = useState<SituationItem[]>([])
  const [fusionHotspots, setFusionHotspots] = useState<FusionHotspot[]>([])
  const [insights, setInsights] = useState<InsightCard[]>([])
  const [loading, setLoading] = useState(true)
  const [entityCtx, setEntityCtx] = useState<Record<string, unknown> | null>(null)
  const [entityLoading, setEntityLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      try {
        const [sitRes, briefRes, insRes] = await Promise.all([
          fetchApi('/api/situations'),
          fetchApi('/api/briefing'),
          fetchApi('/api/insights?top=10'),
        ])
        if (!cancelled) {
          if (sitRes.ok) {
            const d = await sitRes.json()
            setItems(d.items || [])
          } else {
            setItems([])
          }
          if (briefRes.ok) {
            const b = await briefRes.json()
            setFusionHotspots(b.fusion_hotspots || [])
          } else {
            setFusionHotspots([])
          }
          if (insRes.ok) {
            const ins = await insRes.json()
            setInsights(ins.insights || [])
          } else {
            setInsights([])
          }
        }
      } catch {
        if (!cancelled) {
          setItems([])
          setFusionHotspots([])
          setInsights([])
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    const t = setInterval(load, 60000)
    return () => { cancelled = true; clearInterval(t) }
  }, [])

  const pinItems: SituationItem[] = osintPins.map((p) => ({
    id: `pin:${p.id}`,
    entity_id: p.entityId,
    category: 'osint',
    severity: 'medium',
    type: p.pinType || p.tool,
    title: p.title,
    source: 'osint_pin',
    location: { lat: p.lat, lon: p.lon, place: p.query },
    details: { lines: p.lines, investigationId: p.investigationId },
  }))

  const all = [...items, ...pinItems].sort((a, b) => {
    const order: Record<string, number> = { critical: 0, high: 1, medium: 2, warn: 3, low: 4 }
    return (order[a.severity] ?? 3) - (order[b.severity] ?? 3)
  })

  const focusItem = (it: SituationItem) => {
    const loc = it.location
    if (!loc?.lat || loc.lon == null) return
    const lines = [
      `Source: ${it.source}`,
      `Type: ${it.type}`,
      `Severity: ${it.severity}`,
      ...(it.entity_id ? [`Entity: ${it.entity_id}`] : []),
    ]
    onFocus({
      kind: it.category,
      lat: loc.lat,
      lon: loc.lon,
      height: 400000,
      title: it.title,
      lines,
    })
  }

  const addToInvestigation = (it: SituationItem) => {
    const loc = it.location
    if (!loc?.lat || loc.lon == null) return
    onAddPin({
      id: it.id,
      tool: 'situation',
      query: it.id,
      lat: loc.lat,
      lon: loc.lon,
      title: it.title,
      lines: [`Source: ${it.source}`, `Type: ${it.type}`],
      pinType: it.type,
      entityId: it.entity_id,
    })
  }

  const loadEntity = async (entityId: string) => {
    setEntityLoading(true)
    try {
      const r = await fetchApi(`/api/entity/${encodeURIComponent(entityId)}/context`)
      setEntityCtx(await r.json())
    } catch {
      setEntityCtx({ error: 'load failed' })
    } finally {
      setEntityLoading(false)
    }
  }

  return (
    <div className="situation-overlay" role="dialog" aria-label="Situation board">
      <div className="situation-panel">
        <header className="situation-header">
          <h2>Unified Situation Board</h2>
          <span className="situation-count">{all.length} items</span>
          <button type="button" className="situation-close" onClick={onClose}>✕</button>
        </header>

        {loading && (
          <div className="situation-loading">
            Loading feeds… (correlations, GDACS, pegel — ~5–15 s first load)
          </div>
        )}

        <div className="situation-body">
          {insights.length > 0 && (
            <div className="situation-insights-block">
              <h3>INSIGHTS ({insights.length})</h3>
              {insights.map((ins) => {
                const conf = Math.round((ins.confidence ?? 0) * 100)
                const topEntity = (ins.entities || []).find((e) => e.id)
                return (
                  <div key={ins.id} className="insight-card">
                    <div className="insight-card-head">
                      <span className="insight-rank">#{ins.rank}</span>
                      {ins.rising && (
                        <span className="insight-rising" title="Rising vs 24h">
                          ▲ Δ{Number(ins.delta_score ?? 0).toFixed(2)}
                        </span>
                      )}
                      <span className="insight-headline">{ins.headline}</span>
                      {ins.narrative_source === 'ollama' && (
                        <span className="insight-ai-badge" title="LLM narrative (qwen3)">AI</span>
                      )}
                    </div>
                    <div className="insight-sowhat">{ins.so_what}</div>
                    <div className="insight-confbar" title={ins.confidence_basis || ''}>
                      <span className="insight-confbar-fill" style={{ width: `${conf}%` }} />
                      <span className="insight-conf-label">{conf}%</span>
                    </div>
                    <div className="insight-chips">
                      {(ins.sources || []).slice(0, 4).map((s) => (
                        <span key={s} className="insight-chip">{s}</span>
                      ))}
                      {(ins.entities || []).slice(0, 2).map((e) => (
                        <span key={e.id || e.name} className="insight-chip insight-chip-entity">
                          {e.name}
                        </span>
                      ))}
                    </div>
                    <div className="situation-actions">
                      {ins.center?.lat != null && ins.center?.lon != null && (
                        <button
                          type="button"
                          className="locate-mini"
                          onClick={() => {
                            onClose()
                            onFocus({
                              kind: 'fusion',
                              lat: ins.center!.lat!,
                              lon: ins.center!.lon!,
                              height: 700000,
                              title: ins.headline,
                              lines: [ins.so_what, `Confidence: ${conf}%`],
                            })
                          }}
                        >
                          ◎ Globe
                        </button>
                      )}
                      {topEntity?.id && (
                        <button type="button" className="locate-mini" onClick={() => loadEntity(topEntity.id!)}>
                          ⎔ Context
                        </button>
                      )}
                      <button
                        type="button"
                        className="locate-mini"
                        onClick={() => onAskAI(ins.headline, [ins.so_what, `Sources: ${(ins.sources || []).join(', ')}`])}
                      >
                        ✦ AI
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          {fusionHotspots.length > 0 && (
            <div className="situation-fusion-block">
              <h3>FUSION HOTSPOTS ({fusionHotspots.length})</h3>
              {fusionHotspots.slice(0, 3).map((h, i) => (
                <div key={i} className="situation-fusion-row">
                  <span className="situation-fusion-rank">#{i + 1}</span>
                  <span className="situation-fusion-label">
                    {h.label || h.summary || `${h.lat?.toFixed(1) ?? '—'}, ${h.lon?.toFixed(1) ?? '—'}`}
                  </span>
                  {h.score != null && (
                    <span className="situation-fusion-score">score {Number(h.score).toFixed(1)}</span>
                  )}
                  {h.lat != null && h.lon != null && (
                    <button
                      type="button"
                      className="locate-mini"
                      onClick={() => {
                        onClose()
                        onFocus({
                          kind: 'fusion',
                          lon: h.lon!,
                          lat: h.lat!,
                          height: 800000,
                          title: h.label || `Fusion hotspot ${i + 1}`,
                          lines: [`Score: ${h.score ?? '—'}`, h.summary].filter(Boolean) as string[],
                        })
                      }}
                    >
                      ◎
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}

          <ul className="situation-list">
            {all.map((it) => (
              <li key={it.id} className={`situation-row ${sevClass(it.severity)}`}>
                <div className="situation-meta">
                  <span className="situation-cat">{it.category}</span>
                  <span className="situation-sev">{it.severity}</span>
                </div>
                <div className="situation-title">{it.title}</div>
                <div className="situation-src">{it.source}</div>
                <div className="situation-actions">
                  {it.location?.lat != null && (
                    <>
                      <button type="button" className="locate-mini" onClick={() => focusItem(it)}>◎ Globe</button>
                      <button type="button" className="locate-mini" onClick={() => addToInvestigation(it)}>+ Pin</button>
                    </>
                  )}
                  {it.entity_id && (
                    <button type="button" className="locate-mini" onClick={() => loadEntity(it.entity_id!)}>⎔ Context</button>
                  )}
                  <button
                    type="button"
                    className="locate-mini"
                    onClick={() => onAskAI(it.title, [`Source: ${it.source}`, `Type: ${it.type}`])}
                  >
                    ✦ AI
                  </button>
                </div>
              </li>
            ))}
            {!loading && all.length === 0 && (
              <li className="situation-empty">No active situations — feeds are quiet.</li>
            )}
          </ul>

          {(entityCtx || entityLoading) && (
            <aside className="situation-entity-panel">
              <h3>Entity context</h3>
              {entityLoading && <div className="situation-loading">Loading…</div>}
              {!entityLoading && entityCtx && (
                <pre className="situation-entity-json">{JSON.stringify(entityCtx, null, 2)}</pre>
              )}
              <button type="button" className="locate-mini" onClick={() => setEntityCtx(null)}>Close</button>
            </aside>
          )}
        </div>
      </div>
    </div>
  )
}
