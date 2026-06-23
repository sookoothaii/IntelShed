import { useCallback, useEffect, useRef, useState } from 'react'
import cytoscape from 'cytoscape'
import type { Core, ElementDefinition } from 'cytoscape'
import { fetchApi } from '../lib/networkFetch'
import type { FocusTarget } from '../lib/focus'

type IngestStatus = {
  loaded: boolean
  gliner_loaded?: boolean
  glirel_enabled?: boolean
  glirel_loaded?: boolean
  relations_mode?: 'disabled' | 'glirel' | 'unavailable'
  glirel_skip_reason?: string | null
  license_note?: string
  device: string | null
  gliner_model: string
  glirel_model: string
  load_error: string | null
  torch_version: string | null
  cuda_available: boolean
  cuda_device?: string
  relation_labels: string[]
}

type IngestResult = {
  ok: boolean
  device?: string
  relations_mode?: string
  root_id?: string
  source?: string
  truncated?: boolean
  counts?: { entities: number; edges: number; mentions: number; relations: number }
  error?: string
}

type GraphNode = { id: string; schema: string; caption: string; lat?: number | null; lon?: number | null }
type GraphEdge = {
  source_id: string
  target_id: string
  kind: string
  confidence?: number | null
  dataset?: string
  seen_at?: string | null
}
type GraphData = { root?: string | null; found: boolean; nodes: GraphNode[]; edges: GraphEdge[]; mode?: string }

interface Props {
  onFocus?: (f: Omit<FocusTarget, 'ts'>) => void
  /** When set (e.g. drill-down from SITUATIONS), auto-load this entity's graph. */
  initialEntityId?: string | null
}

const SCHEMA_COLOR: Record<string, string> = {
  Person: '#4ea1ff',
  Organization: '#ffb347',
  Company: '#ffb347',
  Address: '#7bdc8f',
  Vessel: '#56d4d4',
  Airplane: '#56d4d4',
  Event: '#ff6b6b',
  Document: '#b07cff',
}

/** Overview defaults: operator-relevant schemas (excludes Airplane noise). */
const OVERVIEW_SCHEMAS = ['Event', 'Vessel', 'Person', 'Organization', 'Address', 'Document'] as const
type OverviewSchema = (typeof OVERVIEW_SCHEMAS)[number]
type ResolutionStatus = {
  available: boolean
  splink_version?: string | null
  resolution_edges?: number
  last_run?: { edges_added?: number; finished_at?: string } | null
}

type FeedStatus = {
  autopilot?: boolean
  sources?: string[]
  last_run?: { totals?: { entities?: number; records?: number }; finished_at?: string } | null
  ftm_stats?: { entities?: number; edges?: number }
}

const edgeConfidenceClass = (kind: string, confidence?: number | null) => {
  if (kind === 'mentions') return 'mentions'
  if (kind === 'sameAs') return 'same-as'
  if (confidence == null || Number.isNaN(confidence)) return ''
  if (confidence >= 0.9) return 'conf-high'
  if (confidence >= 0.75) return 'conf-mid'
  return 'conf-low'
}

const fmtConfidence = (v?: number | null) =>
  v == null || Number.isNaN(v) ? '—' : `${Math.round(v * 100)}%`

const schemaColor = (s: string) => SCHEMA_COLOR[s] || '#9aa3b2'

export default function IntelGraphPanel({ onFocus, initialEntityId }: Props) {
  const [status, setStatus] = useState<IngestStatus | null>(null)
  const [text, setText] = useState('')
  const [dataset, setDataset] = useState('intel-ingest')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [rootId, setRootId] = useState('')
  const [resStatus, setResStatus] = useState<ResolutionStatus | null>(null)
  const [feedStatus, setFeedStatus] = useState<FeedStatus | null>(null)
  const [edgeTip, setEdgeTip] = useState<string | null>(null)
  const [graphEmpty, setGraphEmpty] = useState(true)
  const [schemaFilter, setSchemaFilter] = useState<Set<OverviewSchema>>(
    () => new Set(['Event', 'Vessel', 'Person', 'Organization']),
  )

  const cyRef = useRef<Core | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)

  const fetchStatus = useCallback(async () => {
    try {
      const r = await fetchApi('/api/intel/ingest/status')
      setStatus(await r.json())
    } catch (e: any) { setError(`status: ${e.message || e}`) }
  }, [])

  const fetchResolutionStatus = useCallback(async () => {
    try {
      const r = await fetchApi('/api/intel/resolution/status')
      setResStatus(await r.json())
    } catch { /* optional */ }
  }, [])

  const fetchFeedStatus = useCallback(async () => {
    try {
      const r = await fetchApi('/api/intel/feeds/status')
      setFeedStatus(await r.json())
    } catch { /* optional */ }
  }, [])

  useEffect(() => { fetchStatus(); fetchResolutionStatus(); fetchFeedStatus() }, [fetchStatus, fetchResolutionStatus, fetchFeedStatus])

  // Keep wheel zoom on the graph only — do not scroll the DATA panel underneath.
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const stopPanelScroll = (e: WheelEvent) => { e.stopPropagation() }
    el.addEventListener('wheel', stopPanelScroll, { passive: true })
    return () => el.removeEventListener('wheel', stopPanelScroll)
  }, [])

  // Init cytoscape once.
  useEffect(() => {
    if (cyRef.current || !containerRef.current) return
    const container = containerRef.current
    cyRef.current = cytoscape({
      container,
      elements: [],
      style: [
        {
          selector: 'node',
          style: {
            'background-color': 'data(color)',
            label: 'data(label)',
            color: '#e8edf4',
            'font-size': 9,
            'text-wrap': 'wrap',
            'text-max-width': '90px',
            'text-valign': 'bottom',
            'text-margin-y': 3,
            width: 22,
            height: 22,
            'border-width': 1,
            'border-color': '#0a0e14',
          },
        },
        {
          selector: 'node.root',
          style: { width: 32, height: 32, 'border-width': 2, 'border-color': '#fff' },
        },
        {
          selector: 'edge',
          style: {
            width: 1.4,
            'line-color': '#46506a',
            'target-arrow-color': '#46506a',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            label: 'data(label)',
            'font-size': 7,
            color: '#9aa3b2',
            'text-rotation': 'autorotate',
            'text-background-color': '#0a0e14',
            'text-background-opacity': 0.7,
            'text-background-padding': '1px',
          },
        },
        { selector: 'edge.mentions', style: { 'line-style': 'dashed', 'line-color': '#2e3650', 'target-arrow-color': '#2e3650' } },
        { selector: 'edge.same-as', style: { 'line-color': '#6b8cff', 'target-arrow-color': '#6b8cff', width: 2 } },
        { selector: 'edge.conf-high', style: { 'line-color': '#5bdc8f', 'target-arrow-color': '#5bdc8f' } },
        { selector: 'edge.conf-mid', style: { 'line-color': '#e6c84a', 'target-arrow-color': '#e6c84a' } },
        { selector: 'edge.conf-low', style: { 'line-color': '#ff7b6b', 'target-arrow-color': '#ff7b6b' } },
      ],
      layout: { name: 'grid' },
      // Default 1.0 — panel scroll is isolated separately; low values need excessive wheel spins.
      wheelSensitivity: 1,
      minZoom: 0.08,
      maxZoom: 8,
    })

    const cy = cyRef.current
    const ro = new ResizeObserver(() => {
      cy.resize()
    })
    ro.observe(container)

    cy.on('tap', 'node', (evt) => {
      const id = evt.target.id()
      const lat = evt.target.data('lat')
      const lon = evt.target.data('lon')
      if (onFocus && typeof lat === 'number' && typeof lon === 'number') {
        onFocus({ kind: 'osint', lon, lat, height: 600000, title: evt.target.data('label'), lines: [`SCHEMA: ${evt.target.data('schema')}`] })
      }
      setRootId(id)
      loadGraph(id)
    })

    cy.on('mouseover', 'edge', (evt) => {
      const d = evt.target.data()
      setEdgeTip(`${d.label} · ${fmtConfidence(d.confidence)} · ${d.dataset || '—'}${d.seen_at ? ` · ${d.seen_at.slice(0, 19)}` : ''}`)
    })
    cy.on('mouseout', 'edge', () => setEdgeTip(null))

    return () => {
      ro.disconnect()
      cy.destroy()
      cyRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const renderGraph = useCallback((g: GraphData, rootIdHint?: string) => {
    const cy = cyRef.current
    if (!cy) return
    if (!g.found || !g.nodes.length) {
      cy.elements().remove()
      setGraphEmpty(true)
      setInfo('No entities in graph store yet')
      return
    }
    setGraphEmpty(false)
    const els: ElementDefinition[] = []
    for (const n of g.nodes) {
      els.push({
        data: {
          id: n.id,
          label: n.caption || n.id.slice(0, 8),
          schema: n.schema,
          color: schemaColor(n.schema),
          lat: n.lat ?? undefined,
          lon: n.lon ?? undefined,
        },
        classes: rootIdHint && n.id === rootIdHint ? 'root' : undefined,
      })
    }
    for (const e of g.edges) {
      const conf = typeof e.confidence === 'number' ? e.confidence : undefined
      els.push({
        data: {
          id: `${e.source_id}__${e.target_id}__${e.kind}`,
          source: e.source_id,
          target: e.target_id,
          label: e.kind === 'sameAs' ? `sameAs ${fmtConfidence(conf)}` : e.kind,
          confidence: conf,
          dataset: e.dataset,
          seen_at: e.seen_at,
        },
        classes: edgeConfidenceClass(e.kind, conf),
      })
    }
    cy.elements().remove()
    cy.add(els)
    cy.layout({ name: 'cose', animate: false, nodeRepulsion: () => 9000, idealEdgeLength: () => 90, padding: 20 } as any).run()
    cy.fit(undefined, 30)
    const mode = g.mode === 'overview' ? 'overview · ' : ''
    setInfo(`${mode}${g.nodes.length} nodes · ${g.edges.length} edges`)
  }, [])

  const loadOverview = useCallback(async () => {
    setError(null)
    try {
      const qs = new URLSearchParams({
        limit: '120',
        datasets: 'gdacs,gdelt-pulse,gdelt-geo,ais,eonet,intel-ingest',
      })
      const schemas = [...schemaFilter]
      if (schemas.length) qs.set('schemas', schemas.join(','))
      const r = await fetchApi(`/api/intel/graph/overview?${qs}`)
      const g: GraphData = await r.json()
      if (!g.found) {
        setGraphEmpty(true)
        setError('No feed entities yet — run SYNC FEEDS or INGEST first.')
        return
      }
      renderGraph(g)
    } catch (e: any) { setError(`overview: ${e.message || e}`) }
  }, [renderGraph, schemaFilter])

  const toggleSchema = (schema: OverviewSchema) => {
    setSchemaFilter(prev => {
      const next = new Set(prev)
      if (next.has(schema)) next.delete(schema)
      else next.add(schema)
      return next
    })
  }

  const loadGraph = useCallback(async (id: string) => {
    if (!id) return
    setError(null)
    try {
      const r = await fetchApi(`/api/entity/${encodeURIComponent(id)}/graph?depth=2&limit=300`)
      const g: GraphData = await r.json()
      if (!g.found) { setError('Entity not found in graph store.'); setGraphEmpty(true); return }
      renderGraph(g, id)
    } catch (e: any) { setError(`graph: ${e.message || e}`) }
  }, [renderGraph])

  // Drill-down from SITUATIONS / FULL SITUATION: load the requested entity graph.
  useEffect(() => {
    if (!initialEntityId) return
    setRootId(initialEntityId)
    loadGraph(initialEntityId)
  }, [initialEntityId, loadGraph])

  const runFeeds = async () => {
    setBusy(true); setError(null); setInfo('Syncing live feeds into FtM graph…')
    try {
      const r = await fetchApi('/api/intel/feeds/run', { method: 'POST' })
      const d = await r.json()
      if (!r.ok) { setError(d.detail || `feed sync failed (${r.status})`); return }
      const t = d.totals || {}
      const res = d.resolution
      const resLine = res
        ? ` · resolve +${res.edges_added ?? 0} (${res.subset_edges ?? 0} subset)`
        : ''
      setInfo(`✓ feeds +${t.entities ?? 0} entities · ${t.records ?? 0} records${resLine} — loading overview…`)
      fetchFeedStatus()
      await loadOverview()
    } catch (e: any) { setError(`feeds: ${e.message || e}`) }
    finally { setBusy(false) }
  }

  const runResolution = async () => {
    setBusy(true); setError(null); setInfo('Running entity resolution (Splink)…')
    try {
      const r = await fetchApi('/api/intel/resolution/run', { method: 'POST' })
      const d = await r.json()
      if (!r.ok) { setError(d.detail || `resolution failed (${r.status})`); return }
      setInfo(`✓ resolution +${d.edges_added ?? 0} edges (${d.exact_edges ?? 0} exact · ${d.subset_edges ?? 0} subset · ${d.splink_edges ?? 0} splink)`)
      fetchResolutionStatus()
      if (rootId) await loadGraph(rootId)
      else await loadOverview()
    } catch (e: any) { setError(`resolution: ${e.message || e}`) }
    finally { setBusy(false) }
  }

  const ingest = async () => {
    if (!text.trim()) { setError('Paste some text first.'); return }
    setBusy(true); setError(null); setInfo('Extracting entities + relations (first run loads the model)…')
    try {
      const r = await fetchApi('/api/intel/ingest/text', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, dataset }),
      })
      const d: IngestResult = await r.json()
      if (!r.ok || !d.ok) { setError(d.error || `ingest failed (${r.status})`); return }
      setInfo(`✓ ${d.counts?.entities ?? 0} entities · ${d.counts?.relations ?? 0} relations · ${d.counts?.mentions ?? 0} mentions · ${d.relations_mode ?? '?'}`)
      fetchStatus()
      if (d.root_id) { setRootId(d.root_id); loadGraph(d.root_id) }
    } catch (e: any) { setError(`ingest: ${e.message || e}`) }
    finally { setBusy(false) }
  }

  const upload = async (file: File) => {
    setBusy(true); setError(null); setInfo(`Parsing ${file.name}…`)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('dataset', dataset)
      const r = await fetchApi('/api/intel/ingest/document', { method: 'POST', body: fd })
      const d: IngestResult = await r.json()
      if (!r.ok || !d.ok) { setError(d.error || `upload failed (${r.status})`); return }
      setInfo(`✓ ${d.counts?.entities ?? 0} entities · ${d.counts?.relations ?? 0} relations · ${d.device}`)
      fetchStatus()
      if (d.root_id) { setRootId(d.root_id); loadGraph(d.root_id) }
    } catch (e: any) { setError(`upload: ${e.message || e}`) }
    finally { setBusy(false) }
  }

  return (
    <div className="intel-panel">
      <div className="intel-status">
        {status ? (
          <>
            <span className={`stat-pill ${status.cuda_available ? 'ok' : 'warn'}`}>
              {status.cuda_available ? `GPU ${status.cuda_device?.replace('NVIDIA GeForce ', '') || 'CUDA'}` : 'CPU'}
            </span>
            <span className="stat-meta">
              {status.relations_mode === 'glirel'
                ? 'relations: GLiREL (opt-in NC)'
                : status.relations_mode === 'unavailable'
                  ? 'relations: unavailable — see status'
                  : 'relations: off (entities + mentions only)'}
            </span>
            <span className="stat-meta">{status.loaded ? `model loaded · ${status.device}` : 'model lazy (loads on first ingest)'}</span>
            <span className="stat-meta">torch {status.torch_version || '—'}</span>
            {status.load_error && <span className="data-error">{status.load_error}</span>}
            {resStatus?.available && (
              <span className="stat-meta">
                resolution: {resStatus.resolution_edges ?? 0} sameAs
                {resStatus.splink_version ? ` · splink ${resStatus.splink_version}` : ''}
              </span>
            )}
            {feedStatus && (
              <span className="stat-meta">
                ftm: {feedStatus.ftm_stats?.entities ?? 0} ent · {feedStatus.ftm_stats?.edges ?? 0} edges
                {feedStatus.autopilot ? ' · feeds autopilot' : ''}
              </span>
            )}
          </>
        ) : <span className="stat-meta">Loading status…</span>}
      </div>

      <div className="intel-section">
        <h3>📥 Ingest text → entity graph</h3>
        <textarea
          className="intel-textarea"
          placeholder="Paste a report, article, or notes. GLiNER extracts entities, GLiREL extracts relations."
          value={text}
          onChange={e => setText(e.target.value)}
          rows={5}
        />
        <div className="intel-toolbar">
          <input className="intel-dataset" value={dataset} onChange={e => setDataset(e.target.value)} title="Provenance dataset tag" />
          <button className="data-refresh" onClick={ingest} disabled={busy}>{busy ? '…' : 'INGEST'}</button>
          <label className="intel-upload">
            UPLOAD PDF/EML
            <input
              type="file"
              accept=".pdf,.eml,.msg,.txt"
              style={{ display: 'none' }}
              onChange={e => { const f = e.target.files?.[0]; if (f) upload(f); e.currentTarget.value = '' }}
            />
          </label>
        </div>
      </div>

      <div className="intel-section intel-section-graph">
        <h3>🕸 Graph <span className="stat-meta">{info || '—'}</span></h3>
        <div className="intel-toolbar">
          <input
            className="intel-dataset wide"
            placeholder="Entity id (or ingest above)…"
            value={rootId}
            onChange={e => setRootId(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && loadGraph(rootId)}
          />
          <button className="data-refresh" onClick={() => loadGraph(rootId)} disabled={!rootId}>LOAD</button>
          <button className="data-refresh" onClick={loadOverview} disabled={busy} title="Show recent feed + ingest entities">OVERVIEW</button>
          <button className="data-refresh" onClick={runFeeds} disabled={busy} title="Pull GDACS/GDELT/EONET/AIS/anomalies into FtM">SYNC FEEDS</button>
          <button className="data-refresh" onClick={runResolution} disabled={busy || !resStatus?.available} title="Splink entity resolution -> sameAs edges">RESOLVE</button>
        </div>
        <div className="intel-schema-filter" title="Filter overview graph by FtM schema (excludes Airplane by default)">
          {OVERVIEW_SCHEMAS.map(s => (
            <button
              key={s}
              type="button"
              className={`intel-schema-pill${schemaFilter.has(s) ? ' active' : ''}`}
              style={schemaFilter.has(s) ? { borderColor: schemaColor(s), color: schemaColor(s) } : undefined}
              onClick={() => toggleSchema(s)}
            >
              {s}
            </button>
          ))}
        </div>
        {error && <div className="data-error">{error}</div>}
        <div className="intel-graph-wrap">
          {graphEmpty && !busy && (
            <div className="intel-graph-empty">
              No graph yet — SYNC FEEDS or INGEST, or click OVERVIEW
            </div>
          )}
          <div ref={containerRef} className="intel-graph" />
        </div>
        {edgeTip && <div className="intel-edge-tip">{edgeTip}</div>}
        <div className="intel-legend">
          {Object.entries(SCHEMA_COLOR).filter(([k]) => k !== 'Company').map(([k, c]) => (
            <span key={k}><i style={{ background: c }} />{k}</span>
          ))}
          <span className="intel-legend-hint">click node · hover edge for provenance · dashed = mentions · blue/green = sameAs</span>
        </div>
      </div>
    </div>
  )
}
