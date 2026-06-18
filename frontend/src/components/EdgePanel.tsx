import { useCallback, useEffect, useState } from 'react'
import { fetchApi } from '../lib/networkFetch'
import type { FocusTarget } from '../lib/focus'
import SensorSparklines from './SensorSparklines'

export const PRIMARY_EDGE_NODE = 'offgrid-pi'

type EdgeNode = {
  node_id: string
  name?: string
  online?: boolean
  age_seconds?: number | null
  updated_at?: string
  lat?: number | null
  lon?: number | null
  sensors?: Record<string, number | string>
  health?: {
    cpu_temp_c?: number
    ram_pct?: number
    ram_mb_total?: number
    ram_mb_used?: number
    disk_pct?: number
    load_1m?: number
    load_5m?: number
    load_15m?: number
    uptime_sec?: number
    services?: Record<string, string>
  }
  mesh?: Array<{
    id?: string
    name?: string
    battery?: number
    last_text?: string
    last_seen?: string
  }>
  pihole?: { queries?: number; blocked?: number; percent?: number }
}

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

function formatUptime(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec)) return '—'
  const d = Math.floor(sec / 86400)
  const h = Math.floor((sec % 86400) / 3600)
  const m = Math.floor((sec % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

function pctBarColor(pct: number, warn = 80, crit = 92): string {
  if (pct >= crit) return '#ff4d5e'
  if (pct >= warn) return '#ffd23f'
  return '#00e5a0'
}

function tempColor(c: number): string {
  if (c >= 75) return '#ff4d5e'
  if (c >= 65) return '#ffd23f'
  return '#00e5a0'
}

export default function EdgePanel({ onFocus }: { onFocus: (f: Omit<FocusTarget, 'ts'>) => void }) {
  const [node, setNode] = useState<EdgeNode | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await fetchApi('/api/nodes')
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data = await r.json()
      const pi = (data.nodes || []).find((n: EdgeNode) => n.node_id === PRIMARY_EDGE_NODE) || null
      setNode(pi)
      if (!pi) setError('No push from offgrid-pi — check worldbase_push on the Pi')
    } catch (e: any) {
      setError(e?.message || 'fetch failed')
      setNode(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const id = window.setInterval(load, 60_000)
    return () => window.clearInterval(id)
  }, [load])

  const h = node?.health || {}
  const sensors = node?.sensors || {}
  const online = node?.online === true
  const roomTemp = sensors.temp_c as number | undefined
  const roomRh = sensors.humidity_pct as number | undefined

  return (
    <section className="edge-panel">
      <div className="edge-panel-toolbar">
        <button type="button" onClick={load} disabled={loading}>
          {loading ? 'Loading…' : '↻ Refresh'}
        </button>
        {node && (
          <span className={`edge-status-pill ${online ? 'online' : 'offline'}`}>
            {online ? 'EDGE ONLINE' : 'EDGE OFFLINE'}
          </span>
        )}
        {node?.age_seconds != null && (
          <span className="data-count">push {formatAge(node.age_seconds)}</span>
        )}
        {node?.lat != null && node?.lon != null && (
          <button
            type="button"
            className="edge-locate-btn"
            onClick={() =>
              onFocus({
                kind: 'node',
                lon: node.lon!,
                lat: node.lat!,
                height: 500000,
                title: node.name || PRIMARY_EDGE_NODE,
                lines: [`NODE: ${PRIMARY_EDGE_NODE}`, online ? 'STATUS: ONLINE' : 'STATUS: OFFLINE'],
              })
            }
          >
            ◎ LOCATE
          </button>
        )}
      </div>

      {error && <div className="data-error">{error}</div>}

      {!node && !error && !loading && (
        <div className="health-status pending">Waiting for Pi push to /api/node/ingest</div>
      )}

      {node && (
        <>
          <div className="edge-head">
            <div className="market-stat" style={{ borderColor: tempColor(h.cpu_temp_c ?? 0) }}>
              <span className="mh-label">CPU TEMP</span>
              <strong style={{ color: tempColor(h.cpu_temp_c ?? 0) }}>
                {h.cpu_temp_c != null ? `${h.cpu_temp_c}°C` : '—'}
              </strong>
              <small>Pi SoC</small>
            </div>
            <div className="market-stat">
              <span className="mh-label">RAM</span>
              <strong>{h.ram_pct != null ? `${h.ram_pct}%` : '—'}</strong>
              {h.ram_pct != null && (
                <div className="mh-bar">
                  <div
                    className="mh-bar-fill"
                    style={{ width: `${Math.min(100, h.ram_pct)}%`, background: pctBarColor(h.ram_pct) }}
                  />
                </div>
              )}
              <small>
                {h.ram_mb_used != null && h.ram_mb_total != null
                  ? `${h.ram_mb_used} / ${h.ram_mb_total} MB`
                  : 'system memory'}
              </small>
            </div>
            <div className="market-stat">
              <span className="mh-label">DISK</span>
              <strong>{h.disk_pct != null ? `${h.disk_pct}%` : '—'}</strong>
              {h.disk_pct != null && (
                <div className="mh-bar">
                  <div
                    className="mh-bar-fill"
                    style={{ width: `${Math.min(100, h.disk_pct)}%`, background: pctBarColor(h.disk_pct, 75, 90) }}
                  />
                </div>
              )}
              <small>root volume</small>
            </div>
            <div className="market-stat">
              <span className="mh-label">LOAD</span>
              <strong>{h.load_1m != null ? h.load_1m.toFixed(2) : '—'}</strong>
              <small>
                {h.load_5m != null ? `5m ${h.load_5m.toFixed(2)}` : ''}
                {h.load_15m != null ? ` · 15m ${h.load_15m.toFixed(2)}` : ''}
              </small>
            </div>
            <div className="market-stat">
              <span className="mh-label">UPTIME</span>
              <strong>{formatUptime(h.uptime_sec)}</strong>
              <small>since boot</small>
            </div>
            <div className="market-stat" style={{ borderColor: tempColor(roomTemp ?? 0) }}>
              <span className="mh-label">ROOM DHT</span>
              <strong>{roomTemp != null ? `${roomTemp}°C` : '—'}</strong>
              <small>{roomRh != null ? `${roomRh}% RH` : 'esp32_dht_usb'}</small>
            </div>
          </div>

          <SensorSparklines nodeId={PRIMARY_EDGE_NODE} hours={24} />

          {h.services && Object.keys(h.services).length > 0 && (
            <div className="edge-section">
              <h4>SERVICES</h4>
              <div className="edge-svc-grid">
                {Object.entries(h.services).map(([name, state]) => (
                  <span
                    key={name}
                    className={`edge-svc ${state === 'active' ? 'active' : state === 'unknown' ? 'unknown' : 'down'}`}
                  >
                    {name}={state}
                  </span>
                ))}
              </div>
            </div>
          )}

          {node.mesh && node.mesh.length > 0 && (
            <div className="edge-section">
              <h4>MESH NODES</h4>
              <div className="edge-mesh-list">
                {node.mesh.map((m, i) => (
                  <div key={`${m.id}-${i}`} className="edge-mesh-row">
                    <strong>{m.name || m.id || 'node'}</strong>
                    <span>
                      {m.battery != null ? `${m.battery}%` : '—'}
                      {m.last_text ? ` · "${m.last_text}"` : ''}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {node.pihole && node.pihole.blocked != null && (
            <div className="edge-section">
              <h4>PI-HOLE</h4>
              <div className="edge-pihole">
                {node.pihole.blocked} blocked / {node.pihole.queries} queries
                {node.pihole.percent != null ? ` (${node.pihole.percent}%)` : ''}
              </div>
            </div>
          )}
        </>
      )}
    </section>
  )
}
