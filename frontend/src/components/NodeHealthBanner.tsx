import { useEffect, useMemo, useState } from 'react'
import { fetchApi } from '../lib/networkFetch'

type NodeRow = {
  node_id: string
  name?: string
  online?: boolean
  age_seconds?: number | null
  updated_at?: string
}

type NodesResponse = {
  count: number
  nodes: NodeRow[]
}

const POLL_MS = 60_000

function formatAge(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return 'unknown'
  const s = Math.max(0, Math.floor(seconds))
  if (s < 90) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 90) return `${m}m ago`
  const h = m / 60
  if (h < 48) return `${h.toFixed(h < 10 ? 1 : 0)}h ago`
  return `${Math.floor(h / 24)}d ago`
}

export function NodeHealthBanner() {
  const [nodes, setNodes] = useState<NodeRow[]>([])
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const r = await fetchApi('/api/nodes')
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const data: NodesResponse = await r.json()
        if (!alive) return
        setNodes(data.nodes || [])
        setError(null)
      } catch (e: any) {
        if (!alive) return
        setError(e?.message || 'fetch failed')
      }
    }
    tick()
    const id = window.setInterval(tick, POLL_MS)
    return () => { alive = false; window.clearInterval(id) }
  }, [])

  // Reset dismissal when a node transitions back to online — so the next outage shows again.
  useEffect(() => {
    if (!nodes.length) return
    setDismissed((prev) => {
      const next = new Set(prev)
      for (const n of nodes) {
        if (n.online && next.has(n.node_id)) next.delete(n.node_id)
      }
      return next
    })
  }, [nodes])

  const offline = useMemo(
    () => nodes.filter((n) => n.online === false && !dismissed.has(n.node_id)),
    [nodes, dismissed],
  )

  if (error || offline.length === 0) return null

  return (
    <div className="node-banner" role="status">
      <span className="node-banner-tag">EDGE OFFLINE</span>
      <div className="node-banner-list">
        {offline.map((n) => (
          <span key={n.node_id} className="node-banner-row">
            <strong>{n.name || n.node_id}</strong>
            <span className="node-banner-age">last seen {formatAge(n.age_seconds)}</span>
          </span>
        ))}
      </div>
      <span className="node-banner-hint">
        check Pi power / SSH; if recently rebooted, verify PC IP is 192.168.1.111 (DHCP reservation)
      </span>
      <button
        type="button"
        className="node-banner-close"
        aria-label="Dismiss banner"
        onClick={() => setDismissed(new Set(offline.map((n) => n.node_id)))}
      >
        ×
      </button>
    </div>
  )
}
