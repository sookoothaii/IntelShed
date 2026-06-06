import { useEffect, useRef, useState } from 'react'
import maplibregl, { Map as MapLibreMap, StyleSpecification } from 'maplibre-gl'
import { Protocol, PMTiles } from 'pmtiles'
import { layers as protomapsLayers, namedFlavor } from '@protomaps/basemaps'
import 'maplibre-gl/dist/maplibre-gl.css'

let _protocolRegistered = false

type Archive = {
  name: string
  size_mb: number
  pmtiles_url: string
}
type StatusResponse = {
  available: boolean
  archives: Archive[]
  primary: string | null
}

const FLAVORS = ['dark', 'black', 'grayscale', 'light', 'white'] as const
type FlavorName = (typeof FLAVORS)[number]

export type MapFocus = { lat: number; lon: number; ts?: number } | null

export default function MapPanel({
  focus,
  onCameraMove,
  syncCamera,
}: {
  focus?: MapFocus
  onCameraMove?: (cam: { lon: number; lat: number; zoom: number }) => void
  syncCamera?: { lon: number; lat: number; height?: number; zoom?: number; source: 'globe' | 'map'; ts: number } | null
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const [archives, setArchives] = useState<Archive[]>([])
  const [activeArchive, setActiveArchive] = useState<string>('')
  const [flavor, setFlavor] = useState<FlavorName>('dark')
  const [status, setStatus] = useState<'loading' | 'ready' | 'error' | 'empty'>('loading')
  const [error, setError] = useState<string>('')
  const [showHint, setShowHint] = useState<boolean>(false)

  const onCameraMoveRef = useRef(onCameraMove)
  useEffect(() => {
    onCameraMoveRef.current = onCameraMove
  }, [onCameraMove])

  // Protocol handler must be registered exactly once for the app lifecycle.
  useEffect(() => {
    if (_protocolRegistered) return
    const protocol = new Protocol()
    maplibregl.addProtocol('pmtiles', protocol.tile)
    _protocolRegistered = true
  }, [])

  useEffect(() => {
    let cancelled = false
    fetch('/api/pmtiles/status')
      .then((r) => r.json())
      .then((data: StatusResponse) => {
        if (cancelled) return
        if (!data.available || !data.archives?.length) {
          setStatus('empty')
          return
        }
        setArchives(data.archives)
        const preferred =
          data.archives.find((a) => a.name === 'thailand') ||
          data.archives.find((a) => a.name === 'planet_z6') ||
          data.archives[0]
        setActiveArchive(preferred.name)
        setStatus('ready')
      })
      .catch((e) => {
        if (cancelled) return
        setStatus('error')
        setError(String(e?.message || e))
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!containerRef.current || !activeArchive || status !== 'ready') return
    let cancelled = false

    const init = async () => {
      const archive = archives.find((a) => a.name === activeArchive)
      if (!archive) return

      // Absolute URL so the pmtiles:// fetcher resolves correctly during dev (Vite proxy)
      const pmtilesUrl = `${window.location.origin}${archive.pmtiles_url}`

      let centerLon = 100
      let centerLat = 13
      let initZoom = 2
      let maxZoom = 14
      try {
        const p = new PMTiles(pmtilesUrl)
        const header = await p.getHeader()
        centerLon = header.centerLon
        centerLat = header.centerLat
        maxZoom = header.maxZoom
        initZoom = Math.max(1, Math.min(header.maxZoom - 2, 6))
      } catch (err) {
        console.warn('[MapPanel] PMTiles header read failed', err)
      }
      if (cancelled) return

      const flv = namedFlavor(flavor)
      const style: StyleSpecification = {
        version: 8,
        glyphs: 'https://cdn.protomaps.com/fonts/pbf/{fontstack}/{range}.pbf',
        sources: {
          protomaps: {
            type: 'vector',
            url: `pmtiles://${pmtilesUrl}`,
            attribution:
              '<a href="https://protomaps.com">Protomaps</a> © <a href="https://openstreetmap.org">OpenStreetMap</a>',
          },
        },
        layers: protomapsLayers('protomaps', flv, { lang: 'en' }),
      }

      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
      }

      const map = new maplibregl.Map({
        container: containerRef.current!,
        style,
        center: [centerLon, centerLat],
        zoom: initZoom,
        maxZoom: maxZoom,
        attributionControl: { compact: true },
      })
      map.addControl(new maplibregl.NavigationControl({ showCompass: true }), 'top-right')
      map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: 'metric' }), 'bottom-right')
      mapRef.current = map

      map.on('moveend', () => {
        const center = map.getCenter()
        onCameraMoveRef.current?.({
          lon: center.lng,
          lat: center.lat,
          zoom: map.getZoom(),
        })
      })

      map.on('error', (e) => {
        console.warn('[MapPanel] map error', e?.error || e)
      })
    }

    init()

    return () => {
      cancelled = true
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
      }
    }
  }, [archives, activeArchive, flavor, status])

  useEffect(() => {
    if (!focus || !mapRef.current) return
    const target: [number, number] = [focus.lon, focus.lat]
    const currZoom = mapRef.current.getZoom()
    mapRef.current.flyTo({
      center: target,
      zoom: Math.max(currZoom, 7),
      duration: 900,
      essential: true,
    })
  }, [focus?.ts, focus?.lat, focus?.lon])

  useEffect(() => {
    if (!syncCamera || syncCamera.source === 'map' || !mapRef.current) return
    const zoom = syncCamera.zoom ?? (syncCamera.height ? Math.max(1, Math.log2(40000000 / syncCamera.height)) : 4)
    mapRef.current.flyTo({
      center: [syncCamera.lon, syncCamera.lat],
      zoom,
      duration: 100, // fast sync
    })
  }, [syncCamera])

  const archive = archives.find((a) => a.name === activeArchive)

  return (
    <div className="map-wrap">
      <div ref={containerRef} className="map-canvas" />

      <div className="map-controls">
        <div className="map-title">PMTILES BASEMAP</div>

        <div className="map-row">
          <span className="map-label">ARCHIVE</span>
          {archives.length === 0 ? (
            <span className="map-val">—</span>
          ) : (
            <select value={activeArchive} onChange={(e) => setActiveArchive(e.target.value)}>
              {archives.map((a) => (
                <option key={a.name} value={a.name}>
                  {a.name} · {a.size_mb} MB
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="map-row">
          <span className="map-label">STYLE</span>
          <select value={flavor} onChange={(e) => setFlavor(e.target.value as FlavorName)}>
            {FLAVORS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </div>

        {archive && (
          <div className="map-row sub">
            <span className="map-label">PATH</span>
            <span className="map-val" title={archive.pmtiles_url}>
              {archive.pmtiles_url}
            </span>
          </div>
        )}

        <button
          className="map-hint-toggle"
          onClick={() => setShowHint((v) => !v)}
          type="button"
        >
          {showHint ? 'hide' : 'how to add more'}
        </button>

        {showHint && (
          <div className="map-hint">
            <div>
              <code>{`.\\scripts\\download-pmtiles.ps1 -Region world-z10`}</code>
              <span className="map-hint-note">~1 GB global detail</span>
            </div>
            <div>
              <code>{`.\\scripts\\download-pmtiles.ps1 -Region asean`}</code>
              <span className="map-hint-note">~regional Asia bbox</span>
            </div>
          </div>
        )}

        {status === 'error' && <div className="map-error">ERROR: {error}</div>}
        {status === 'empty' && (
          <div className="map-error">
            <strong>No PMTiles archives found.</strong>
            <br />
            Run from project root:
            <br />
            <code>{`.\\scripts\\download-pmtiles.ps1 -Region stack`}</code>
          </div>
        )}
      </div>
    </div>
  )
}
