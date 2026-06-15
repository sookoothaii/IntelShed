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

export default function SituationBoard({ onClose, onFocus, osintPins, onAddPin, onAskAI }: Props) {
  const [items, setItems] = useState<SituationItem[]>([])
  const [loading, setLoading] = useState(true)
  const [entityCtx, setEntityCtx] = useState<Record<string, unknown> | null>(null)
  const [entityLoading, setEntityLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = async () => {
      setLoading(true)
      try {
        const r = await fetchApi('/api/situations')
        const d = await r.json()
        if (!cancelled) setItems(d.items || [])
      } catch {
        if (!cancelled) setItems([])
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
