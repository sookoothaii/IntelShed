import { useMemo, useState } from 'react'

/* ── Types ────────────────────────────────────────────────────────────────── */

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

interface RelatedEntitiesGraphProps {
  rootEntityId: string
  nodes: GraphNode[]
  edges: GraphEdge[]
  onSelectEntity: (id: string) => void
}

/* ── Layout helpers ────────────────────────────────────────────────────────── */

interface PositionedNode extends GraphNode {
  x: number
  y: number
  vx: number
  vy: number
  isRoot: boolean
}

const WIDTH = 280
const HEIGHT = 180
const CENTER_X = WIDTH / 2
const CENTER_Y = HEIGHT / 2
const NODE_RADIUS = 10
const ROOT_RADIUS = 14
const ITERATIONS = 80

function schemaColor(schema?: string | null): string {
  if (!schema) return 'var(--txt-muted)'
  const s = schema.toLowerCase()
  if (s.includes('person')) return 'var(--accent)'
  if (s.includes('organization') || s.includes('company')) return 'var(--green)'
  if (s.includes('address') || s.includes('location')) return 'var(--amber)'
  if (s.includes('event')) return '#e74c3c'
  if (s.includes('asset') || s.includes('vehicle')) return '#9b59b6'
  return 'var(--txt-dim)'
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max - 1) + '…' : s
}

/**
 * Simple force-directed layout:
 * - Root node pinned at center
 * - Radial placement with jitter for neighbours
 * - Repulsion between all nodes, attraction along edges
 */
function computeLayout(nodes: GraphNode[], edges: GraphEdge[], rootId: string): PositionedNode[] {
  const positioned: PositionedNode[] = nodes.map((n) => {
    const isRoot = n.id === rootId
    const angle = Math.random() * Math.PI * 2
    const dist = isRoot ? 0 : 55 + Math.random() * 25
    return {
      ...n,
      x: CENTER_X + Math.cos(angle) * dist,
      y: CENTER_Y + Math.sin(angle) * dist,
      vx: 0,
      vy: 0,
      isRoot,
    }
  })

  const idMap = new Map(positioned.map((p) => [p.id, p]))

  for (let iter = 0; iter < ITERATIONS; iter++) {
    const cooling = 1 - iter / ITERATIONS

    // Repulsion
    for (let i = 0; i < positioned.length; i++) {
      for (let j = i + 1; j < positioned.length; j++) {
        const a = positioned[i]
        const b = positioned[j]
        const dx = b.x - a.x
        const dy = b.y - a.y
        const distSq = dx * dx + dy * dy + 0.01
        const dist = Math.sqrt(distSq)
        const force = 800 / distSq
        const fx = (dx / dist) * force * cooling
        const fy = (dy / dist) * force * cooling
        if (!a.isRoot) { a.vx -= fx; a.vy -= fy }
        if (!b.isRoot) { b.vx += fx; b.vy += fy }
      }
    }

    // Attraction along edges
    for (const e of edges) {
      const a = idMap.get(e.source_id)
      const b = idMap.get(e.target_id)
      if (!a || !b) continue
      const dx = b.x - a.x
      const dy = b.y - a.y
      const dist = Math.sqrt(dx * dx + dy * dy + 0.01)
      const targetDist = 60
      const force = (dist - targetDist) * 0.04 * cooling
      const fx = (dx / dist) * force
      const fy = (dy / dist) * force
      if (!a.isRoot) { a.vx += fx; a.vy += fy }
      if (!b.isRoot) { b.vx -= fx; b.vy -= fy }
    }

    // Apply velocity + bounds
    for (const p of positioned) {
      if (p.isRoot) {
        p.x = CENTER_X
        p.y = CENTER_Y
        p.vx = 0
        p.vy = 0
        continue
      }
      p.x += p.vx * 0.1
      p.y += p.vy * 0.1
      p.vx *= 0.6
      p.vy *= 0.6
      const margin = NODE_RADIUS + 4
      p.x = Math.max(margin, Math.min(WIDTH - margin, p.x))
      p.y = Math.max(margin, Math.min(HEIGHT - margin, p.y))
    }
  }

  return positioned
}

/* ── Component ─────────────────────────────────────────────────────────────── */

export default function RelatedEntitiesGraph({
  rootEntityId,
  nodes,
  edges,
  onSelectEntity,
}: RelatedEntitiesGraphProps) {
  const [hoveredId, setHoveredId] = useState<string | null>(null)
  const layoutKey = useMemo(
    () => nodes.map((n) => n.id).join(',') + '|' + edges.map((e) => `${e.source_id}-${e.target_id}`).join(','),
    [nodes, edges],
  )

  // Recompute layout only when node/edge set changes
  const positioned = useMemo(() => {
    if (nodes.length === 0) return []
    return computeLayout(nodes, edges, rootEntityId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layoutKey])

  if (nodes.length <= 1) {
    return <div className="related-graph-empty">No connected entities</div>
  }

  const idToNode = new Map(positioned.map((p) => [p.id, p]))

  return (
    <div className="related-graph-container">
      <svg
        width={WIDTH}
        height={HEIGHT}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="related-graph-svg"
      >
        {/* Edges */}
        {edges.map((e, i) => {
          const a = idToNode.get(e.source_id)
          const b = idToNode.get(e.target_id)
          if (!a || !b) return null
          const isHighlighted =
            hoveredId === e.source_id || hoveredId === e.target_id
          return (
            <line
              key={i}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              className={`related-graph-edge${isHighlighted ? ' related-graph-edge--hl' : ''}`}
            />
          )
        })}

        {/* Edge labels (only for small graphs) */}
        {edges.length <= 6 &&
          edges.map((e, i) => {
            const a = idToNode.get(e.source_id)
            const b = idToNode.get(e.target_id)
            if (!a || !b || !e.kind) return null
            const mx = (a.x + b.x) / 2
            const my = (a.y + b.y) / 2
            return (
              <text
                key={`l${i}`}
                x={mx}
                y={my}
                className="related-graph-edge-label"
                textAnchor="middle"
              >
                {truncate(e.kind, 10)}
              </text>
            )
          })}

        {/* Nodes */}
        {positioned.map((p) => {
          const r = p.isRoot ? ROOT_RADIUS : NODE_RADIUS
          const isHovered = hoveredId === p.id
          return (
            <g
              key={p.id}
              transform={`translate(${p.x},${p.y})`}
              className="related-graph-node-g"
              onClick={() => !p.isRoot && onSelectEntity(p.id)}
              onMouseEnter={() => setHoveredId(p.id)}
              onMouseLeave={() => setHoveredId(null)}
              style={{ cursor: p.isRoot ? 'default' : 'pointer' }}
            >
              <circle
                r={r}
                className={`related-graph-node${p.isRoot ? ' related-graph-node--root' : ''}${isHovered ? ' related-graph-node--hl' : ''}`}
                fill={schemaColor(p.schema)}
              />
              <text
                y={r + 12}
                className="related-graph-node-label"
                textAnchor="middle"
              >
                {truncate(p.caption || p.id.split('/').pop() || '?', 16)}
              </text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
