import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchApi } from '../lib/networkFetch'

export type TrafficCamRef = {
  id: string
  name: string
  lat: number
  lon: number
  image_url?: string
  source?: string
  country?: string
  refresh_ms?: number
}

type NearbyCam = TrafficCamRef & { distance_km?: number }

function distKm(a: { lat: number; lon: number }, b: { lat: number; lon: number }): number {
  const r = Math.PI / 180
  const dlat = (b.lat - a.lat) * r
  const dlon = (b.lon - a.lon) * r
  const x =
    Math.sin(dlat / 2) ** 2 +
    Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dlon / 2) ** 2
  return 6371 * 2 * Math.atan2(Math.sqrt(x), Math.sqrt(1 - x))
}

export default function TrafficCamPanel({
  cam,
  onSelectCam,
  streamMode = false,
}: {
  cam: TrafficCamRef
  onSelectCam?: (next: TrafficCamRef) => void
  /** Faster image polling for live-feed feel in globe modal */
  streamMode?: boolean
}) {
  const [live, setLive] = useState<TrafficCamRef>(cam)
  const [nearby, setNearby] = useState<NearbyCam[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [imgTick, setImgTick] = useState(0)

  const refreshMs = live.refresh_ms && live.refresh_ms > 0 ? live.refresh_ms : 120_000
  const streamPollMs = streamMode ? 8_000 : refreshMs

  const loadCam = useCallback(async (id: string, force = false) => {
    setLoading(true)
    setError(null)
    try {
      const q = force ? '?refresh=1' : ''
      const r = await fetchApi(`/api/traffic/cams/${encodeURIComponent(id)}${q}`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const d = await r.json()
      if (d.camera) {
        setLive(d.camera)
        setImgTick((t) => t + 1)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Refresh failed')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    setLive(cam)
    setImgTick((t) => t + 1)
  }, [cam.id])

  useEffect(() => {
    let active = true
    fetchApi('/api/traffic/cams?scope=regional')
      .then((r) => r.json())
      .then((d) => {
        if (!active || !d.cameras) return
        const list: NearbyCam[] = d.cameras
          .filter((c: TrafficCamRef) => c.lat != null && c.lon != null)
          .map((c: TrafficCamRef) => ({
            ...c,
            distance_km: distKm(cam, { lat: c.lat, lon: c.lon }),
          }))
          .sort((a: NearbyCam, b: NearbyCam) => (a.distance_km ?? 0) - (b.distance_km ?? 0))
        setNearby(list)
      })
      .catch(() => {})
    return () => {
      active = false
    }
  }, [cam.id, cam.lat, cam.lon])

  useEffect(() => {
    const t = window.setInterval(() => loadCam(live.id, true), streamPollMs)
    return () => window.clearInterval(t)
  }, [live.id, streamPollMs, loadCam])

  useEffect(() => {
    if (!streamMode || !live.id) return
    const t = window.setInterval(() => setImgTick((n) => n + 1), 4_000)
    return () => window.clearInterval(t)
  }, [streamMode, live.id])

  const imageSrc = useMemo(() => {
    if (!live.id) return ''
    return `/api/traffic/cams/${encodeURIComponent(live.id)}/frame?_wb=${imgTick}`
  }, [live.id, imgTick])

  const onPick = (id: string) => {
    const picked = nearby.find((c) => c.id === id)
    if (picked && onSelectCam) onSelectCam(picked)
    else loadCam(id, true)
  }

  return (
    <div className="traffic-cam-panel">
      {nearby.length > 1 && (
        <label className="traffic-cam-picker">
          <span>SELECT CAM</span>
          <select
            value={live.id}
            onChange={(e) => onPick(e.target.value)}
          >
            {nearby.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
                {c.distance_km != null ? ` · ${c.distance_km.toFixed(1)} km` : ''}
              </option>
            ))}
          </select>
        </label>
      )}

      <div className={`traffic-cam-frame${streamMode ? ' traffic-cam-stream' : ''}`}>
        {imageSrc ? (
          <img
            key={imageSrc}
            src={imageSrc}
            alt={live.name}
            className="traffic-cam-live-img"
            onError={() => setError('Image failed — try refresh')}
          />
        ) : (
          <div className="traffic-cam-placeholder">NO IMAGE URL</div>
        )}
        <span className="webcam-live-badge">{streamMode ? 'LIVE STREAM' : 'LIVE'}</span>
      </div>

      {error && <div className="health-status pending traffic-cam-error">{error}</div>}

      <div className="traffic-cam-actions">
        <button type="button" className="refresh-btn" disabled={loading} onClick={() => loadCam(live.id, true)}>
          {loading ? 'LOADING…' : '↻ REFRESH IMAGE'}
        </button>
        {live.image_url && (
          <a className="tp-link" href={live.image_url} target="_blank" rel="noreferrer">
            OPEN FULL ↗
          </a>
        )}
      </div>
      <p className="traffic-cam-meta">
        {live.source} · {live.country} · auto-refresh {Math.round(refreshMs / 1000)}s
      </p>
    </div>
  )
}
