import { useEffect, useState } from 'react'
import type { FocusTarget } from '../lib/focus'
import { fetchApi } from '../lib/networkFetch';

type StacItem = {
  id: string
  collection: string
  datetime: string
  cloud_cover: number | null
  bbox: number[]
  thumbnail: string | null
  proxy_thumbnail: string | null
  cog_visual: string | null
  titiler_tiles?: Record<string, string>
}

type Collection = { id: string; label: string; default_cloud_cover?: number }
type Region = { id: string; label: string; bbox: number[] }

type Catalog = {
  endpoint: string
  titiler_configured: boolean
  collections: Collection[]
  regions: Region[]
}

interface Props {
  onFocus: (f: Omit<FocusTarget, 'ts'>) => void
}

export default function StacPanel({ onFocus }: Props) {
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [collection, setCollection] = useState('sentinel-2-l2a')
  const [region, setRegion] = useState('thailand')
  const [days, setDays] = useState(14)
  const [cloudMax, setCloudMax] = useState(25)
  const [items, setItems] = useState<StacItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selected, setSelected] = useState<StacItem | null>(null)

  useEffect(() => {
    fetchApi('/api/stac/collections')
      .then(r => r.json())
      .then(d => setCatalog(d))
      .catch(e => setError(String(e)))
  }, [])

  const run = async () => {
    setLoading(true); setError(null)
    try {
      const u = new URLSearchParams({
        region, collection, days: String(days), cloud_cover_max: String(cloudMax), limit: '24',
      })
      const r = await fetchApi(`/api/stac/search?${u.toString()}`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const d = await r.json()
      if (d.error) throw new Error(d.error)
      setItems(d.items || [])
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e))
      setItems([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { run() // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [region, collection, days, cloudMax])

  const fmt = (s?: string) => s ? new Date(s).toLocaleString() : '—'
  const bboxCenter = (bbox: number[] | undefined) => {
    if (!bbox || bbox.length !== 4) return null
    return { lon: (bbox[0] + bbox[2]) / 2, lat: (bbox[1] + bbox[3]) / 2 }
  }
  const focusItem = (it: StacItem) => {
    const c = bboxCenter(it.bbox)
    if (!c) return
    onFocus({
      kind: 'satellite_scene',
      lon: c.lon,
      lat: c.lat,
      height: 500000,
      title: `${it.collection} · ${it.id.slice(-12)}`,
      lines: [
        `DATE: ${fmt(it.datetime)}`,
        `CLOUD: ${it.cloud_cover != null ? it.cloud_cover.toFixed(1) + '%' : '—'}`,
        `BBOX: ${it.bbox?.map(n => n.toFixed(2)).join(', ')}`,
      ],
    })
  }

  return (
    <div className="stac-panel">
      <div className="stac-toolbar">
        <label>REGION
          <select value={region} onChange={e => setRegion(e.target.value)}>
            {(catalog?.regions || [{ id: 'thailand', label: 'Thailand' }]).map(r => (
              <option key={r.id} value={r.id}>{r.label}</option>
            ))}
          </select>
        </label>
        <label>COLLECTION
          <select value={collection} onChange={e => setCollection(e.target.value)}>
            {(catalog?.collections || []).map(c => (
              <option key={c.id} value={c.id}>{c.label || c.id}</option>
            ))}
          </select>
        </label>
        <label>DAYS
          <input type="number" min={1} max={180} value={days} onChange={e => setDays(Math.max(1, Math.min(180, Number(e.target.value) || 14)))} style={{ width: 60 }} />
        </label>
        <label>CLOUD MAX %
          <input type="number" min={0} max={100} value={cloudMax} onChange={e => setCloudMax(Math.max(0, Math.min(100, Number(e.target.value) || 25)))} style={{ width: 60 }} />
        </label>
        <button className="data-refresh" onClick={run}>↻ SEARCH</button>
        {catalog && (
          <span className="stac-meta">
            {catalog.titiler_configured ? 'TiTiler ✓' : 'static thumbs only'} · upstream: <code>{catalog.endpoint.replace('https://', '')}</code>
          </span>
        )}
      </div>

      {error && <div className="data-error">STAC search: {error}</div>}
      {loading && <div className="data-info">Searching {collection} over {region}…</div>}
      {!loading && items.length === 0 && !error && (
        <div className="data-info">No scenes match — relax cloud filter or widen window.</div>
      )}

      <div className="stac-grid">
        {items.map(it => (
          <div key={it.id} className={`stac-card ${selected?.id === it.id ? 'selected' : ''}`} onClick={() => setSelected(it)}>
            {it.proxy_thumbnail ? (
              <img loading="lazy" src={it.proxy_thumbnail} alt={it.id} />
            ) : (
              <div className="stac-no-thumb">NO PREVIEW</div>
            )}
            <div className="stac-meta-line">
              <span className="stac-date">{fmt(it.datetime).slice(0, 16)}</span>
              <span className={`stac-cloud ${(it.cloud_cover ?? 0) > 50 ? 'high' : (it.cloud_cover ?? 0) > 20 ? 'mid' : 'low'}`}>
                ☁ {it.cloud_cover != null ? it.cloud_cover.toFixed(0) + '%' : '—'}
              </span>
            </div>
            <div className="stac-actions">
              <button className="locate-mini" onClick={(e) => { e.stopPropagation(); focusItem(it) }}>◎</button>
              {it.cog_visual && (
                <a className="stac-cog" href={it.cog_visual} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}>COG ↗</a>
              )}
            </div>
          </div>
        ))}
      </div>

      {selected && (
        <div className="stac-detail">
          <div className="stac-detail-head">
            <strong>{selected.id}</strong>
            <button onClick={() => setSelected(null)}>✕</button>
          </div>
          <div className="stac-detail-rows">
            <div>Collection: <code>{selected.collection}</code></div>
            <div>Datetime: {fmt(selected.datetime)}</div>
            <div>Cloud cover: {selected.cloud_cover != null ? selected.cloud_cover.toFixed(2) + '%' : '—'}</div>
            <div>BBox: {selected.bbox?.map(n => n.toFixed(3)).join(', ')}</div>
            {selected.titiler_tiles && Object.entries(selected.titiler_tiles).map(([k, url]) => (
              <div key={k}>TiTiler {k}: <code title={url}>{url.slice(0, 60)}…</code></div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
