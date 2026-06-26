import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchApi } from '../lib/networkFetch'
import type { FocusTarget } from '../lib/focus'
import { PRIMARY_EDGE_NODE } from './EdgePanel'

type Reference = { lat: number; lon: number; label: string; source: string }

type WildfireRow = {
  lat: number
  lon: number
  confidence: number
  confidence_label?: string
  frp?: number
  acq_date?: string
  zone?: string
  distance_km?: number
  satellite?: string
  brightness?: number
}

type WildfiresPayload = {
  count: number
  regional_count?: number
  global_count?: number
  matched_count?: number
  region_label?: string
  updated?: string
  fires: WildfireRow[]
  reference?: Reference | null
  filters?: { zone?: string; sort?: string; max_km?: number | null; limit?: number; offset?: number }
}

const PAGE_SIZE = 50

function formatDistance(km: number | undefined): string {
  if (km == null || !Number.isFinite(km)) return '—'
  if (km < 1) return '<1 km'
  if (km < 100) return `${Math.round(km)} km`
  if (km < 1000) return `${km.toFixed(0)} km`
  return `${(km / 1000).toFixed(1)} Mm`
}

function confColor(conf: number): string {
  if (conf >= 80) return '#ff2d00'
  if (conf >= 50) return '#ff6b35'
  return '#ffd23f'
}

async function resolveMeshReference(): Promise<Reference | null> {
  try {
    const r = await fetchApi('/api/nodes')
    if (!r.ok) return null
    const data = await r.json()
    const pi = (data.nodes || []).find((n: Record<string, unknown>) => n.node_id === PRIMARY_EDGE_NODE)
    if (!pi) return null

    const meshWithGps = (pi.mesh || []).find(
      (m: Record<string, unknown>) => m.lat != null && m.lon != null && Number.isFinite(Number(m.lat)) && Number.isFinite(Number(m.lon)),
    )
    if (meshWithGps) {
      return {
        lat: Number(meshWithGps.lat),
        lon: Number(meshWithGps.lon),
        label: meshWithGps.name ? `Meshtastic ${meshWithGps.name}` : 'Meshtastic tracker',
        source: 'mesh',
      }
    }

    if (pi.lat != null && pi.lon != null && pi.online) {
      return {
        lat: Number(pi.lat),
        lon: Number(pi.lon),
        label: 'Pi edge GPS',
        source: 'pi',
      }
    }
  } catch {
    /* fail-soft */
  }
  return null
}

export default function WildfiresPanel({ onFocus }: { onFocus: (f: Omit<FocusTarget, 'ts'>) => void }) {
  const [reference, setReference] = useState<Reference | null>(null)
  const [payload, setPayload] = useState<WildfiresPayload | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [zone, setZone] = useState<'all' | 'regional' | 'global'>('regional')
  const [sort, setSort] = useState<'distance' | 'confidence' | 'frp'>('distance')
  const [maxKm, setMaxKm] = useState<string>('2000')
  const [minConf, setMinConf] = useState('0')
  const [searchQ, setSearchQ] = useState('')
  const [offset, setOffset] = useState(0)
  const [debouncedQ, setDebouncedQ] = useState('')

  useEffect(() => {
    resolveMeshReference().then(setReference)
  }, [])

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedQ(searchQ.trim()), 300)
    return () => window.clearTimeout(t)
  }, [searchQ])

  useEffect(() => {
    setOffset(0)
  }, [zone, sort, maxKm, minConf, debouncedQ, reference?.lat, reference?.lon])

  const load = useCallback(async (nextOffset = offset) => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      params.set('zone', zone)
      params.set('sort', sort)
      params.set('limit', String(PAGE_SIZE))
      params.set('offset', String(nextOffset))
      const min = Number(minConf)
      if (Number.isFinite(min) && min > 0) params.set('min_confidence', String(min))
      const mk = Number(maxKm)
      if (Number.isFinite(mk) && mk > 0) params.set('max_km', String(mk))
      if (debouncedQ) params.set('q', debouncedQ)
      if (reference) {
        params.set('near_lat', String(reference.lat))
        params.set('near_lon', String(reference.lon))
      }

      const r = await fetchApi(`/api/wildfires?${params.toString()}`)
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
      const data: WildfiresPayload = await r.json()
      setPayload(data)
      if (!reference && data.reference?.lat != null && data.reference?.lon != null) {
        setReference({
          lat: data.reference.lat,
          lon: data.reference.lon,
          label: data.reference.label || 'Operator reference',
          source: data.reference.source || 'operator_env',
        })
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [zone, sort, maxKm, minConf, debouncedQ, reference, offset])

  useEffect(() => {
    load(offset)
  }, [load, offset])

  const matched = payload?.matched_count ?? payload?.fires?.length ?? 0
  const hasMore = matched > offset + (payload?.fires?.length ?? 0)

  const summary = useMemo(() => {
    if (!payload) return ''
    const parts = [
      `${payload.regional_count ?? 0} ASEAN`,
      `${payload.global_count ?? 0} global`,
      `${payload.count ?? 0} total`,
    ]
    if (payload.matched_count != null) {
      parts.push(`${payload.matched_count} matched`)
    }
    return parts.join(' · ')
  }, [payload])

  return (
    <section className="wildfires-panel">
      <div className="wildfires-ref">
        {reference ? (
          <>
            <span className="wildfires-ref-label">YOUR POSITION</span>
            <strong>{reference.label}</strong>
            <span className="wildfires-ref-coords">
              {reference.lat.toFixed(4)}°, {reference.lon.toFixed(4)}°
            </span>
          </>
        ) : (
          <span className="wildfires-ref-pending">Resolving mesh GPS from Pi…</span>
        )}
      </div>

      <div className="wildfires-toolbar">
        <input
          className="data-search"
          placeholder="Search lat/lon…"
          value={searchQ}
          onChange={(e) => setSearchQ(e.target.value)}
        />
        <select className="poi-select" value={zone} onChange={(e) => setZone(e.target.value as typeof zone)}>
          <option value="regional">ASEAN only</option>
          <option value="global">Global only</option>
          <option value="all">All zones</option>
        </select>
        <select className="poi-select" value={sort} onChange={(e) => setSort(e.target.value as typeof sort)}>
          <option value="distance">Sort: distance</option>
          <option value="confidence">Sort: confidence</option>
          <option value="frp">Sort: FRP</option>
        </select>
        <select className="poi-select" value={maxKm} onChange={(e) => setMaxKm(e.target.value)}>
          <option value="">Any distance</option>
          <option value="250">≤ 250 km</option>
          <option value="500">≤ 500 km</option>
          <option value="1000">≤ 1000 km</option>
          <option value="2000">≤ 2000 km</option>
          <option value="5000">≤ 5000 km</option>
        </select>
        <select className="poi-select" value={minConf} onChange={(e) => setMinConf(e.target.value)}>
          <option value="0">Any confidence</option>
          <option value="50">Medium+</option>
          <option value="80">High only</option>
        </select>
        <button type="button" className="data-refresh" onClick={() => load(offset)} disabled={loading}>
          {loading ? '…' : '↻ REFRESH'}
        </button>
      </div>

      {error && <div className="data-error">{error}</div>}
      <span className="data-count">{summary}</span>
      {reference && sort === 'distance' && maxKm && (
        <div className="wildfires-filter-note">
          Showing nearest hotspots within {maxKm} km of {reference.label}
        </div>
      )}

      {payload?.fires?.length === 0 && !loading && (
        <div className="health-status pending">
          No fires match filters — widen max distance or clear search
        </div>
      )}

      <div className="wildfires-list">
        {(payload?.fires || []).map((f, i) => {
          const color = confColor(f.confidence ?? 0)
          const dist = formatDistance(f.distance_km)
          return (
            <div
              key={`${f.lat}-${f.lon}-${offset + i}`}
              className="iss-card wildfires-card"
              style={{ borderLeft: `3px solid ${color}` }}
              onClick={() =>
                f.lon != null &&
                f.lat != null &&
                onFocus({
                  kind: 'wildfire',
                  lon: f.lon,
                  lat: f.lat,
                  height: 400000,
                  title: `Wildfire (${f.confidence_label})`,
                  lines: [
                    reference && f.distance_km != null ? `Distance: ${formatDistance(f.distance_km)}` : '',
                    `Zone: ${f.zone === 'regional' ? 'ASEAN' : 'Global'}`,
                    `Confidence: ${f.confidence}%`,
                    `Brightness: ${f.brightness ?? '—'}K`,
                    `FRP: ${f.frp ?? '—'} MW`,
                    `Satellite: ${f.satellite ?? '—'}`,
                    `Date: ${f.acq_date ?? '—'}`,
                  ].filter(Boolean),
                })
              }
            >
              <div className="wildfires-card-top">
                <span className="wildfires-dist">{dist}</span>
                <span style={{ color, fontWeight: 'bold' }}>{f.confidence_label?.toUpperCase()}</span>
              </div>
              <strong>
                {f.zone === 'regional' ? 'ASEAN' : 'GLOBAL'} · {f.lat?.toFixed(2)}, {f.lon?.toFixed(2)}
              </strong>
              <small style={{ color: '#6f8c84' }}>
                FRP {f.frp ?? '—'} MW · {f.acq_date ?? '—'}
              </small>
            </div>
          )
        })}
      </div>

      <div className="wildfires-pagination">
        <span className="data-count">
          Showing {Math.min(offset + (payload?.fires?.length ?? 0), matched)} of {matched}
        </span>
        {offset > 0 && (
          <button type="button" className="data-refresh" onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
            ← PREV
          </button>
        )}
        {hasMore && (
          <button type="button" className="data-refresh" onClick={() => setOffset(offset + PAGE_SIZE)}>
            LOAD MORE →
          </button>
        )}
      </div>
    </section>
  )
}
