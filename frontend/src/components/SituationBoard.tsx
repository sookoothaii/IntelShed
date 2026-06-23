import { useEffect, useMemo, useRef, useState } from 'react'
import type { FocusTarget } from '../lib/focus'
import type { OsintPin } from '../lib/osintPins'
import { fetchApi } from '../lib/networkFetch'
import { useSituationsQuery, useBriefingQuery, useInsightsQuery } from '../hooks/useSharedFeeds'

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
  onOpenIntel: (entityId: string) => void
}

type SevBucket = 'crit' | 'high' | 'med' | 'low'
type SortMode = 'severity' | 'newest' | 'score'

const SEV_BUCKETS: { key: SevBucket; label: string }[] = [
  { key: 'crit', label: 'CRIT' },
  { key: 'high', label: 'HIGH' },
  { key: 'med', label: 'MED' },
  { key: 'low', label: 'LOW' },
]

const SEV_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, warn: 2, low: 3 }

function sevBucket(sev: string): SevBucket {
  if (sev === 'critical') return 'crit'
  if (sev === 'high') return 'high'
  if (sev === 'medium' || sev === 'warn') return 'med'
  return 'low'
}

function sevClass(sev: string): string {
  if (sev === 'critical' || sev === 'high') return 'sit-sev-high'
  if (sev === 'medium' || sev === 'warn') return 'sit-sev-med'
  return 'sit-sev-low'
}

function itemTimestamp(it: SituationItem): number {
  const d = it.details || {}
  const cand = d.published ?? d.time ?? d.date ?? d.updated_at ?? d.ts ?? d.observed_at
  if (cand == null) return 0
  if (typeof cand === 'number') return cand > 1e12 ? cand : cand * 1000
  const t = Date.parse(String(cand))
  return Number.isFinite(t) ? t : 0
}

function itemScore(it: SituationItem): number {
  const d = it.details || {}
  const raw = d.score ?? d.magnitude ?? d.mag ?? d.delta_score
  const n = Number(raw)
  if (Number.isFinite(n)) return n
  return 3 - (SEV_ORDER[it.severity] ?? 3)
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

type EntityContext = {
  error?: string
  entity?: {
    id?: string
    type?: string
    label?: string
    lat?: number | null
    lon?: number | null
    source_feed?: string
    external_id?: string
    meta?: Record<string, unknown>
    updated_at?: string
  }
  links?: Array<{ from_id: string; to_id: string; relation: string; meta?: Record<string, unknown> }>
  related?: Array<{ id?: string; label?: string; type?: string }>
}

function fmtTime(ms: number | undefined): string {
  if (!ms) return '—'
  try {
    return new Date(ms).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return '—'
  }
}

export default function SituationBoard({ onClose, onFocus, osintPins, onAddPin, onAskAI, onOpenIntel }: Props) {
  const [paused, setPaused] = useState(false)
  const interval = paused ? (false as const) : 60_000
  const sitQ = useSituationsQuery({ refetchInterval: interval })
  const briefQ = useBriefingQuery({ refetchInterval: interval })
  const insQ = useInsightsQuery(10, { refetchInterval: interval })

  const items: SituationItem[] = sitQ.data?.items || []
  const fusionHotspots: FusionHotspot[] = briefQ.data?.fusion_hotspots || []
  const insights: InsightCard[] = insQ.data?.insights || []
  const loading = sitQ.isLoading || briefQ.isLoading || insQ.isLoading
  const updatedAt = Math.max(sitQ.dataUpdatedAt || 0, briefQ.dataUpdatedAt || 0, insQ.dataUpdatedAt || 0)

  const [entityCtx, setEntityCtx] = useState<EntityContext | null>(null)
  const [entityLoading, setEntityLoading] = useState(false)
  const [sevFilter, setSevFilter] = useState<Set<SevBucket>>(new Set())
  const [catFilter, setCatFilter] = useState<Set<string>>(new Set())
  const [srcFilter, setSrcFilter] = useState<Set<string>>(new Set())
  const [sort, setSort] = useState<SortMode>('severity')
  const [rawQuery, setRawQuery] = useState('')
  const [query, setQuery] = useState('')
  const [showAllFusion, setShowAllFusion] = useState(false)
  const [copied, setCopied] = useState<string | null>(null)

  const panelRef = useRef<HTMLDivElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)

  // Debounce free-text search (A2).
  useEffect(() => {
    const t = setTimeout(() => setQuery(rawQuery.trim().toLowerCase()), 200)
    return () => clearTimeout(t)
  }, [rawQuery])

  // A6: Escape closes, focus trap, initial focus.
  useEffect(() => {
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
        return
      }
      if (e.key !== 'Tab' || !panelRef.current) return
      const focusable = panelRef.current.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      )
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

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

  const all = useMemo(() => [...items, ...pinItems], [items, pinItems])

  const sevCounts = useMemo(() => {
    const c: Record<SevBucket, number> = { crit: 0, high: 0, med: 0, low: 0 }
    for (const it of all) c[sevBucket(it.severity)] += 1
    return c
  }, [all])

  const categories = useMemo(
    () => Array.from(new Set(all.map((i) => i.category))).sort(),
    [all],
  )
  const sources = useMemo(
    () => Array.from(new Set(all.map((i) => i.source))).sort(),
    [all],
  )

  const filtered = useMemo(() => {
    const out = all.filter((it) => {
      if (sevFilter.size > 0 && !sevFilter.has(sevBucket(it.severity))) return false
      if (catFilter.size > 0 && !catFilter.has(it.category)) return false
      if (srcFilter.size > 0 && !srcFilter.has(it.source)) return false
      if (query) {
        const hay = `${it.title} ${it.source} ${it.type} ${it.category}`.toLowerCase()
        if (!hay.includes(query)) return false
      }
      return true
    })
    out.sort((a, b) => {
      if (sort === 'newest') return itemTimestamp(b) - itemTimestamp(a)
      if (sort === 'score') return itemScore(b) - itemScore(a)
      return (SEV_ORDER[a.severity] ?? 3) - (SEV_ORDER[b.severity] ?? 3)
    })
    return out
  }, [all, sevFilter, catFilter, srcFilter, query, sort])

  const toggle = <T,>(set: Set<T>, value: T, setter: (s: Set<T>) => void) => {
    const next = new Set(set)
    if (next.has(value)) next.delete(value)
    else next.add(value)
    setter(next)
  }

  const focusItem = (it: SituationItem) => {
    const loc = it.location
    if (!loc?.lat || loc.lon == null) return
    const lines = [
      `Source: ${it.source}`,
      `Type: ${it.type}`,
      `Severity: ${it.severity}`,
      ...(it.entity_id ? [`Entity: ${it.entity_id}`] : []),
    ]
    onFocus({ kind: it.category, lat: loc.lat, lon: loc.lon, height: 400000, title: it.title, lines })
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

  const copyView = async (kind: 'json' | 'markdown') => {
    let text: string
    if (kind === 'json') {
      text = JSON.stringify(filtered, null, 2)
    } else {
      const lines = filtered.map((it) => {
        const loc = it.location
        const coords = loc?.lat != null && loc?.lon != null ? ` (${loc.lat.toFixed(3)}, ${loc.lon.toFixed(3)})` : ''
        return `- [${it.severity.toUpperCase()}] ${it.title} — ${it.source}${coords}`
      })
      text = `# SITUATIONS (${filtered.length})\n\n${lines.join('\n')}\n`
    }
    try {
      await navigator.clipboard.writeText(text)
      setCopied(kind)
      setTimeout(() => setCopied(null), 1500)
    } catch {
      setCopied('error')
      setTimeout(() => setCopied(null), 1500)
    }
  }

  const visibleFusion = showAllFusion ? fusionHotspots : fusionHotspots.slice(0, 3)

  return (
    <div className="situation-overlay" onClick={onClose}>
      <div
        className="situation-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Unified situation board"
        ref={panelRef}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="situation-header">
          <h2>Unified Situation Board</h2>
          <span className="situation-count">{filtered.length}/{all.length} items</span>
          <span className="situation-updated" role="status" aria-live="polite">
            {loading ? 'Updating…' : `Updated ${fmtTime(updatedAt)}`}
          </span>
          <button
            type="button"
            className={`situation-pause${paused ? ' on' : ''}`}
            aria-pressed={paused}
            aria-label={paused ? 'Resume auto-refresh' : 'Pause auto-refresh'}
            title={paused ? 'Resume 60s auto-refresh' : 'Pause auto-refresh while reading'}
            onClick={() => setPaused((p) => !p)}
          >
            {paused ? '▶ RESUME' : '⏸ PAUSE'}
          </button>
          <button type="button" className="situation-close" aria-label="Close board" ref={closeRef} onClick={onClose}>✕</button>
        </header>

        <div className="situation-toolbar">
          <div className="situation-sevqueue" role="group" aria-label="Severity filter">
            {SEV_BUCKETS.map((b) => (
              <button
                key={b.key}
                type="button"
                className={`sit-sevpill sit-sevpill--${b.key}${sevFilter.has(b.key) ? ' on' : ''}`}
                aria-pressed={sevFilter.has(b.key)}
                onClick={() => toggle(sevFilter, b.key, setSevFilter)}
              >
                {b.label} <strong>{sevCounts[b.key]}</strong>
              </button>
            ))}
          </div>

          <div className="situation-search">
            <input
              type="search"
              placeholder="Search title / source / type…"
              value={rawQuery}
              aria-label="Search situations"
              onChange={(e) => setRawQuery(e.target.value)}
            />
          </div>

          <div className="situation-sort" role="group" aria-label="Sort order">
            {(['severity', 'newest', 'score'] as SortMode[]).map((m) => (
              <button
                key={m}
                type="button"
                className={sort === m ? 'on' : ''}
                aria-pressed={sort === m}
                onClick={() => setSort(m)}
              >
                {m.toUpperCase()}
              </button>
            ))}
          </div>

          <div className="situation-export">
            <button type="button" onClick={() => copyView('json')} aria-label="Copy filtered view as JSON">
              {copied === 'json' ? '✓ JSON' : 'COPY JSON'}
            </button>
            <button type="button" onClick={() => copyView('markdown')} aria-label="Copy filtered view as Markdown">
              {copied === 'markdown' ? '✓ MD' : 'COPY MD'}
            </button>
          </div>
        </div>

        {(categories.length > 1 || sources.length > 1) && (
          <div className="situation-chips-row">
            {categories.length > 1 && (
              <div className="situation-chips" role="group" aria-label="Category filter">
                <span className="situation-chips-label">CAT</span>
                {categories.map((c) => (
                  <button
                    key={c}
                    type="button"
                    className={`sit-chip${catFilter.has(c) ? ' on' : ''}`}
                    aria-pressed={catFilter.has(c)}
                    onClick={() => toggle(catFilter, c, setCatFilter)}
                  >
                    {c}
                  </button>
                ))}
              </div>
            )}
            {sources.length > 1 && (
              <div className="situation-chips" role="group" aria-label="Source filter">
                <span className="situation-chips-label">SRC</span>
                {sources.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className={`sit-chip${srcFilter.has(s) ? ' on' : ''}`}
                    aria-pressed={srcFilter.has(s)}
                    onClick={() => toggle(srcFilter, s, setSrcFilter)}
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {loading && all.length === 0 && (
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
                          aria-label="Fly to insight on globe"
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
                        <>
                          <button type="button" className="locate-mini" aria-label="Show entity context" onClick={() => loadEntity(topEntity.id!)}>
                            ⎔ Context
                          </button>
                          <button type="button" className="locate-mini" aria-label="Open entity in INTEL graph" onClick={() => onOpenIntel(topEntity.id!)}>
                            ⌖ INTEL
                          </button>
                        </>
                      )}
                      <button
                        type="button"
                        className="locate-mini"
                        aria-label="Ask AI about this insight"
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
              {visibleFusion.map((h, i) => (
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
                      aria-label={`Fly to fusion hotspot ${i + 1}`}
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
              {fusionHotspots.length > 3 && (
                <button
                  type="button"
                  className="situation-fusion-toggle"
                  aria-expanded={showAllFusion}
                  onClick={() => setShowAllFusion((v) => !v)}
                >
                  {showAllFusion ? 'Show top 3' : `Show all (${fusionHotspots.length})`}
                </button>
              )}
            </div>
          )}

          <ul className="situation-list">
            {filtered.map((it) => (
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
                      <button type="button" className="locate-mini" aria-label="Fly to item on globe" onClick={() => focusItem(it)}>◎ Globe</button>
                      <button type="button" className="locate-mini" aria-label="Add item to investigation" onClick={() => addToInvestigation(it)}>+ Pin</button>
                    </>
                  )}
                  {it.entity_id && (
                    <>
                      <button type="button" className="locate-mini" aria-label="Show entity context" onClick={() => loadEntity(it.entity_id!)}>⎔ Context</button>
                      <button type="button" className="locate-mini" aria-label="Open entity in INTEL graph" onClick={() => onOpenIntel(it.entity_id!)}>⌖ INTEL</button>
                    </>
                  )}
                  <button
                    type="button"
                    className="locate-mini"
                    aria-label="Ask AI about this item"
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
            {!loading && all.length > 0 && filtered.length === 0 && (
              <li className="situation-empty">No items match the current filters.</li>
            )}
          </ul>

          {(entityCtx || entityLoading) && (
            <aside className="situation-entity-panel" aria-label="Entity context">
              <h3>Entity context</h3>
              {entityLoading && <div className="situation-loading">Loading…</div>}
              {!entityLoading && entityCtx?.error && (
                <div className="situation-entity-error">{entityCtx.error}</div>
              )}
              {!entityLoading && entityCtx?.entity && (
                <div className="situation-entity-card">
                  <div className="situation-entity-name">{entityCtx.entity.label || entityCtx.entity.id}</div>
                  <dl className="situation-entity-fields">
                    {entityCtx.entity.type && (<><dt>Schema</dt><dd>{entityCtx.entity.type}</dd></>)}
                    {entityCtx.entity.id && (<><dt>ID</dt><dd>{entityCtx.entity.id}</dd></>)}
                    {entityCtx.entity.source_feed && (<><dt>Source</dt><dd>{entityCtx.entity.source_feed}</dd></>)}
                    {entityCtx.entity.updated_at && (<><dt>Updated</dt><dd>{entityCtx.entity.updated_at}</dd></>)}
                    {entityCtx.entity.lat != null && entityCtx.entity.lon != null && (
                      <><dt>Coords</dt><dd>{Number(entityCtx.entity.lat).toFixed(3)}, {Number(entityCtx.entity.lon).toFixed(3)}</dd></>
                    )}
                    <dt>Links</dt><dd>{entityCtx.links?.length ?? 0} · {entityCtx.related?.length ?? 0} related</dd>
                  </dl>
                  {entityCtx.entity.meta && Object.keys(entityCtx.entity.meta).length > 0 && (
                    <dl className="situation-entity-fields situation-entity-meta">
                      {Object.entries(entityCtx.entity.meta).slice(0, 8).map(([k, v]) => (
                        <span key={k}>
                          <dt>{k}</dt>
                          <dd>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</dd>
                        </span>
                      ))}
                    </dl>
                  )}
                  {(entityCtx.related?.length ?? 0) > 0 && (
                    <div className="situation-entity-related">
                      {entityCtx.related!.slice(0, 6).map((r) => (
                        <span key={r.id} className="insight-chip insight-chip-entity">{r.label || r.id}</span>
                      ))}
                    </div>
                  )}
                  <div className="situation-actions">
                    {entityCtx.entity.id && (
                      <button type="button" className="locate-mini" aria-label="Open entity in INTEL graph" onClick={() => onOpenIntel(entityCtx.entity!.id!)}>
                        ⌖ Open in INTEL
                      </button>
                    )}
                  </div>
                  <details className="situation-entity-raw">
                    <summary>Raw JSON</summary>
                    <pre className="situation-entity-json">{JSON.stringify(entityCtx, null, 2)}</pre>
                  </details>
                </div>
              )}
              <button type="button" className="locate-mini" aria-label="Close entity context" onClick={() => setEntityCtx(null)}>Close</button>
            </aside>
          )}
        </div>
      </div>
    </div>
  )
}
