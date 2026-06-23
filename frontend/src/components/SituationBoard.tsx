import { useEffect, useMemo, useRef, useState } from 'react'
import type { FocusTarget } from '../lib/focus'
import type { OsintPin } from '../lib/osintPins'
import { fetchApi } from '../lib/networkFetch'
import { writeHudSessionField } from '../lib/hudSessionState'
import { useSituationsQuery, useBriefingQuery, useInsightsQuery } from '../hooks/useHudQueries'

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
  onOpenIntel?: (entityId?: string) => void
  osintPins: OsintPin[]
  onAddPin: (pin: Omit<OsintPin, 'ts'>) => void
  onAskAI: (title: string, lines: string[]) => void
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

type SortKey = 'severity' | 'title' | 'source'

const SEV_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, warn: 3, low: 4 }

function sevClass(sev: string): string {
  if (sev === 'critical' || sev === 'high') return 'sit-sev-high'
  if (sev === 'medium' || sev === 'warn') return 'sit-sev-med'
  return 'sit-sev-low'
}

function useFocusTrap(active: boolean, containerRef: React.RefObject<HTMLElement | null>, onEscape: () => void) {
  useEffect(() => {
    if (!active || !containerRef.current) return
    const root = containerRef.current
    const focusables = () =>
      Array.from(root.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      )).filter((el) => !el.hasAttribute('disabled'))

    const first = focusables()[0]
    first?.focus()

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onEscape()
        return
      }
      if (e.key !== 'Tab') return
      const list = focusables()
      if (list.length === 0) return
      const idx = list.indexOf(document.activeElement as HTMLElement)
      if (e.shiftKey) {
        if (idx <= 0) {
          e.preventDefault()
          list[list.length - 1]?.focus()
        }
      } else if (idx === list.length - 1) {
        e.preventDefault()
        list[0]?.focus()
      }
    }
    root.addEventListener('keydown', onKey)
    return () => root.removeEventListener('keydown', onKey)
  }, [active, containerRef, onEscape])
}

function EntityContextView({ ctx }: { ctx: Record<string, unknown> }) {
  if (ctx.error) return <div className="situation-entity-error">{String(ctx.error)}</div>
  const entity = (ctx.entity || ctx) as Record<string, unknown>
  const caption = String(entity.caption || entity.name || entity.id || '—')
  const schema = String(entity.schema || '—')
  const datasets = Array.isArray(entity.datasets) ? entity.datasets.join(', ') : ''
  const props = entity.properties as Record<string, unknown> | undefined
  return (
    <div className="situation-entity-structured">
      <div className="situation-entity-row"><strong>Caption</strong><span>{caption}</span></div>
      <div className="situation-entity-row"><strong>Schema</strong><span>{schema}</span></div>
      {entity.id != null && (
        <div className="situation-entity-row"><strong>ID</strong><span className="situation-entity-mono">{String(entity.id)}</span></div>
      )}
      {datasets && <div className="situation-entity-row"><strong>Datasets</strong><span>{datasets}</span></div>}
      {props && Object.keys(props).length > 0 && (
        <div className="situation-entity-props">
          {Object.entries(props).slice(0, 8).map(([k, v]) => (
            <div key={k} className="situation-entity-row">
              <strong>{k}</strong>
              <span>{typeof v === 'object' ? JSON.stringify(v) : String(v)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function SituationBoard({
  onClose,
  onFocus,
  onOpenIntel,
  osintPins,
  onAddPin,
  onAskAI,
}: Props) {
  const panelRef = useRef<HTMLDivElement>(null)
  const [paused, setPaused] = useState(false)
  const [sevFilter, setSevFilter] = useState<string | null>(null)
  const [catFilter, setCatFilter] = useState<string | null>(null)
  const [srcFilter, setSrcFilter] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('severity')
  const [fusionShowAll, setFusionShowAll] = useState(false)
  const [entityCtx, setEntityCtx] = useState<Record<string, unknown> | null>(null)
  const [entityId, setEntityId] = useState<string | null>(null)
  const [entityLoading, setEntityLoading] = useState(false)
  const [copyMsg, setCopyMsg] = useState<string | null>(null)

  const pollEnabled = !paused
  const { data: sitData, isLoading: sitLoading, isFetching } = useSituationsQuery(pollEnabled)
  const { data: briefData, isLoading: briefLoading } = useBriefingQuery(pollEnabled)
  const { data: insData, isLoading: insLoading } = useInsightsQuery(10, pollEnabled)

  useFocusTrap(true, panelRef, onClose)

  const items: SituationItem[] = sitData?.items || []
  const fusionHotspots: FusionHotspot[] = briefData?.fusion_hotspots || []
  const insights: InsightCard[] = insData?.insights || []
  const loading = sitLoading || briefLoading || insLoading

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

  const allRaw = useMemo(() => [...items, ...pinItems], [items, pinItems])

  const sevCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const it of allRaw) {
      counts[it.severity] = (counts[it.severity] || 0) + 1
    }
    return counts
  }, [allRaw])

  const categories = useMemo(() => [...new Set(allRaw.map((i) => i.category))].sort(), [allRaw])
  const sources = useMemo(() => [...new Set(allRaw.map((i) => i.source))].sort(), [allRaw])

  const all = useMemo(() => {
    let list = [...allRaw]
    if (sevFilter) list = list.filter((i) => i.severity === sevFilter)
    if (catFilter) list = list.filter((i) => i.category === catFilter)
    if (srcFilter) list = list.filter((i) => i.source === srcFilter)
    const q = search.trim().toLowerCase()
    if (q) {
      list = list.filter(
        (i) =>
          i.title.toLowerCase().includes(q)
          || i.source.toLowerCase().includes(q)
          || i.category.toLowerCase().includes(q)
          || (i.entity_id || '').toLowerCase().includes(q),
      )
    }
    list.sort((a, b) => {
      if (sortKey === 'severity') return (SEV_ORDER[a.severity] ?? 3) - (SEV_ORDER[b.severity] ?? 3)
      if (sortKey === 'title') return a.title.localeCompare(b.title)
      return a.source.localeCompare(b.source)
    })
    return list
  }, [allRaw, sevFilter, catFilter, srcFilter, search, sortKey])

  const exportPayload = useMemo(
    () => ({
      exported_at: new Date().toISOString(),
      count: all.length,
      items: all,
      insights,
      fusion_hotspots: fusionHotspots,
    }),
    [all, insights, fusionHotspots],
  )

  const copyBoard = async (fmt: 'json' | 'md') => {
    const text =
      fmt === 'json'
        ? JSON.stringify(exportPayload, null, 2)
        : [
            '# Situation Board',
            '',
            `Items: ${all.length}`,
            '',
            ...all.map(
              (i) =>
                `- **${i.severity.toUpperCase()}** [${i.category}] ${i.title} _(${i.source})_`,
            ),
            '',
            insights.length > 0 ? `## Insights (${insights.length})` : '',
            ...insights.map((ins) => `- ${ins.headline}: ${ins.so_what}`),
          ].join('\n')
    try {
      await navigator.clipboard.writeText(text)
      setCopyMsg(fmt === 'json' ? 'JSON copied' : 'Markdown copied')
      setTimeout(() => setCopyMsg(null), 2000)
    } catch {
      setCopyMsg('Copy failed')
    }
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

  const loadEntity = async (id: string) => {
    setEntityId(id)
    setEntityLoading(true)
    try {
      const r = await fetchApi(`/api/entity/${encodeURIComponent(id)}/context`)
      setEntityCtx(await r.json())
    } catch {
      setEntityCtx({ error: 'load failed' })
    } finally {
      setEntityLoading(false)
    }
  }

  const openIntel = (id?: string) => {
    writeHudSessionField('dataTab', 'intel')
    if (id) writeHudSessionField('intelEntityFocus', id)
    onOpenIntel?.(id)
    onClose()
  }

  const fusionVisible = fusionShowAll ? fusionHotspots : fusionHotspots.slice(0, 3)

  return (
    <div className="situation-overlay" role="presentation" onClick={onClose}>
      <div
        ref={panelRef}
        className="situation-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Unified situation board"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="situation-header">
          <h2>Unified Situation Board</h2>
          <span className="situation-count" aria-live="polite">{all.length} items</span>
          <div className="situation-header-actions">
            <button
              type="button"
              className="locate-mini"
              onClick={() => setPaused((p) => !p)}
              title={paused ? 'Resume polling' : 'Pause polling'}
            >
              {paused ? '▶' : '⏸'}
            </button>
            <button type="button" className="locate-mini" onClick={() => copyBoard('json')} title="Copy JSON">
              JSON
            </button>
            <button type="button" className="locate-mini" onClick={() => copyBoard('md')} title="Copy Markdown">
              MD
            </button>
            <button type="button" className="situation-close" onClick={onClose} aria-label="Close">✕</button>
          </div>
        </header>

        <div className="situation-toolbar" role="search">
          <div className="situation-sev-pills" role="group" aria-label="Severity filters">
            <button
              type="button"
              className={`situation-pill${sevFilter === null ? ' on' : ''}`}
              onClick={() => setSevFilter(null)}
            >
              ALL {allRaw.length}
            </button>
            {['critical', 'high', 'medium', 'warn', 'low'].map((sev) =>
              sevCounts[sev] ? (
                <button
                  key={sev}
                  type="button"
                  className={`situation-pill situation-pill--${sev}${sevFilter === sev ? ' on' : ''}`}
                  onClick={() => setSevFilter(sevFilter === sev ? null : sev)}
                >
                  {sev.toUpperCase()} {sevCounts[sev]}
                </button>
              ) : null,
            )}
          </div>
          <div className="situation-filters">
            <input
              type="search"
              className="situation-search"
              placeholder="Search title, source, entity…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search situations"
            />
            <select
              className="situation-select"
              value={catFilter || ''}
              onChange={(e) => setCatFilter(e.target.value || null)}
              aria-label="Filter by category"
            >
              <option value="">All categories</option>
              {categories.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
            <select
              className="situation-select"
              value={srcFilter || ''}
              onChange={(e) => setSrcFilter(e.target.value || null)}
              aria-label="Filter by source"
            >
              <option value="">All sources</option>
              {sources.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <select
              className="situation-select"
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
              aria-label="Sort order"
            >
              <option value="severity">Sort: severity</option>
              <option value="title">Sort: title</option>
              <option value="source">Sort: source</option>
            </select>
          </div>
        </div>

        {loading && (
          <div className="situation-loading" role="status" aria-live="polite">
            Loading feeds… (correlations, GDACS, pegel — ~5–15 s first load)
          </div>
        )}
        {isFetching && !loading && (
          <div className="situation-refresh-hint" aria-live="polite">Refreshing…</div>
        )}
        {copyMsg && <div className="situation-copy-msg" role="status" aria-live="polite">{copyMsg}</div>}

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
                        <>
                          <button type="button" className="locate-mini" onClick={() => loadEntity(topEntity.id!)}>
                            ⎔ Context
                          </button>
                          <button type="button" className="locate-mini" onClick={() => openIntel(topEntity.id)}>
                            INTEL
                          </button>
                        </>
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
              <div className="situation-fusion-head">
                <h3>FUSION HOTSPOTS ({fusionHotspots.length})</h3>
                {fusionHotspots.length > 3 && (
                  <button
                    type="button"
                    className="locate-mini"
                    onClick={() => setFusionShowAll((v) => !v)}
                  >
                    {fusionShowAll ? 'Show top 3' : 'Show all'}
                  </button>
                )}
              </div>
              {fusionVisible.map((h, i) => (
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
                    <>
                      <button type="button" className="locate-mini" onClick={() => loadEntity(it.entity_id!)}>⎔ Context</button>
                      <button type="button" className="locate-mini" onClick={() => openIntel(it.entity_id)}>INTEL</button>
                    </>
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
              {!entityLoading && entityCtx && <EntityContextView ctx={entityCtx} />}
              <div className="situation-entity-actions">
                {entityId && (
                  <button type="button" className="locate-mini" onClick={() => openIntel(entityId)}>
                    Open in INTEL
                  </button>
                )}
                <button type="button" className="locate-mini" onClick={() => { setEntityCtx(null); setEntityId(null) }}>
                  Close
                </button>
              </div>
            </aside>
          )}
        </div>
      </div>
    </div>
  )
}
