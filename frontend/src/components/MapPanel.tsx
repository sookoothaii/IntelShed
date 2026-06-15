import { useEffect, useRef, useState } from 'react'
import maplibregl, { Map as MapLibreMap, StyleSpecification } from 'maplibre-gl'
import { Protocol, PMTiles } from 'pmtiles'
import { layers as protomapsLayers, namedFlavor } from '@protomaps/basemaps'
import 'maplibre-gl/dist/maplibre-gl.css'
import type { MapViewMode } from '../lib/mapView'
import { DEFAULT_MAP_VIEW, ESRI_HILLSHADE_TILES, ESRI_SATELLITE_TILES } from '../lib/mapView'
import {
  containerHasSize,
  globeHeightToZoom,
  sanitizeLonLat,
} from '../lib/cameraSync'

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

/** Archives above this size are manual-only — too heavy for auto-default. */
const PLANET_FULL_MB = 95_000

/** Prefer small global archive for smooth pan/zoom; never auto-select planet_full. */
function pickArchive(archives: Archive[]): Archive {
  const byName = (name: string) => archives.find((a) => a.name === name)
  const small = archives.filter((a) => a.name !== 'planet_full' && a.size_mb < PLANET_FULL_MB)
  const pool = small.length ? small : archives
  return (
    byName('planet_z6') ||
    byName('thailand') ||
    pool.find((a) => a.name !== 'planet_full') ||
    archives[0]
  )
}

function isHeavyArchive(archive: Archive | undefined): boolean {
  return !!archive && archive.size_mb >= PLANET_FULL_MB
}

const FLAVORS = ['dark', 'black', 'grayscale', 'light', 'white'] as const
type FlavorName = (typeof FLAVORS)[number]

/** Protomaps basemap assets (glyphs + flavor-matched sprites). */
const GLYPHS = 'https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf'
const SPRITE_BY_FLAVOR: Record<FlavorName, string> = {
  dark: 'https://protomaps.github.io/basemaps-assets/sprites/v4/dark',
  black: 'https://protomaps.github.io/basemaps-assets/sprites/v4/black',
  grayscale: 'https://protomaps.github.io/basemaps-assets/sprites/v4/grayscale',
  light: 'https://protomaps.github.io/basemaps-assets/sprites/v4/light',
  white: 'https://protomaps.github.io/basemaps-assets/sprites/v4/white',
}

function installStyleImageFallback(map: MapLibreMap) {
  map.on('styleimagemissing', (e) => {
    if (map.hasImage(e.id)) return
    const dot = e.id === 'capital' || e.id === 'townspot'
    const size = dot ? 10 : 22
    const data = new Uint8Array(size * size * 4)
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        const dx = x - size / 2 + 0.5
        const dy = y - size / 2 + 0.5
        const inside = dx * dx + dy * dy <= (size / 2 - 0.5) ** 2
        const o = (y * size + x) * 4
        if (!inside) continue
        if (e.id === 'capital') {
          data[o] = 255; data[o + 1] = 210; data[o + 2] = 60; data[o + 3] = 255
        } else if (e.id === 'townspot') {
          data[o] = 180; data[o + 1] = 180; data[o + 2] = 180; data[o + 3] = 220
        } else {
          data[o] = 90; data[o + 1] = 110; data[o + 2] = 130; data[o + 3] = 200
        }
      }
    }
    map.addImage(e.id, { width: size, height: size, data }, { pixelRatio: 1 })
  })
}

export type MapFocus = { lat: number; lon: number; ts?: number } | null

const VECTOR_LAYER_PREFIX = 'protomaps-'
const BUILDINGS_LAYER_ID = 'wb-buildings-3d'

function applyMapModeToMap(map: MapLibreMap, mode: MapViewMode) {
  const showVector = mode.basemap === 'streets' || mode.basemap === 'hybrid'
  const showSat = mode.basemap === 'satellite' || mode.basemap === 'hybrid'
  const showHill = mode.basemap === 'terrain'

  for (const layer of map.getStyle().layers || []) {
    const src = 'source' in layer ? layer.source : null
    if (layer.id.startsWith(VECTOR_LAYER_PREFIX) || src === 'protomaps') {
      if (layer.id === BUILDINGS_LAYER_ID) continue
      map.setLayoutProperty(layer.id, 'visibility', showVector ? 'visible' : 'none')
    }
  }

  const setVis = (id: string, on: boolean) => {
    if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none')
  }
  setVis('wb-satellite', showSat)
  setVis('wb-hillshade', showHill)

  if (map.getLayer(BUILDINGS_LAYER_ID)) {
    map.setLayoutProperty(BUILDINGS_LAYER_ID, 'visibility', mode.buildings && mode.render3d ? 'visible' : 'none')
  }

  const pitch = mode.render3d ? 60 : 0
  const bearing = mode.render3d ? map.getBearing() : 0
  map.easeTo({ pitch, bearing, duration: 500 })
}

export default function MapPanel({
  focus,
  onCameraMove,
  syncCamera,
  mapMode = DEFAULT_MAP_VIEW,
}: {
  focus?: MapFocus
  onCameraMove?: (cam: { lon: number; lat: number; zoom: number; pitch?: number }) => void
  syncCamera?: { lon: number; lat: number; height?: number; zoom?: number; pitch?: number; source: 'globe' | 'map'; ts: number } | null
  mapMode?: MapViewMode
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const mapModeRef = useRef(mapMode)
  useEffect(() => { mapModeRef.current = mapMode }, [mapMode])

  const [archives, setArchives] = useState<Archive[]>([])
  const [activeArchive, setActiveArchive] = useState<string>('')
  const [flavor, setFlavor] = useState<FlavorName>('dark')
  const [status, setStatus] = useState<'loading' | 'ready' | 'error' | 'empty'>('loading')
  const [mapBooting, setMapBooting] = useState(false)
  const [error, setError] = useState<string>('')
  const [showHint, setShowHint] = useState<boolean>(false)

  const onCameraMoveRef = useRef(onCameraMove)
  const cameraSyncingRef = useRef(false)
  useEffect(() => {
    onCameraMoveRef.current = onCameraMove
  }, [onCameraMove])

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
        setActiveArchive(pickArchive(data.archives).name)
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
    let resizeObserver: ResizeObserver | null = null

    const init = async () => {
      if (cancelled || !containerRef.current) return
      if (!containerHasSize(containerRef.current)) {
        requestAnimationFrame(() => { if (!cancelled) init() })
        return
      }
      const archive = archives.find((a) => a.name === activeArchive)
      if (!archive) return

      setMapBooting(true)
      const pmtilesUrl = `${window.location.origin}${archive.pmtiles_url}`
      const heavy = isHeavyArchive(archive)

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
      const vectorLayers = protomapsLayers('protomaps', flv, { lang: 'en' }).map((layer) => ({
        ...layer,
        id: `${VECTOR_LAYER_PREFIX}${layer.id}`,
      }))

      const style: StyleSpecification = {
        version: 8,
        glyphs: GLYPHS,
        sprite: SPRITE_BY_FLAVOR[flavor],
        sources: {
          protomaps: {
            type: 'vector',
            url: `pmtiles://${pmtilesUrl}`,
            attribution:
              '<a href="https://protomaps.com">Protomaps</a> © <a href="https://openstreetmap.org">OpenStreetMap</a>',
          },
          'wb-satellite': {
            type: 'raster',
            tiles: [ESRI_SATELLITE_TILES],
            tileSize: 256,
            attribution: 'Esri, Maxar',
            maxzoom: 19,
          },
          'wb-hillshade': {
            type: 'raster',
            tiles: [ESRI_HILLSHADE_TILES],
            tileSize: 256,
            attribution: 'Esri',
            maxzoom: 15,
          },
        },
        layers: [
          { id: 'wb-satellite', type: 'raster', source: 'wb-satellite', layout: { visibility: 'none' } },
          { id: 'wb-hillshade', type: 'raster', source: 'wb-hillshade', layout: { visibility: 'none' } },
          ...vectorLayers,
          {
            id: BUILDINGS_LAYER_ID,
            type: 'fill-extrusion',
            source: 'protomaps',
            'source-layer': 'buildings',
            filter: ['>', ['coalesce', ['get', 'render_height'], 0], 0],
            layout: { visibility: 'none' },
            paint: {
              'fill-extrusion-color': '#1e2d3d',
              'fill-extrusion-height': ['coalesce', ['get', 'render_height'], 12],
              'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
              'fill-extrusion-opacity': 0.88,
            },
          },
        ],
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
        maxZoom: heavy ? Math.min(maxZoom, 12) : maxZoom,
        pitch: mapModeRef.current.render3d ? 60 : 0,
        bearing: 0,
        dragRotate: true,
        pitchWithRotate: true,
        fadeDuration: 0,
        renderWorldCopies: false,
        maxTileCacheSize: heavy ? 32 : 64,
        attributionControl: { compact: true },
      })
      installStyleImageFallback(map)
      map.addControl(new maplibregl.NavigationControl({ showCompass: true, visualizePitch: true }), 'top-right')
      map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: 'metric' }), 'bottom-right')
      mapRef.current = map

      map.on('load', () => {
        applyMapModeToMap(map, mapModeRef.current)
      })

      map.once('idle', () => {
        if (!cancelled) setMapBooting(false)
      })

      map.on('moveend', () => {
        if (cameraSyncingRef.current) return
        const center = map.getCenter()
        const pos = sanitizeLonLat(center.lng, center.lat)
        if (!pos) return
        onCameraMoveRef.current?.({
          lon: pos.lon,
          lat: pos.lat,
          zoom: map.getZoom(),
          pitch: map.getPitch(),
        })
      })

      resizeObserver = new ResizeObserver(() => {
        if (!containerRef.current || !mapRef.current) return
        if (!containerHasSize(containerRef.current)) return
        try {
          mapRef.current.resize()
        } catch {
          /* ignore during teardown */
        }
      })
      resizeObserver.observe(containerRef.current!)

      map.on('error', (e) => {
        console.warn('[MapPanel] map error', e?.error || e)
      })
    }

    init()

    return () => {
      cancelled = true
      setMapBooting(false)
      resizeObserver?.disconnect()
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
      }
    }
  }, [archives, activeArchive, flavor, status])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !map.isStyleLoaded()) return
    applyMapModeToMap(map, mapMode)
  }, [mapMode])

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
    if (!containerHasSize(containerRef.current)) return
    const pos = sanitizeLonLat(syncCamera.lon, syncCamera.lat)
    if (!pos) return
    const zoom = syncCamera.zoom ?? globeHeightToZoom(syncCamera.height ?? 400_000)
    const pitch = Number.isFinite(syncCamera.pitch)
      ? Math.min(85, Math.max(0, syncCamera.pitch!))
      : (mapMode.render3d ? 60 : 0)
    cameraSyncingRef.current = true
    mapRef.current.jumpTo({
      center: [pos.lon, pos.lat],
      zoom: Math.min(22, Math.max(0, zoom)),
      pitch,
    })
    requestAnimationFrame(() => {
      cameraSyncingRef.current = false
    })
  }, [syncCamera, mapMode.render3d])

  const archive = archives.find((a) => a.name === activeArchive)
  const heavyArchive = isHeavyArchive(archive)

  return (
    <div className="map-wrap">
      <div ref={containerRef} className="map-canvas" />

      {mapBooting && (
        <div className="map-loading" aria-live="polite">
          <span className="map-loading-spin" aria-hidden />
          {heavyArchive ? 'Loading large archive…' : 'Loading basemap…'}
        </div>
      )}

      <div className="map-controls">
        <div className="map-title">PMTILES BASEMAP</div>

        <div className="map-row">
          <span className="map-label">ARCHIVE</span>
          {archives.length === 0 ? (
            <span className="map-val">—</span>
          ) : (
            <select
              value={activeArchive}
              onChange={(e) => setActiveArchive(e.target.value)}
              title={heavyArchive ? 'Large archive — first pan/zoom may be slow' : undefined}
            >
              {archives.map((a) => (
                <option key={a.name} value={a.name}>
                  {a.name} · {a.size_mb >= 1024 ? `${(a.size_mb / 1024).toFixed(1)} GB` : `${a.size_mb} MB`}
                  {a.size_mb >= PLANET_FULL_MB ? ' ⚠' : ''}
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
