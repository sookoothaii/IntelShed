import { useState, useEffect, useCallback } from 'react'
import { fetchApi } from '../lib/networkFetch'
import type { FocusTarget } from '../lib/focus'

interface AnomalyFeature {
  type: 'Feature'
  geometry: {
    type: 'Polygon'
    coordinates: number[][][]
  }
  properties: {
    class: 'increase' | 'decrease'
    mean_delta: number
    max_delta: number
    min_delta: number
    pixel_count: number
    confidence: number
  }
}

interface ChangeResult {
  type: 'FeatureCollection'
  properties: {
    before_id: string
    after_id: string
    before_scene?: { id: string; datetime?: string; cloud_cover?: number }
    after_scene?: { id: string; datetime?: string; cloud_cover?: number }
    index: string
    threshold: number
    feature_count: number
    total_pixels: number
    bbox: number[]
    crs: string
    resolution: number
  }
  features: AnomalyFeature[]
  cached?: boolean
  cached_at?: string
}

interface SatelliteHealth {
  enabled: boolean
  rasterio_available: boolean
  collections: string[]
}

const REGIONS = [
  { id: 'bangkok', label: 'Bangkok metro' },
  { id: 'phuket', label: 'Phuket / Andaman coast' },
  { id: 'thailand', label: 'Thailand (full country)' },
  { id: 'mekong-delta', label: 'Mekong Delta' },
  { id: 'asean', label: 'Southeast Asia' },
  { id: 'germany', label: 'Germany' },
  { id: 'rhein', label: 'Rhein corridor' },
]

function formatDateInput(d: Date): string {
  return d.toISOString().split('T')[0]
}

function polygonCentroid(coords: number[][][]): { lat: number; lon: number } | null {
  const ring = coords[0]
  if (!ring || ring.length === 0) return null
  let lat = 0
  let lon = 0
  let n = 0
  for (const [x, y] of ring) {
    lon += x
    lat += y
    n += 1
  }
  return n === 0 ? null : { lat: lat / n, lon: lon / n }
}

export default function SatellitePanel({
  onFocus,
}: {
  onFocus: (f: Omit<FocusTarget, 'ts'>) => void
}) {
  const [health, setHealth] = useState<SatelliteHealth | null>(null)
  const [region, setRegion] = useState('bangkok')
  const [before, setBefore] = useState(() => {
    const d = new Date()
    d.setDate(d.getDate() - 60)
    return formatDateInput(d)
  })
  const [after, setAfter] = useState(() => formatDateInput(new Date()))
  const [index, setIndex] = useState('ndvi')
  const [threshold, setThreshold] = useState(0.2)
  const [resolution, setResolution] = useState(60)
  const [cloudCover, setCloudCover] = useState(25)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<ChangeResult | null>(null)

  const loadHealth = useCallback(async () => {
    try {
      const r = await fetchApi('/api/satellite/health')
      if (r.ok) setHealth(await r.json())
    } catch {
      // ignore
    }
  }, [])

  useEffect(() => {
    loadHealth()
  }, [loadHealth])

  const handleRun = async () => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const params = new URLSearchParams({
        region,
        before,
        after,
        index,
        threshold: String(threshold),
        resolution: String(resolution),
        cloud_cover_max: String(cloudCover),
      })
      const r = await fetchApi(`/api/satellite/change?${params.toString()}`)
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        throw new Error(body.detail || `${r.status} ${r.statusText}`)
      }
      setResult(await r.json())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const focusAnomaly = (f: AnomalyFeature) => {
    const c = polygonCentroid(f.geometry.coordinates)
    if (!c) return
    const props = f.properties
    onFocus({
      kind: 'satellite_change',
      lon: c.lon,
      lat: c.lat,
      height: 30000,
      title: `Satellite ${props.class} (${props.mean_delta > 0 ? '+' : ''}${props.mean_delta.toFixed(2)})`,
      lines: [
        `CLASS: ${props.class.toUpperCase()}`,
        `MEAN DELTA: ${props.mean_delta.toFixed(4)}`,
        `MAX DELTA: ${props.max_delta.toFixed(4)}`,
        `PIXELS: ${props.pixel_count}`,
        `CONFIDENCE: ${(props.confidence * 100).toFixed(1)}%`,
      ],
    })
  }

  const tagStyle = (color: string) => ({
    padding: '2px 6px',
    borderRadius: 4,
    fontSize: 11,
    background: color + '22',
    color,
    marginRight: 4,
    display: 'inline-block',
  })

  return (
    <div style={{ padding: 12, height: '100%', overflow: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <h2 style={{ margin: 0, fontSize: 16, color: '#00e5a0' }}>SATELLITE CHANGE DETECTION</h2>
        {health && (
          <span
            style={{
              padding: '2px 6px',
              borderRadius: 4,
              fontSize: 11,
              background: health.rasterio_available ? '#00e5a022' : '#ff4d5e22',
              color: health.rasterio_available ? '#00e5a0' : '#ff4d5e',
            }}
          >
            {health.rasterio_available ? 'rasterio ready' : 'rasterio unavailable'}
          </span>
        )}
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <select
          value={region}
          onChange={(e) => setRegion(e.target.value)}
          style={{ padding: 4, background: '#0b1d1d', color: '#b0c4bf', border: '1px solid #1e3a3a' }}
        >
          {REGIONS.map((r) => (
            <option key={r.id} value={r.id}>
              {r.label}
            </option>
          ))}
        </select>
        <select
          value={index}
          onChange={(e) => setIndex(e.target.value)}
          style={{ padding: 4, background: '#0b1d1d', color: '#b0c4bf', border: '1px solid #1e3a3a' }}
        >
          <option value="ndvi">NDVI (vegetation)</option>
          <option value="ndwi">NDWI (water)</option>
        </select>
        <input
          type="date"
          value={before}
          onChange={(e) => setBefore(e.target.value)}
          style={{ padding: 4, background: '#0b1d1d', color: '#b0c4bf', border: '1px solid #1e3a3a' }}
        />
        <input
          type="date"
          value={after}
          onChange={(e) => setAfter(e.target.value)}
          style={{ padding: 4, background: '#0b1d1d', color: '#b0c4bf', border: '1px solid #1e3a3a' }}
        />
        <input
          type="number"
          min={0.05}
          max={1}
          step={0.05}
          value={threshold}
          onChange={(e) => setThreshold(Number(e.target.value))}
          title="threshold"
          style={{ padding: 4, width: 70, background: '#0b1d1d', color: '#b0c4bf', border: '1px solid #1e3a3a' }}
        />
        <input
          type="number"
          min={10}
          max={500}
          step={10}
          value={resolution}
          onChange={(e) => setResolution(Number(e.target.value))}
          title="resolution (m)"
          style={{ padding: 4, width: 80, background: '#0b1d1d', color: '#b0c4bf', border: '1px solid #1e3a3a' }}
        />
        <input
          type="number"
          min={0}
          max={100}
          step={5}
          value={cloudCover}
          onChange={(e) => setCloudCover(Number(e.target.value))}
          title="max cloud %"
          style={{ padding: 4, width: 70, background: '#0b1d1d', color: '#b0c4bf', border: '1px solid #1e3a3a' }}
        />
        <button onClick={handleRun} disabled={loading} style={{ padding: '4px 10px' }}>
          {loading ? 'Running…' : 'Run change detection'}
        </button>
      </div>

      {error && (
        <div style={{ padding: 8, marginBottom: 12, border: '1px solid #ff4d5e', color: '#ff4d5e', borderRadius: 4 }}>
          {error}
        </div>
      )}

      {result && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 12, color: '#6f8c84', marginBottom: 8 }}>
            Scenes: {result.properties.before_scene?.id} → {result.properties.after_scene?.id} ·
            Index: {result.properties.index} · Threshold: {result.properties.threshold} ·
            Resolution: {result.properties.resolution}m ·
            Features: {result.properties.feature_count} ·
            Pixels: {result.properties.total_pixels}
            {result.cached && ' · cached'}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {result.features.map((f, i) => (
              <div
                key={i}
                style={{
                  border: '1px solid #1e3a3a',
                  borderRadius: 6,
                  padding: 10,
                  background: '#0b1d1d',
                  borderLeft: `3px solid ${f.properties.class === 'increase' ? '#00e5a0' : '#ff4d5e'}`,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <span style={tagStyle(f.properties.class === 'increase' ? '#00e5a0' : '#ff4d5e')}>
                    {f.properties.class.toUpperCase()}
                  </span>
                  <span style={{ color: '#b0c4bf', fontSize: 13, fontWeight: 600 }}>
                    Δ {f.properties.mean_delta > 0 ? '+' : ''}
                    {f.properties.mean_delta.toFixed(3)}
                  </span>
                  <span style={{ color: '#6f8c84', fontSize: 11 }}>
                    {f.properties.pixel_count} pixels
                  </span>
                  <span style={tagStyle('#ffd23f')}>conf {(f.properties.confidence * 100).toFixed(0)}%</span>
                  <button
                    onClick={() => focusAnomaly(f)}
                    style={{ padding: '2px 8px', fontSize: 11, marginLeft: 'auto' }}
                  >
                    ◎ LOCATE
                  </button>
                </div>
                <div style={{ fontSize: 11, color: '#6f8c84' }}>
                  min {f.properties.min_delta.toFixed(3)} · max {f.properties.max_delta.toFixed(3)}
                </div>
              </div>
            ))}
            {result.features.length === 0 && (
              <div style={{ color: '#6f8c84' }}>No anomalies detected with current threshold.</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
