import { useCallback, useEffect, useState } from 'react'
import { fetchApi } from '../lib/networkFetch'
import ProvenanceChain from './ProvenanceChain'
import ActionBar from './ActionBar'
import RelatedEntitiesGraph from './RelatedEntitiesGraph'

/* ── Types ────────────────────────────────────────────────────────────────── */

interface EntityStatement {
  prop: string
  value: string
  dataset: string
  seen_at: string | null
  lang?: string | null
}

interface EntityEdge {
  source_id: string
  target_id: string
  kind: string
  properties?: Record<string, unknown>
  confidence?: number | null
  dataset?: string
  seen_at?: string | null
}

interface EntityNeighbour {
  id: string
  schema?: string | null
  caption?: string | null
  lat?: number | null
  lon?: number | null
}

interface EntityData {
  id: string
  schema?: string | null
  caption?: string | null
  properties?: Record<string, unknown>
  datasets?: string[]
  first_seen?: string | null
  last_seen?: string | null
  lat?: number | null
  lon?: number | null
  statements?: EntityStatement[]
  edges?: EntityEdge[]
  neighbours?: EntityNeighbour[]
  found?: boolean
}

interface GraphNode {
  id: string
  schema?: string | null
  caption?: string | null
  lat?: number | null
  lon?: number | null
}

interface GraphEdge {
  source_id: string
  target_id: string
  kind?: string | null
  confidence?: number | null
}

interface EntityDetailPanelProps {
  entityId: string | null
  onSelectEntity?: (id: string) => void
  onFocus?: (lat: number, lon: number, title: string) => void
}

/* ── Helpers ───────────────────────────────────────────────────────────────── */

const SKIP_PROPS = new Set(['id', 'schema', 'caption', 'datasets', 'first_seen', 'last_seen', 'lat', 'lon', 'found', 'statements', 'edges', 'neighbours', 'properties'])

function fmtDate(ts: string | null | undefined): string {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleDateString(undefined, { year: '2-digit', month: 'short', day: 'numeric' })
  } catch {
    return '—'
  }
}

function fmtVal(v: unknown): string {
  if (v == null) return '—'
  if (typeof v === 'string') return v
  if (typeof v === 'number') return String(v)
  if (Array.isArray(v)) return v.map(fmtVal).join(', ')
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/* ── Skeleton ──────────────────────────────────────────────────────────────── */

function SkeletonRows({ rows = 5 }: { rows?: number }) {
  return (
    <div className="entity-panel-skeleton">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="entity-panel-skeleton-row" style={{ animationDelay: `${i * 0.1}s` }} />
      ))}
    </div>
  )
}

/* ── Component ─────────────────────────────────────────────────────────────── */

export default function EntityDetailPanel({ entityId, onSelectEntity, onFocus }: EntityDetailPanelProps) {
  const [entity, setEntity] = useState<EntityData | null>(null)
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([])
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadData = useCallback(async (id: string) => {
    setLoading(true)
    setError(null)
    try {
      const [entRes, graphRes] = await Promise.all([
        fetchApi(`/api/ftm/entity/${encodeURIComponent(id)}`),
        fetchApi(`/api/ftm/entity/${encodeURIComponent(id)}/graph?depth=1&limit=50`),
      ])
      const ent: EntityData = entRes.ok ? await entRes.json() : { id, found: false }
      const graph = graphRes.ok ? await graphRes.json() : { nodes: [], edges: [] }
      setEntity(ent)
      setGraphNodes(graph.nodes || [])
      setGraphEdges(graph.edges || [])
    } catch {
      setError('Failed to load entity data')
      setEntity(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!entityId) {
      setEntity(null)
      setGraphNodes([])
      setGraphEdges([])
      return
    }
    loadData(entityId)
  }, [entityId, loadData])

  /* ── Empty state ───────────────────────────────────────────────────────── */
  if (!entityId) {
    return (
      <div className="entity-panel-empty">
        <div className="entity-panel-empty-icon">◎</div>
        <div className="entity-panel-empty-text">Select an entity on the globe to view details</div>
      </div>
    )
  }

  /* ── Loading state ─────────────────────────────────────────────────────── */
  if (loading) {
    return (
      <div className="entity-panel-loading">
        <div className="entity-panel-skeleton-header" />
        <SkeletonRows rows={4} />
        <div className="entity-panel-skeleton-header" style={{ marginTop: '12px' }} />
        <SkeletonRows rows={3} />
      </div>
    )
  }

  /* ── Error state ───────────────────────────────────────────────────────── */
  if (error) {
    return (
      <div className="entity-panel-error">
        <div className="entity-panel-error-text">{error}</div>
      </div>
    )
  }

  /* ── Not found ─────────────────────────────────────────────────────────── */
  if (entity && entity.found === false) {
    return (
      <div className="entity-panel-error">
        <div className="entity-panel-error-text">Entity not found: {entityId}</div>
      </div>
    )
  }

  if (!entity) return null

  /* ── Build properties list ─────────────────────────────────────────────── */
  const propEntries: { key: string; value: string }[] = []

  // From top-level properties dict
  if (entity.properties && typeof entity.properties === 'object') {
    for (const [k, v] of Object.entries(entity.properties)) {
      if (SKIP_PROPS.has(k)) continue
      propEntries.push({ key: k, value: fmtVal(v) })
    }
  }

  // From statements (deduplicated by prop)
  const seenProps = new Set(propEntries.map((p) => p.key))
  if (entity.statements) {
    for (const s of entity.statements) {
      if (seenProps.has(s.prop)) continue
      propEntries.push({ key: s.prop, value: s.value })
      seenProps.add(s.prop)
    }
  }

  // Build graph nodes from graph endpoint (includes root + neighbours)
  const displayNodes: GraphNode[] = graphNodes.length > 0
    ? graphNodes.slice(0, 9)
    : [
        { id: entity.id, schema: entity.schema, caption: entity.caption },
        ...(entity.neighbours || []).slice(0, 8).map((n) => ({ id: n.id, schema: n.schema, caption: n.caption, lat: n.lat, lon: n.lon })),
      ]

  const displayEdges: GraphEdge[] = graphEdges.length > 0
    ? graphEdges.slice(0, 20)
    : (entity.edges || []).slice(0, 20).map((e) => ({
        source_id: e.source_id,
        target_id: e.target_id,
        kind: e.kind,
        confidence: e.confidence,
      }))

  const handleRelatedSelect = (id: string) => {
    onSelectEntity?.(id)
  }

  const handleFocus = () => {
    if (onFocus && entity.lat != null && entity.lon != null) {
      onFocus(entity.lat, entity.lon, entity.caption || entity.id)
    }
  }

  return (
    <div className="entity-detail-panel">
      {/* Header */}
      <div className="entity-panel-header">
        <div className="entity-panel-caption">{entity.caption || 'Untitled'}</div>
        <div className="entity-panel-meta">
          {entity.schema && (
            <span className="entity-panel-schema-badge">{entity.schema}</span>
          )}
          {entity.lat != null && entity.lon != null && (
            <button
              className="entity-panel-focus-btn"
              onClick={handleFocus}
              title="Focus globe on this entity"
            >
              ◎ focus
            </button>
          )}
        </div>
        <div className="entity-panel-id" title={entity.id}>{entity.id}</div>
      </div>

      {/* Properties */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">PROPERTIES</div>
        {propEntries.length === 0 ? (
          <div className="sidebar-empty">No properties available</div>
        ) : (
          <div className="entity-panel-props">
            {propEntries.slice(0, 20).map((p, i) => (
              <div key={i} className="entity-panel-prop-row">
                <span className="entity-panel-prop-key">{p.key}</span>
                <span className="entity-panel-prop-val" title={p.value}>{p.value}</span>
              </div>
            ))}
          </div>
        )}
        {entity.datasets && entity.datasets.length > 0 && (
          <div className="entity-panel-datasets">
            {entity.datasets.map((d) => (
              <span key={d} className="entity-panel-dataset-tag">{d}</span>
            ))}
          </div>
        )}
        <div className="entity-panel-timestamps">
          {entity.first_seen && (
            <span className="entity-panel-ts">First: {fmtDate(entity.first_seen)}</span>
          )}
          {entity.last_seen && (
            <span className="entity-panel-ts">Last: {fmtDate(entity.last_seen)}</span>
          )}
        </div>
      </div>

      {/* Related Entities */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">RELATED ENTITIES</div>
        <RelatedEntitiesGraph
          rootEntityId={entity.id}
          nodes={displayNodes}
          edges={displayEdges}
          onSelectEntity={handleRelatedSelect}
        />
      </div>

      {/* Provenance Chain */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">PROVENANCE CHAIN</div>
        <ProvenanceChain entityId={entity.id} compact />
      </div>

      {/* Actions */}
      <div className="sidebar-section">
        <div className="sidebar-section-title">ACTIONS</div>
        <div className="action-bar action-bar--compact">
          <ActionBar
            itemId={`entity:${entity.id}`}
            itemTitle={entity.caption || entity.id}
            entityId={entity.id}
            showPublish={false}
          />
        </div>
      </div>
    </div>
  )
}
