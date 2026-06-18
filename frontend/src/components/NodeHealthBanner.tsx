import { useEffect, useMemo, useState } from 'react'
import { fetchApi } from '../lib/networkFetch'
import { PRIMARY_EDGE_NODE } from './EdgePanel'

type NodeRow = {
  node_id: string
  name?: string
  online?: boolean
  age_seconds?: number | null
  updated_at?: string
  sensors?: { temp_c?: number; humidity_pct?: number }
  health?: { cpu_temp_c?: number }
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
  const [dismissedOffline, setDismissedOffline] = useState(false)
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

  const primary = useMemo(
    () => nodes.find((n) => n.node_id === PRIMARY_EDGE_NODE) || null,
    [nodes],
  )

  useEffect(() => {
    if (primary?.online) setDismissedOffline(false)
  }, [primary?.online])

  if (error) return null

  if (primary?.online) {
    const cpu = primary.health?.cpu_temp_c
    const room = primary.sensors?.temp_c
    const parts = [
      cpu != null ? `CPU ${cpu}°C` : null,
      room != null ? `room ${room}°C` : null,
      `push ${formatAge(primary.age_seconds)}`,
    ].filter(Boolean)
    return (
      <div className="node-banner node-banner--online" role="status">
        <span className="node-banner-tag node-banner-tag--online">EDGE ONLINE</span>
        <span className="node-banner-online-detail">{parts.join(' · ')}</span>
      </div>
    )
  }

  if (!primary || dismissedOffline) return null

  return (
    <div className="node-banner" role="status">
      <span className="node-banner-tag">EDGE OFFLINE</span>
      <div className="node-banner-list">
        <span className="node-banner-row">
          <strong>{primary.name || PRIMARY_EDGE_NODE}</strong>
          <span className="node-banner-age">last seen {formatAge(primary.age_seconds)}</span>
        </span>
      </div>
      <span className="node-banner-hint">
        check Pi power / SSH; if recently rebooted, verify PC IP is 192.168.1.111 (DHCP reservation)
      </span>
      <button
        type="button"
        className="node-banner-close"
        aria-label="Dismiss banner"
        onClick={() => setDismissedOffline(true)}
      >
        ×
      </button>
    </div>
  )
}
