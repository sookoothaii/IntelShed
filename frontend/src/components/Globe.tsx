import { useCallback, useEffect, useRef, useState, type MutableRefObject } from 'react'
import {
  clampCameraHeight,
  containerHasSize,
  mapPitchToCesiumDeg,
  sanitizeLonLat,
  zoomToGlobeHeight,
} from '../lib/cameraSync'
import {
  Viewer,
  Ion,
  Cartesian3,
  Cartesian2,
  Color,
  createOsmBuildingsAsync,
  Cesium3DTileset,
  SceneMode,
  UrlTemplateImageryProvider,
  GeographicTilingScheme,
  CustomDataSource,
  Entity,
  LabelStyle,
  VerticalOrigin,
  
  DistanceDisplayCondition,
  Math as CMath,
  
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  PostProcessStage,
  Cartographic,
  
  MVTDataProvider,
  ImageryLayer,
  JulianDate,
  createWorldImageryAsync,
  IonWorldImageryStyle,
} from 'cesium'

import 'cesium/Build/Cesium/Widgets/widgets.css'
import {
  NVG_FRAGMENT,
  THERMAL_FRAGMENT,
  CRT_FRAGMENT,
  NIGHT_FRAGMENT,
  VISION_MODES,
  type VisionMode,
} from '../lib/visionShaders'
import { POIS } from '../lib/pois'
import type { FocusTarget } from '../lib/focus'
import { AGENT_BUS_LAYER_EVENT, type AgentLayerDetail } from '../lib/agentBus'
import { readHudSessionStore, writeHudSessionField } from '../lib/hudSessionState'
import type { OsintPin } from '../lib/osintPins'
import type { TrafficCamRef } from './TrafficCamPanel'
import type { WebcamStreamRef } from './WebcamStreamPanel'
import GlobeDetailModal from './GlobeDetailModal'
import { useTrailsLayer } from '../hooks/layers/useTrailsLayer';
import { GlobeLayerManager } from '../hooks/layers/GlobeLayerManager';

import { canFetch } from '../lib/networkFetch';
import { createTerrainWithFallback, attachTerrainFailover } from '../lib/cesiumTerrain';

import type { MapViewMode } from '../lib/mapView'
import { DEFAULT_MAP_VIEW, ESRI_HILLSHADE_TILES, ESRI_REFERENCE_LABELS, ESRI_SATELLITE_TILES, ESRI_STREET_TILES, ION_PHOTOREALISTIC_ASSET, hasCesiumIonToken } from '../lib/mapView'
import { fetchApi } from '../lib/networkFetch';
import { buildEntityHoverTip } from '../lib/entityHoverTip';
import { resolveGlobePick } from '../lib/globePick';
import { attachPulseEllipse, tickPulseAnimations } from '../hooks/layers/pulseAnimation';

const TIMELINE_WINDOWS = [6, 12, 24] as const

// Cesium explicit rendering (requestRenderMode): only paint frames when the scene
// changes, cutting idle CPU/GPU (Cesium docs: ~25% -> ~3% idle). Default ON since
// pulse rings use throttled ConstantProperty updates; rAF pump calls requestRender()
// for camera, motion layers, pulse ticks, and focus ring. Opt out for debug:
// VITE_WORLDBASE_GLOBE_CONTINUOUS_RENDER=1
const GLOBE_CONTINUOUS_RENDER = import.meta.env.VITE_WORLDBASE_GLOBE_CONTINUOUS_RENDER === '1'

// Frame-rate cap: throttle Cesium's render loop to cut GPU power/heat. Pulse rings
// (quakes/nodes/military) are throttled separately (~15 fps via pulseAnimation.ts);
// motion layers (aircraft/sat) still repaint every frame when enabled.
const GLOBE_TARGET_FPS = (() => {
  const raw = import.meta.env.VITE_WORLDBASE_GLOBE_TARGET_FPS
  if (raw == null || raw === '') return 30
  const n = Number(raw)
  return Number.isFinite(n) && n > 0 ? n : 0
})()

// Render-quiescence idle fps (heat lever, env-gated, default OFF). Cesium's
// scene.globe.tilesLoaded stays false forever on this HUD because off-screen preload
// tiles never settle, so requestRenderMode can never idle and the globe repaints at
// the full capped rate even when the visible scene is static (measured idle waste
// ~1,828 draws/s of pixel-identical frames). This controller idles on *visible*
// quiescence instead: when the visible (High) tile queue is empty, the camera is
// idle, and no motion (aircraft/sat) or pulse (quakes/nodes/military) layer, tracked
// entity, or focus ring is active, it throttles targetFrameRate to GLOBE_IDLE_FPS and
// restores instantly on any interaction. Same quality (only a provably static visible
// scene is throttled); measured 30 -> 2 fps cut idle draws ~1,828/s -> ~121/s (~93%).
// Set e.g. to 2; leave unset/<=0 to disable.
const GLOBE_IDLE_FPS = (() => {
  const raw = import.meta.env.VITE_WORLDBASE_GLOBE_IDLE_FPS
  if (raw == null || raw === '') return 0
  const n = Number(raw)
  return Number.isFinite(n) && n > 0 ? n : 0
})()

const GLOBE_IDLE_RESTORE_FPS = GLOBE_TARGET_FPS > 0 ? GLOBE_TARGET_FPS : 60

// How long Cesium's tileLoadProgressEvent must stay silent before the visible scene
// counts as "settled". The event fires only when the tile load queue length changes,
// so silence means tiles are either fully loaded or permanently stalled — in both
// cases the *visible* image will not change from tile loading, so it is safe to idle.
// (The HUD's root level-0 imagery is perpetually stuck TRANSITIONING, so waiting for
// an empty load queue or tilesLoaded=true would never idle — silence is the reliable
// signal.)
const GLOBE_IDLE_TILE_SETTLE_MS = 1500

// Tile-churn suppression: off-screen preload tiles never settle and keep
// tileLoadProgressEvent firing, defeating requestRenderMode idle. Disable
// ancestor/sibling preload at init; drop loadingDescendantLimit to 0 when the
// visible scene is quiescent (same predicate as idle fps, but always on).
const GLOBE_LOADING_DESCENDANT_ACTIVE = 20
const GLOBE_LOADING_DESCENDANT_QUIESCENT = 0

// Globe tile detail (Cesium default 2.0). Was hard-coded 1.0 (~4× tile load); 2.0
// is a free CPU/GPU lever with marginal visual change at globe scale.
const GLOBE_MAX_SSE = (() => {
  const raw = import.meta.env.VITE_WORLDBASE_GLOBE_SSE
  if (raw == null || raw === '') return 2.0
  const n = Number(raw)
  return Number.isFinite(n) && n > 0 ? n : 2.0
})()

// Dynamic SSE: coarser tiles while panning or at high altitude (fewer tile loads).
const GLOBE_SSE_MOVING = 4.0
const GLOBE_SSE_HIGH_ALT = 3.0
const GLOBE_SSE_HIGH_ALT_M = 100_000

const GLOBE_TILE_CACHE_SIZE = (() => {
  const raw = import.meta.env.VITE_WORLDBASE_GLOBE_TILE_CACHE
  if (raw == null || raw === '') return 100
  const n = Number(raw)
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 100
})()

/** Retina GPU lever: skip browser-recommended supersampling; cap internal render scale. */
function globeResolutionScale(): number {
  return window.devicePixelRatio > 1 ? 0.5 : 1.0
}

function timelineCutoffMs(scrubT: number, hours: number): number {
  const now = Date.now()
  const windowMs = hours * 3600 * 1000
  return now - windowMs + scrubT * windowMs
}

function fmtTimelineLabel(ms: number): string {
  return new Date(ms).toLocaleString(undefined, {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function esriImagery(url: string, credit: string) {
  return new UrlTemplateImageryProvider({
    url,
    credit,
    maximumLevel: 19,
  })
}

async function ionWorldImagery(style: IonWorldImageryStyle) {
  return createWorldImageryAsync({ style })
}

async function applyGlobeMapMode(
  viewer: Viewer,
  mode: MapViewMode,
  refs: {
    labelOverlay: MutableRefObject<ImageryLayer | null>
    osmBuildings: MutableRefObject<any>
    photoreal: MutableRefObject<any>
    gibsOverlay: MutableRefObject<ImageryLayer | null>
  },
) {
  const scene = viewer.scene
  scene.mode = mode.render3d ? SceneMode.SCENE3D : SceneMode.SCENE2D

  // --- Basemap (preserve NASA GIBS overlay if active) ---
  const layers = viewer.imageryLayers
  const gibsKeep = refs.gibsOverlay.current
  if (refs.labelOverlay.current) {
    try { layers.remove(refs.labelOverlay.current, false) } catch { /* already removed */ }
    refs.labelOverlay.current = null
  }
  for (let i = layers.length - 1; i >= 0; i--) {
    const layer = layers.get(i)
    if (layer !== gibsKeep) layers.remove(layer, false)
  }

  const useIon = hasCesiumIonToken()
  if (mode.basemap === 'streets') {
    if (useIon) {
      try {
        layers.addImageryProvider(await ionWorldImagery(IonWorldImageryStyle.ROAD))
      } catch (e) {
        console.warn('[Globe] Ion ROAD imagery unavailable, falling back to Esri:', e)
        layers.addImageryProvider(esriImagery(ESRI_STREET_TILES, 'Esri, OpenStreetMap contributors'))
      }
    } else {
      layers.addImageryProvider(esriImagery(ESRI_STREET_TILES, 'Esri, OpenStreetMap contributors'))
    }
  } else if (mode.basemap === 'satellite') {
    if (useIon) {
      try {
        layers.addImageryProvider(await ionWorldImagery(IonWorldImageryStyle.AERIAL))
      } catch (e) {
        console.warn('[Globe] Ion AERIAL imagery unavailable, falling back to Esri:', e)
        layers.addImageryProvider(esriImagery(ESRI_SATELLITE_TILES, 'Esri, Maxar, Earthstar Geographics'))
      }
    } else {
      layers.addImageryProvider(esriImagery(ESRI_SATELLITE_TILES, 'Esri, Maxar, Earthstar Geographics'))
    }
  } else if (mode.basemap === 'hybrid') {
    if (useIon) {
      try {
        layers.addImageryProvider(await ionWorldImagery(IonWorldImageryStyle.AERIAL_WITH_LABELS))
      } catch (e) {
        console.warn('[Globe] Ion AERIAL_WITH_LABELS unavailable, falling back to Esri:', e)
        layers.addImageryProvider(esriImagery(ESRI_SATELLITE_TILES, 'Esri, Maxar, Earthstar Geographics'))
        refs.labelOverlay.current = layers.addImageryProvider(
          esriImagery(ESRI_REFERENCE_LABELS, 'Esri, OpenStreetMap contributors'),
        )
        if (refs.labelOverlay.current) refs.labelOverlay.current.alpha = 0.85
      }
    } else {
      layers.addImageryProvider(esriImagery(ESRI_SATELLITE_TILES, 'Esri, Maxar, Earthstar Geographics'))
      if (refs.labelOverlay.current) {
        layers.remove(refs.labelOverlay.current, false)
        refs.labelOverlay.current = null
      }
      refs.labelOverlay.current = layers.addImageryProvider(
        esriImagery(ESRI_REFERENCE_LABELS, 'Esri, OpenStreetMap contributors'),
      )
      if (refs.labelOverlay.current) refs.labelOverlay.current.alpha = 0.85
    }
  } else {
    layers.addImageryProvider(esriImagery(ESRI_HILLSHADE_TILES, 'Esri World Hillshade'))
    layers.addImageryProvider(esriImagery(ESRI_STREET_TILES, 'Esri, OpenStreetMap contributors'))
    const top = layers.get(layers.length - 1)
    if (top) top.alpha = 0.55
  }

  // --- 3D buildings ---
  if (refs.osmBuildings.current) {
    refs.osmBuildings.current.show = mode.buildings && !mode.photorealistic
  }

  // --- Photorealistic 3D tiles (Ion) ---
  if (mode.photorealistic && Ion.defaultAccessToken) {
    if (!refs.photoreal.current) {
      try {
        const tileset = await Cesium3DTileset.fromIonAssetId(ION_PHOTOREALISTIC_ASSET)
        refs.photoreal.current = tileset
        scene.primitives.add(tileset)
      } catch (e) {
        console.warn('[Globe] Photorealistic 3D unavailable:', e)
      }
    }
    if (refs.photoreal.current) refs.photoreal.current.show = true
  } else if (refs.photoreal.current) {
    refs.photoreal.current.show = false
  }

  // --- 3D camera tilt ---
  if (mode.render3d && scene.mode === SceneMode.SCENE3D) {
    const cam = viewer.camera
    const c = Cartographic.fromCartesian(cam.position)
    if (cam.pitch > -CMath.PI_OVER_FOUR) {
      viewer.camera.flyTo({
        destination: Cartesian3.fromRadians(c.longitude, c.latitude, Math.max(c.height, 800)),
        orientation: {
          heading: cam.heading,
          pitch: CMath.toRadians(-45),
          roll: 0,
        },
        duration: 0.6,
      })
    }
  } else if (!mode.render3d) {
    viewer.camera.flyTo({
      destination: viewer.camera.position,
      orientation: { heading: 0, pitch: CMath.toRadians(-90), roll: 0 },
      duration: 0.5,
    })
  }
}

Ion.defaultAccessToken = import.meta.env.VITE_CESIUM_ION_TOKEN ?? ''
if (!Ion.defaultAccessToken) {
  console.warn('[WorldBase] VITE_CESIUM_ION_TOKEN is not set. Copy frontend/.env.example to frontend/.env and add your Cesium Ion token.')
}

const SAT_GROUPS = [
  { id: 'starlink', label: 'STARLINK' },
  { id: 'stations', label: 'STATIONS' },
  { id: 'gps-ops', label: 'GPS' },
  { id: 'weather', label: 'WEATHER' },
  { id: 'active', label: 'ALL' },
]

const TRANSIT_CITIES = [
  { id: 'berlin', label: 'BERLIN' },
  { id: 'hamburg', label: 'HAMBURG' },
  { id: 'munich', label: 'MUNICH' },
  { id: 'helsinki', label: 'HELSINKI' },
  { id: 'boston', label: 'BOSTON' },
]

type Stats = {
  aircraft: number
  satellites: number
  quakes: number
  events: number
  nodes: number
  military: number
  spaceweather: number
  geopolitics: number
  wildfires: number
  lightning: number
  transit: number
  trafficCams: number
  maritime: number
  gdacs: number
  hazards: number
  outages: number
  volcanoes: number
  airquality: number
  weather: number
  pegel: number
  osint: number
  intelFt: number
  energy: number
  fps: number
}

type GlobeLayers = {
  aircraft: boolean
  satellites: boolean
  orbits: boolean
  quakes: boolean
  events: boolean
  nodes: boolean
  military: boolean
  spaceweather: boolean
  geopolitics: boolean
  wildfires: boolean
  lightning: boolean
  transit: boolean
  trafficCams: boolean
  maritime: boolean
  gdacs: boolean
  hazards: boolean
  outages: boolean
  volcanoes: boolean
  airquality: boolean
  weather: boolean
  pegel: boolean
  energy: boolean
  osint: boolean
  intelFt: boolean
}

type LayerKey = keyof GlobeLayers

// Power-save levers (see briefs/cesium-gpu-thermal-research.md roadmap items 2–5).
const GLOBE_POWER_SAVE_FPS = 1
const GLOBE_ATMOSPHERE_OFF_HEIGHT_M = 2_000_000
const GLOBE_FXAA_IDLE_MS = 3000
const GLOBE_MSAA_WHEN_SUPERSAMPLE = 1

type GlobePowerState = {
  docVisible: boolean
  intersecting: boolean
  interactionIdle: boolean
  cameraMoving: boolean
  cameraHeightM: number
}

function applyGlobePowerSettings(
  viewer: Viewer,
  hudVisible: boolean,
  _layers: GlobeLayers,
  power: GlobePowerState,
) {
  const scene = viewer.scene
  const throttle = !hudVisible || !power.docVisible || !power.intersecting
  const normalFps = GLOBE_TARGET_FPS > 0 ? GLOBE_TARGET_FPS : 0
  viewer.targetFrameRate = throttle ? GLOBE_POWER_SAVE_FPS : normalFps

  if (!GLOBE_CONTINUOUS_RENDER) {
    scene.requestRenderMode = true
    scene.maximumRenderTimeChange = Infinity
  } else {
    scene.requestRenderMode = false
  }

  let sse = GLOBE_MAX_SSE
  if (power.cameraMoving) {
    sse = Math.max(sse, GLOBE_SSE_MOVING)
  } else if (power.cameraHeightM > GLOBE_SSE_HIGH_ALT_M) {
    sse = Math.max(sse, GLOBE_SSE_HIGH_ALT)
  }
  if (scene.globe.maximumScreenSpaceError !== sse) {
    scene.globe.maximumScreenSpaceError = sse
  }

  if (viewer.resolutionScale > 1) {
    scene.msaaSamples = GLOBE_MSAA_WHEN_SUPERSAMPLE
  }

  if (scene.postProcessStages?.fxaa) {
    scene.postProcessStages.fxaa.enabled = !power.interactionIdle
  }

  if (scene.skyAtmosphere) {
    scene.skyAtmosphere.show = power.cameraHeightM < GLOBE_ATMOSPHERE_OFF_HEIGHT_M
  }

  scene.requestRender()
}

type FeedHealth = {
  status?: string
  age_sec?: number
  source?: string | string[]
  count?: number
  error?: string
}

type TelemetryEntry = {
  layer?: LayerKey
  label: string
  statKey?: keyof Stats
  color: string
  hudKey?: string
  healthKeys?: string[]
  formatValue?: (stats: Stats) => string
  /** One-line hover tooltip */
  tip?: string
}

function kpTooltip(kp: number): string {
  if (!kp) return 'Kp index (0–9): geomagnetic activity, 3 h average.'
  if (kp < 2) return `Kp ${kp.toFixed(2)} — quiet, minimal impact on satellites/networks.`
  if (kp < 4) return `Kp ${kp.toFixed(2)} — mildly active, aurora possible.`
  if (kp < 5) return `Kp ${kp.toFixed(2)} — active, HF/GNSS may degrade.`
  if (kp < 6) return `Kp ${kp.toFixed(2)} — minor storm, outages possible.`
  return `Kp ${kp.toFixed(2)} — major storm, satellites & networks at risk.`
}

const TELEMETRY_GROUPS: { id: string; label: string; rows: TelemetryEntry[] }[] = [
  {
    id: 'motion',
    label: 'MOTION',
    rows: [
      { layer: 'aircraft', label: 'AIRCRAFT', statKey: 'aircraft', color: '#ffd23f', healthKeys: ['aircraft'], tip: 'Live aircraft (ADS-B).' },
      { layer: 'satellites', label: 'SATELLITES', statKey: 'satellites', color: '#00e5ff', tip: 'Satellites of the selected constellation.' },
      { layer: 'orbits', label: 'ORBITS', color: '#00e5ff', tip: 'Orbit lines (toggle).' },
      { layer: 'military', label: 'MILITARY', statKey: 'military', color: '#ff6b35', healthKeys: ['military'], tip: 'Aircraft flagged as military.' },
      { layer: 'maritime', label: 'MARITIME', statKey: 'maritime', color: '#00e5ff', healthKeys: ['maritime'], tip: 'AIS vessel positions worldwide.' },
      { layer: 'transit', label: 'TRANSIT', statKey: 'transit', color: '#ffd23f', healthKeys: ['transit'], tip: 'Public transit vehicles (GTFS realtime).' },
      { layer: 'trafficCams', label: 'TRAFFIC CAMS', statKey: 'trafficCams', color: '#ff9f1c', healthKeys: ['traffic_cams:regional'], tip: 'ASEAN traffic cameras (Singapore data.gov.sg).' },
    ],
  },
  {
    id: 'geo',
    label: 'GEO',
    rows: [
      { layer: 'quakes', label: 'SEISMIC', statKey: 'quakes', color: '#ff2d00', healthKeys: ['quakes'], tip: 'Earthquakes ≥ M2.5, last 24 h (USGS).' },
      { layer: 'events', label: 'EVENTS', statKey: 'events', color: '#ff6b35', healthKeys: ['events', 'world'], tip: 'Recent entries from event/RSS feeds.' },
      { layer: 'gdacs', label: 'GDACS', statKey: 'gdacs', color: '#ff6b35', hudKey: 'gdacs', healthKeys: ['gdacs', 'gdacs_v2'], tip: 'UN alerts: cyclone, earthquake, flood, drought.' },
      { layer: 'hazards', label: 'HAZARDS', statKey: 'hazards', color: '#22d3ee', hudKey: 'hazards', healthKeys: ['hazards', 'cap'], tip: 'Official weather warnings (CAP).' },
      { layer: 'volcanoes', label: 'VOLCANOES', statKey: 'volcanoes', color: '#ff4d5e', healthKeys: ['volcanoes'], tip: 'Holocene volcanoes (Smithsonian).' },
      { layer: 'geopolitics', label: 'CRISES', statKey: 'geopolitics', color: '#ff2d00', healthKeys: ['geopolitics'], tip: 'Geopolitische Krisen (ReliefWeb).' },
    ],
  },
  {
    id: 'env',
    label: 'ENV',
    rows: [
      { layer: 'wildfires', label: 'WILDFIRES', statKey: 'wildfires', color: '#ff6b35', hudKey: 'wildfires', healthKeys: ['wildfires', 'eonet'], tip: 'Active fires (NASA EONET/FIRMS).' },
      { layer: 'lightning', label: 'LIGHTNING', statKey: 'lightning', color: '#22d3ee', hudKey: 'lightning', healthKeys: ['lightning', 'blitzortung'], tip: 'Lightning strikes in realtime.' },
      {
        layer: 'spaceweather',
        label: 'KP INDEX',
        statKey: 'spaceweather',
        color: '#00e5a0',
        healthKeys: ['spaceweather'],
        formatValue: (s) => (s.spaceweather ? s.spaceweather.toFixed(2) : '—'),
      },
      { layer: 'airquality', label: 'AIR QUALITY', statKey: 'airquality', color: '#b0c4b1', healthKeys: ['airquality'], tip: 'Air quality (AQI/PM2.5) per city.' },
      { layer: 'weather', label: 'WEATHER', statKey: 'weather', color: '#4fc3f7', healthKeys: ['weather', 'windy'], tip: 'Surface temp grid (Windy Point Forecast).' },
    ],
  },
  {
    id: 'infra',
    label: 'INFRA',
    rows: [
      { layer: 'nodes', label: 'NODES', statKey: 'nodes', color: '#00e5a0', healthKeys: ['nodes'], tip: 'Your edge nodes (Pi/mesh).' },
      { layer: 'outages', label: 'OUTAGES', statKey: 'outages', color: '#a855f7', hudKey: 'outages', healthKeys: ['outages'], tip: 'Internet disruptions (IODA/Cloudflare).' },
      { layer: 'pegel', label: 'PEGEL', statKey: 'pegel', color: '#4fc3f7', hudKey: 'pegel', healthKeys: ['pegel'], tip: 'German river gauges / flood levels.' },
      { layer: 'energy', label: 'ENERGY', statKey: 'energy', color: '#ffd23f', hudKey: 'energy', healthKeys: ['energy_de'], tip: 'German power mix (SMARD).' },
    ],
  },
  {
    id: 'intel',
    label: 'INTEL',
    rows: [
      { layer: 'intelFt', label: 'INTEL', statKey: 'intelFt', color: '#b794f6', healthKeys: ['intel'], tip: 'FtM entities with coordinates (24h window).' },
      { layer: 'osint', label: 'OSINT', statKey: 'osint', color: '#00ffa3', tip: 'Your research pins on the globe.' },
    ],
  },
]

type ViewPresetId = 'overview' | 'de_infra' | 'osint' | 'full'

type ViewPreset = {
  label: string
  layers: GlobeLayers
  collapsed: Record<string, boolean>
  trails: boolean
  compact: boolean
  heatmap: boolean
}

/** Quick preset buttons (FULL stays in advanced layers panel). */
const TELEMETRY_QUICK_PRESETS: ViewPresetId[] = ['overview', 'de_infra', 'osint']

const VIEW_PRESETS: Record<ViewPresetId, ViewPreset> = {
  overview: {
    label: 'OVERVIEW',
    layers: {
      aircraft: true,
      satellites: true,
      orbits: false,
      quakes: true,
      events: true,
      nodes: false,
      military: false,
      spaceweather: true,
      geopolitics: false,
      wildfires: true,
      lightning: false,
      transit: false,
      trafficCams: false,
      maritime: false,
      gdacs: true,
      hazards: true,
      outages: true,
      volcanoes: false,
      airquality: false,
      weather: true,
      pegel: false,
      energy: false,
      osint: true,
      intelFt: false,
    },
    collapsed: { motion: false, geo: false, env: false, infra: true, intel: true },
    trails: false,
    compact: true,
    heatmap: true,
  },
  de_infra: {
    label: 'DE INFRA',
    layers: {
      aircraft: true,
      satellites: false,
      orbits: false,
      quakes: true,
      events: false,
      nodes: false,
      military: false,
      spaceweather: true,
      geopolitics: false,
      wildfires: false,
      lightning: false,
      transit: false,
      trafficCams: false,
      maritime: false,
      gdacs: true,
      hazards: true,
      outages: true,
      volcanoes: false,
      airquality: false,
      weather: false,
      pegel: true,
      energy: true,
      osint: false,
      intelFt: false,
    },
    collapsed: { motion: true, geo: false, env: true, infra: false, intel: true },
    trails: false,
    compact: true,
    heatmap: false,
  },
  osint: {
    label: 'OSINT',
    layers: {
      aircraft: false,
      satellites: false,
      orbits: false,
      quakes: false,
      events: true,
      nodes: false,
      military: false,
      spaceweather: false,
      geopolitics: true,
      wildfires: false,
      lightning: false,
      transit: false,
      trafficCams: true,
      maritime: true,
      gdacs: true,
      hazards: false,
      outages: false,
      volcanoes: false,
      airquality: false,
      weather: true,
      pegel: false,
      energy: false,
      osint: true,
      intelFt: true,
    },
    collapsed: { motion: true, geo: true, env: true, infra: true, intel: false },
    trails: false,
    compact: false,
    heatmap: false,
  },
  full: {
    label: 'FULL',
    layers: {
      aircraft: true,
      satellites: true,
      orbits: true,
      quakes: true,
      events: true,
      nodes: true,
      military: false,
      spaceweather: true,
      geopolitics: false,
      wildfires: true,
      lightning: true,
      transit: false,
      trafficCams: false,
      maritime: false,
      gdacs: true,
      hazards: true,
      outages: true,
      volcanoes: false,
      airquality: false,
      weather: true,
      pegel: false,
      energy: false,
      osint: true,
      intelFt: true,
    },
    collapsed: { motion: false, geo: false, env: false, infra: false, intel: false },
    trails: true,
    compact: false,
    heatmap: true,
  },
}

const GLOBE_SESSION_KEY = 'globeTelemetry'

type GlobeTelemetrySession = {
  viewPreset: ViewPresetId
  layers: GlobeLayers
  telemetryCompact: boolean
  telemetryCollapsed: Record<string, boolean>
  trailsEnabled: boolean
  heatmapOn: boolean
  layersPanelOpen: boolean
}

const VIEW_PRESET_IDS: ViewPresetId[] = ['overview', 'de_infra', 'osint', 'full']

function isViewPresetId(v: unknown): v is ViewPresetId {
  return typeof v === 'string' && VIEW_PRESET_IDS.includes(v as ViewPresetId)
}

function isGlobeLayers(v: unknown): v is GlobeLayers {
  if (!v || typeof v !== 'object') return false
  const ref = VIEW_PRESETS.overview.layers
  return (Object.keys(ref) as LayerKey[]).every((k) => typeof (v as GlobeLayers)[k] === 'boolean')
}

function isTelemetryCollapsed(v: unknown): v is Record<string, boolean> {
  if (!v || typeof v !== 'object') return false
  return Object.values(v).every((x) => typeof x === 'boolean')
}

function isGlobeTelemetrySession(v: unknown): v is GlobeTelemetrySession {
  if (!v || typeof v !== 'object') return false
  const s = v as GlobeTelemetrySession
  return (
    isViewPresetId(s.viewPreset) &&
    isGlobeLayers(s.layers) &&
    typeof s.telemetryCompact === 'boolean' &&
    isTelemetryCollapsed(s.telemetryCollapsed) &&
    typeof s.trailsEnabled === 'boolean' &&
    typeof s.heatmapOn === 'boolean' &&
    typeof s.layersPanelOpen === 'boolean'
  )
}

function loadGlobeTelemetrySession(): GlobeTelemetrySession | null {
  const raw = readHudSessionStore()[GLOBE_SESSION_KEY]
  return isGlobeTelemetrySession(raw) ? raw : null
}

function fmtTelemetryAge(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec)) return ''
  if (sec < 60) return `${Math.round(sec)}s`
  if (sec < 3600) return `${Math.round(sec / 60)}m`
  return `${(sec / 3600).toFixed(1)}h`
}

function resolveFeedHealth(feeds: Record<string, FeedHealth>, keys?: string[]): FeedHealth | null {
  if (!keys?.length) return null
  for (const k of keys) {
    if (feeds[k]) return feeds[k]
  }
  for (const [k, v] of Object.entries(feeds)) {
    if (keys.some((hk) => k === hk || k.startsWith(`${hk}:`) || k.includes(hk))) return v
  }
  return null
}

function telemetryMeta(
  entry: TelemetryEntry,
  feedHud: Record<string, string>,
  health: FeedHealth | null,
  extra?: string,
): string {
  const parts: string[] = []
  if (extra) parts.push(extra)
  else if (entry.hudKey && feedHud[entry.hudKey]) parts.push(feedHud[entry.hudKey])
  else if (health?.source) {
    const src = Array.isArray(health.source) ? health.source[0] : health.source
    if (src) parts.push(String(src).replace(/^https?:\/\//, '').slice(0, 14))
  }
  const age = fmtTelemetryAge(health?.age_sec)
  if (age) parts.push(age)
  return parts.length ? ` · ${parts.join(' · ')}` : ''
}

function feedStatusClass(status?: string): string {
  if (status === 'fresh') return 'telemetry-status--fresh'
  if (status === 'warn') return 'telemetry-status--warn'
  if (status === 'stale') return 'telemetry-status--stale'
  if (status === 'unknown') return 'telemetry-status--unknown'
  return ''
}

type Target = {
  kind: string
  title: string
  lines: string[]
  lat?: number
  lon?: number
  link?: string
  nodeId?: string
  entityId?: string
  pegelUuid?: string
  trafficCam?: TrafficCamRef
  webcam?: WebcamStreamRef
  weatherCell?: {
    lat: number
    lon: number
    temperature_c?: number | null
    wind_speed_ms?: number | null
    precip_mm_3h?: number | null
  }
} | null

type Cursor = { lon: string; lat: string; alt: string }

function readEntityDegrees(ent: Entity): { lat: number; lon: number } | undefined {
  try {
    const pos = ent.position?.getValue(JulianDate.now())
    if (!pos) return undefined
    const c = Cartographic.fromCartesian(pos)
    return {
      lat: CMath.toDegrees(c.latitude),
      lon: CMath.toDegrees(c.longitude),
    }
  } catch {
    return undefined
  }
}

function enrichTargetCoords(t: NonNullable<Target>, ent?: Entity): NonNullable<Target> {
  if (t.lat != null && t.lon != null) return t
  if (t.weatherCell) return { ...t, lat: t.weatherCell.lat, lon: t.weatherCell.lon }
  if (t.trafficCam) return { ...t, lat: t.trafficCam.lat, lon: t.trafficCam.lon }
  if (ent) {
    const c = readEntityDegrees(ent)
    if (c) return { ...t, lat: c.lat, lon: c.lon }
  }
  return t
}

export default function Globe({
  focus,
  onAskAI,
  osintPins = [],
  onClearOsintPins,
  onCameraMove,
  onOpenWindy,
  syncCamera,
  mapMode = DEFAULT_MAP_VIEW,
  visible = true,
  layoutSplit = false,
}: {
  focus?: FocusTarget | null
  onAskAI?: (title: string, lines: string[]) => void
  osintPins?: OsintPin[]
  onClearOsintPins?: () => void
  onCameraMove?: (cam: { lon: number; lat: number; height: number; pitch?: number }) => void
  onOpenWindy?: (lat: number, lon: number) => void
  syncCamera?: { lon: number; lat: number; height?: number; zoom?: number; pitch?: number; source: 'globe' | 'map'; ts: number } | null
  mapMode?: MapViewMode
  visible?: boolean
  layoutSplit?: boolean
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<Viewer | null>(null)
  const [viewer, setViewer] = useState<Viewer | null>(null)
  const apiRef = useRef<any>({})
  const osintSrcRef = useRef<CustomDataSource | null>(null)
  const focusRef = useRef<FocusTarget | null>(focus ?? null)

  const [vision, setVision] = useState<VisionMode>('normal')
  const [satGroup, setSatGroup] = useState('starlink')
  const [stats, setStats] = useState<Stats>({ aircraft: 0, satellites: 0, quakes: 0, events: 0, nodes: 0, military: 0, spaceweather: 0, geopolitics: 0, wildfires: 0, lightning: 0, transit: 0, trafficCams: 0, maritime: 0, gdacs: 0, hazards: 0, outages: 0, volcanoes: 0, airquality: 0, weather: 0, pegel: 0, osint: 0, intelFt: 0, energy: 0, fps: 0 })
  const [gibsLayer, setGibsLayer] = useState<'off' | 'fires' | 'goes' | 'viirs'>('off')
  const gibsImageryRef = useRef<any>(null)
  const gibsDateRef = useRef<string>('')
  const labelOverlayRef = useRef<ImageryLayer | null>(null)
  const osmBuildingsRef = useRef<any>(null)
  const photorealRef = useRef<any>(null)
  const mapModeRef = useRef(mapMode)
  useEffect(() => { mapModeRef.current = mapMode }, [mapMode])
  const [mvtProvider, setMvtProvider] = useState<any>(null)
  const [transitCity, setTransitCity] = useState('helsinki')
  const [target, setTarget] = useState<Target>(null)
  const [detailOpen, setDetailOpen] = useState(false)
  const applyTarget = useCallback((t: NonNullable<Target>, ent?: Entity) => {
    setTarget(enrichTargetCoords(t, ent))
    setDetailOpen(true)
  }, [])
  const closeDetail = useCallback(() => {
    setDetailOpen(false)
    setTarget(null)
    apiRef.current.unlock?.()
    const v = viewerRef.current
    if (v && !(v as any).isDestroyed?.()) {
      try {
        v.resize()
        v.scene.requestRender()
      } catch {
        /* ignore */
      }
    }
  }, [])
  const handleTrafficCamSelect = useCallback((next: TrafficCamRef) => {
    applyTarget({
      kind: 'traffic_cam',
      title: `🚦 ${next.name}`,
      link: next.image_url,
      lat: next.lat,
      lon: next.lon,
      lines: [
        `SOURCE: ${next.source ?? '—'}`,
        `COUNTRY: ${next.country ?? '—'}`,
        `LAT/LON: ${next.lat.toFixed(4)}, ${next.lon.toFixed(4)}`,
      ],
      trafficCam: next,
      entityId: `traffic_cam:${next.id}`,
    })
    const v = viewerRef.current
    if (v) {
      v.camera.flyTo({
        destination: Cartesian3.fromDegrees(next.lon, next.lat, 14000),
        orientation: { heading: 0, pitch: CMath.toRadians(-48), roll: 0 },
        duration: 1.0,
      })
    }
  }, [applyTarget])
  const [cursor, setCursor] = useState<Cursor>({ lon: '—', lat: '—', alt: '—' })
  const [hoverTip, setHoverTip] = useState<{ title: string; lines: string[]; x: number; y: number } | null>(null)
  const [scrubT, setScrubT] = useState(1)
  const [timelineHours, setTimelineHours] = useState<number>(24)
  const [aircraftSource, setAircraftSource] = useState('')
  const [feedHud, setFeedHud] = useState<Record<string, string>>({})
  const [feedHealth, setFeedHealth] = useState<Record<string, FeedHealth>>({})
  const savedGlobe = loadGlobeTelemetrySession()
  const globeDefaults = VIEW_PRESETS.overview
  const [telemetryCompact, setTelemetryCompact] = useState(
    savedGlobe?.telemetryCompact ?? globeDefaults.compact,
  )
  const [telemetryCollapsed, setTelemetryCollapsed] = useState<Record<string, boolean>>(
    () => savedGlobe?.telemetryCollapsed ?? { ...globeDefaults.collapsed },
  )
  const [viewPreset, setViewPreset] = useState<ViewPresetId>(savedGlobe?.viewPreset ?? 'overview')
  const [layersPanelOpen, setLayersPanelOpen] = useState(savedGlobe?.layersPanelOpen ?? false)
  const [trailsEnabled, setTrailsEnabled] = useState(savedGlobe?.trailsEnabled ?? globeDefaults.trails)
  const [heatmapOn, setHeatmapOn] = useState(savedGlobe?.heatmapOn ?? globeDefaults.heatmap)
  const [heatmapMeta, setHeatmapMeta] = useState<{ cells: number; max: number; contrib: Record<string, number> } | null>(null)
  const [sanctionedMmsi, setSanctionedMmsi] = useState<Set<string>>(new Set())
  const sanctionedRef = useRef<Set<string>>(new Set())
  useEffect(() => { sanctionedRef.current = sanctionedMmsi }, [sanctionedMmsi])
  const trailsEnabledRef = useRef(true)
  useEffect(() => { trailsEnabledRef.current = trailsEnabled }, [trailsEnabled])
  const timelineRef = useRef({ scrubT: 1, hours: 24 })
  const [layers, setLayers] = useState<GlobeLayers>(
    () => savedGlobe?.layers ?? { ...globeDefaults.layers },
  )

  useEffect(() => {
    writeHudSessionField(GLOBE_SESSION_KEY, {
      viewPreset,
      layers,
      telemetryCompact,
      telemetryCollapsed,
      trailsEnabled,
      heatmapOn,
      layersPanelOpen,
    } satisfies GlobeTelemetrySession)
  }, [viewPreset, layers, telemetryCompact, telemetryCollapsed, trailsEnabled, heatmapOn, layersPanelOpen])

  const trailsApi = useTrailsLayer({ viewer, active: trailsEnabled });

  const visibleRef = useRef(visible)
  useEffect(() => { visibleRef.current = visible }, [visible])
  const layersRef = useRef(layers)
  useEffect(() => { layersRef.current = layers }, [layers])
  const powerStateRef = useRef<GlobePowerState>({
    docVisible: typeof document !== 'undefined' ? !document.hidden : true,
    intersecting: true,
    interactionIdle: false,
    cameraMoving: false,
    cameraHeightM: 0,
  })
  const applyPowerRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    const onAgentLayer = (ev: Event) => {
      const detail = (ev as CustomEvent<AgentLayerDetail>).detail
      const layer = detail?.layer
      if (!layer || !(layer in layersRef.current)) return
      setLayers((prev) => ({
        ...prev,
        [layer as LayerKey]: detail.enabled ?? !prev[layer as LayerKey],
      }))
    }
    window.addEventListener(AGENT_BUS_LAYER_EVENT, onAgentLayer)
    return () => window.removeEventListener(AGENT_BUS_LAYER_EVENT, onAgentLayer)
  }, [])

  const applyViewPreset = useCallback((id: ViewPresetId) => {
    const preset = VIEW_PRESETS[id]
    setLayers({ ...preset.layers })
    setTelemetryCollapsed({ ...preset.collapsed })
    setTelemetryCompact(preset.compact)
    setTrailsEnabled(preset.trails)
    setHeatmapOn(preset.heatmap)
    setViewPreset(id)
  }, [])

  const prevSplitRef = useRef(layoutSplit)
  useEffect(() => {
    if (layoutSplit && !prevSplitRef.current) {
      applyViewPreset('overview')
    }
    prevSplitRef.current = layoutSplit
  }, [layoutSplit, applyViewPreset])

  useEffect(() => {
    if (!visible) return
    let cancelled = false
    const poll = async () => {
      try {
        const r = await fetchApi('/api/health')
        if (!r.ok || cancelled) return
        const d = await r.json()
        if (!cancelled && d.feeds) setFeedHealth(d.feeds)
      } catch { /* ignore */ }
    }
    poll()
    const t = setInterval(poll, 60000)
    return () => { cancelled = true; clearInterval(t) }
  }, [visible])

  const onCameraMoveRef = useRef(onCameraMove)
  const cameraSyncingRef = useRef(false)
  const syncSuppressUntilRef = useRef(0)
  useEffect(() => { onCameraMoveRef.current = onCameraMove }, [onCameraMove])

  const shouldSyncCamera = () =>
    cameraSyncingRef.current || performance.now() < syncSuppressUntilRef.current

  useEffect(() => {
    if (!visible) return
    const v = viewerRef.current
    if (!v || (v as any).isDestroyed?.()) return
    const resize = () => {
      try {
        v.resize()
        v.scene.requestRender()
      } catch {
        /* ignore during teardown */
      }
    }
    requestAnimationFrame(resize)
    const t1 = window.setTimeout(resize, 120)
    const t2 = window.setTimeout(resize, 350)
    return () => {
      clearTimeout(t1)
      clearTimeout(t2)
    }
  }, [visible, layoutSplit])

  useEffect(() => {
    const v = viewerRef.current
    if (!v || (v as any).isDestroyed?.()) return
    v.useDefaultRenderLoop = visible
    applyPowerRef.current?.()
    if (visible) {
      try {
        v.resize()
        v.scene.requestRender()
        apiRef.current.applyTimeline?.()
      } catch {
        /* ignore during teardown */
      }
    }
  }, [visible, layoutSplit])

  useEffect(() => {
    const onVisibility = () => {
      powerStateRef.current.docVisible = !document.hidden
      applyPowerRef.current?.()
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => document.removeEventListener('visibilitychange', onVisibility)
  }, [])

  useEffect(() => {
    applyPowerRef.current?.()
  }, [layers, viewer])

  useEffect(() => {
    if (!visible) return
    const v = viewerRef.current
    if (!v || (v as any).isDestroyed?.()) return
    try {
      v.resolutionScale = globeResolutionScale()
      applyPowerRef.current?.()
      v.resize()
      v.scene.requestRender()
    } catch {
      /* ignore during teardown */
    }
  }, [visible, layoutSplit])

  useEffect(() => {
    if (!containerRef.current) return
    let cancelled = false
    let viewer: Viewer | null = null
    let resizeObserver: ResizeObserver | null = null
    let recoverAfterOnline: (() => void) | null = null
    const timers: ReturnType<typeof setInterval>[] = []
    const feedActive = () => !cancelled && visibleRef.current

    let detachTerrainFailover: (() => void) | undefined
    let detachIdleWake: (() => void) | null = null
    let pumpRaf = 0
    let intersectionObserver: IntersectionObserver | null = null
    let fxaaIdleTimer = 0
    let focusPulseCleanup: (() => void) | null = null

    ;(async () => {
      const terrainProvider = await createTerrainWithFallback()
      if (cancelled || !containerRef.current) return

      viewer = new Viewer(containerRef.current, {
        terrainProvider,
        baseLayerPicker: false,
        sceneModePicker: false,
        navigationHelpButton: false,
        animation: false,
        timeline: false,
        homeButton: true,
        geocoder: true,
        infoBox: false,
        selectionIndicator: false,
        requestRenderMode: !GLOBE_CONTINUOUS_RENDER,
        maximumRenderTimeChange: !GLOBE_CONTINUOUS_RENDER ? Infinity : undefined,
        contextOptions: {
          webgl: {
            antialias: false,
            alpha: false,
          },
        },
      })
      viewerRef.current = viewer
      viewer.useBrowserRecommendedResolution = false
      viewer.resolutionScale = globeResolutionScale()
      setViewer(viewer)
      detachTerrainFailover = attachTerrainFailover(viewer, terrainProvider)

      const scene = viewer.scene
      scene.globe.enableLighting = true
      scene.globe.depthTestAgainstTerrain = false
      scene.globe.maximumScreenSpaceError = GLOBE_MAX_SSE
      scene.globe.tileCacheSize = GLOBE_TILE_CACHE_SIZE
      scene.globe.preloadAncestors = false
      scene.globe.preloadSiblings = false
      scene.fog.enabled = true
      if (scene.skyAtmosphere) scene.skyAtmosphere.show = true
      ;(scene.globe as any).atmosphereLightIntensity = 12.0
      if (scene.postProcessStages?.fxaa) scene.postProcessStages.fxaa.enabled = true
      if (GLOBE_TARGET_FPS > 0) viewer.targetFrameRate = GLOBE_TARGET_FPS

      const syncPowerSettings = () => {
        const v = viewerRef.current
        if (!v || (v as any).isDestroyed?.()) return
        try {
          applyGlobePowerSettings(v, visibleRef.current, layersRef.current, powerStateRef.current)
        } catch {
          /* teardown */
        }
      }
      applyPowerRef.current = syncPowerSettings

      if (containerRef.current && typeof IntersectionObserver !== 'undefined') {
        intersectionObserver = new IntersectionObserver(
          (entries) => {
            powerStateRef.current.intersecting = entries.some((e) => e.isIntersecting)
            syncPowerSettings()
          },
          { threshold: 0 },
        )
        intersectionObserver.observe(containerRef.current)
      }

      const markInteraction = () => {
        powerStateRef.current.interactionIdle = false
        syncPowerSettings()
        window.clearTimeout(fxaaIdleTimer)
        fxaaIdleTimer = window.setTimeout(() => {
          powerStateRef.current.interactionIdle = true
          syncPowerSettings()
        }, GLOBE_FXAA_IDLE_MS)
      }
      const onCameraHeight = () => {
        try {
          const c = Cartographic.fromCartesian(viewer!.camera.position)
          const h = c.height
          const prev = powerStateRef.current.cameraHeightM
          powerStateRef.current.cameraHeightM = h
          const prevShow = prev < GLOBE_ATMOSPHERE_OFF_HEIGHT_M
          const nextShow = h < GLOBE_ATMOSPHERE_OFF_HEIGHT_M
          if (prevShow !== nextShow) syncPowerSettings()
        } catch {
          /* ignore */
        }
      }
      viewer.camera.changed.addEventListener(onCameraHeight)
      viewer.camera.moveStart.addEventListener(() => {
        powerStateRef.current.cameraMoving = true
        markInteraction()
      })
      viewer.camera.moveEnd.addEventListener(() => {
        powerStateRef.current.cameraMoving = false
        markInteraction()
      })
      onCameraHeight()
      syncPowerSettings()
      markInteraction()

      // OSM 3D buildings — free via Cesium Ion (same token as terrain)
      viewer.camera.moveEnd.addEventListener(() => {
        const v = viewerRef.current
        if (!v || (v as any).isDestroyed?.()) return
        if (shouldSyncCamera()) return
        if (cameraSyncingRef.current) return
        const c = Cartographic.fromCartesian(v.camera.position)
        const pos = sanitizeLonLat(CMath.toDegrees(c.longitude), CMath.toDegrees(c.latitude))
        if (!pos) return
        onCameraMoveRef.current?.({
          lon: pos.lon,
          lat: pos.lat,
          height: clampCameraHeight(c.height),
          pitch: CMath.toDegrees(v.camera.pitch),
        })
      })

      resizeObserver = new ResizeObserver(() => {
        const v = viewerRef.current
        if (!containerRef.current || !v || (v as any).isDestroyed?.()) return
        if (!containerHasSize(containerRef.current)) return
        try {
          v.resize()
        } catch {
          /* ignore during teardown */
        }
      })
      resizeObserver.observe(containerRef.current)

      
      const focusSrc = new CustomDataSource('focus')
      const osintSrc = new CustomDataSource('osint')
      osintSrcRef.current = osintSrc
      ;[focusSrc, osintSrc].forEach((s) => viewer!.dataSources.add(s))

      // ---------- Explicit-render activity pump ----------
      // Throttled pulse ring updates (~15 fps) plus render wake for camera moves,
      // tracked entities, and focus ring. When requestRenderMode is on, only dirty
      // frames are painted.
      let renderHotUntil = 0
      const wakeIdleFps = () => {
        // Restore full fps synchronously on interaction so the first frame after idle
        // is not delayed by the throttled (idle-fps) pump cadence.
        if (GLOBE_IDLE_FPS <= 0) return
        const v = viewerRef.current
        if (v && !(v as any).isDestroyed?.() && v.targetFrameRate === GLOBE_IDLE_FPS) {
          v.targetFrameRate = GLOBE_IDLE_RESTORE_FPS
          try { v.scene.requestRender() } catch { /* teardown */ }
        }
      }
      const bumpRender = (ms = 1200) => {
        renderHotUntil = Math.max(renderHotUntil, Date.now() + ms)
        wakeIdleFps()
      }
      const onCamChange = () => bumpRender(800)
      viewer.camera.changed.addEventListener(onCamChange)
      viewer.camera.moveStart.addEventListener(onCamChange)
      viewer.camera.moveEnd.addEventListener(() => bumpRender(400))
      // Visible-scene settle tracker: tileLoadProgressEvent fires only when the tile
      // load queue length changes, so we mark the last time tile loading made any
      // progress. Silence for GLOBE_IDLE_TILE_SETTLE_MS means the visible scene is
      // settled (loaded or permanently stalled) and safe to idle.
      let lastTileProgressAt = Date.now()
      // Instant wake on pointer/wheel even before the camera starts moving, so the
      // quiescence controller never makes the first interaction feel sluggish.
      const onCanvasWake = () => bumpRender(800)
      const onTileProgress = () => { lastTileProgressAt = Date.now() }
      try { scene.globe.tileLoadProgressEvent.addEventListener(onTileProgress) } catch { /* older Cesium */ }
      if (GLOBE_IDLE_FPS > 0) {
        scene.canvas.addEventListener('pointerdown', onCanvasWake)
        scene.canvas.addEventListener('wheel', onCanvasWake, { passive: true })
        detachIdleWake = () => {
          try {
            scene.canvas.removeEventListener('pointerdown', onCanvasWake)
            scene.canvas.removeEventListener('wheel', onCanvasWake)
            scene.globe.tileLoadProgressEvent.removeEventListener(onTileProgress)
          } catch { /* canvas/globe already torn down */ }
        }
      } else {
        detachIdleWake = () => {
          try {
            scene.globe.tileLoadProgressEvent.removeEventListener(onTileProgress)
          } catch { /* globe already torn down */ }
        }
      }
      const pump = () => {
        pumpRaf = requestAnimationFrame(pump)
        const v = viewerRef.current
        if (!v || (v as any).isDestroyed?.() || !visibleRef.current) return
        const L = layersRef.current
        const motionLayer = !!(L.aircraft || L.satellites)
        const hasFocusRing = focusSrc.entities.values.length > 0
        const pulseFrame = tickPulseAnimations()
        const busy =
          Date.now() < renderHotUntil ||
          motionLayer ||
          pulseFrame ||
          hasFocusRing ||
          !!v.trackedEntity

        const tilesSettled = Date.now() - lastTileProgressAt > GLOBE_IDLE_TILE_SETTLE_MS
        const quiescent = !busy && !motionLayer && tilesSettled

        // Tile-churn suppression (always on): stop off-screen descendant loads when idle.
        const descLimit = quiescent ? GLOBE_LOADING_DESCENDANT_QUIESCENT : GLOBE_LOADING_DESCENDANT_ACTIVE
        if (v.scene.globe.loadingDescendantLimit !== descLimit) {
          v.scene.globe.loadingDescendantLimit = descLimit
        }

        // Render-quiescence controller (env-gated): when the visible scene is provably
        // static, throttle the render loop to GLOBE_IDLE_FPS; restore to normal
        // otherwise. Quiescence = camera/interaction idle, no motion (aircraft/sat),
        // no pulse tick (~15 fps rings), no tracked entity or focus ring, AND tile
        // loading has gone quiet (tileLoadProgressEvent silent). Using load-progress
        // silence rather than tilesLoaded/empty-queue is essential: the HUD's root
        // imagery stays perpetually TRANSITIONING, so tilesLoaded never turns true
        // and the visible queue can stay non-empty forever. Motion layers animate
        // continuously and are never throttled (would look choppy = quality loss).
        if (GLOBE_IDLE_FPS > 0) {
          const desired = quiescent ? GLOBE_IDLE_FPS : GLOBE_IDLE_RESTORE_FPS
          if (v.targetFrameRate !== desired) v.targetFrameRate = desired
        }

        if (pulseFrame || (v.scene.requestRenderMode && busy)) {
          try { v.scene.requestRender() } catch { /* teardown */ }
        }
      }
      pumpRaf = requestAnimationFrame(pump)
      bumpRender(2000)

      // ---------- Interaction ----------

      const handler = new ScreenSpaceEventHandler(scene.canvas)
      handler.setInputAction((m: any) => {
        const ray = viewer!.camera.getPickRay(m.endPosition)
        if (ray) {
          const cart = scene.globe.pick(ray, scene)
          if (cart) {
            const c = Cartographic.fromCartesian(cart)
            setCursor({
              lon: CMath.toDegrees(c.longitude).toFixed(4),
              lat: CMath.toDegrees(c.latitude).toFixed(4),
              alt: c.height.toFixed(0),
            })
          }
        }

        const gp = resolveGlobePick(scene.pick(m.endPosition))
        if (gp) {
          const tip = buildEntityHoverTip(String(gp.prop('kind') || ''), gp.prop)
          if (tip) {
            if (!cancelled) {
              setHoverTip({ ...tip, x: m.endPosition.x, y: m.endPosition.y })
            }
            scene.canvas.style.cursor = 'pointer'
            return
          }
        }

        if (!cancelled) setHoverTip(null)
        scene.canvas.style.cursor = 'default'
      }, ScreenSpaceEventType.MOUSE_MOVE)

      const selectEntity = (ent: Entity) => {
        const props = ent.properties as any
        const prop = (k: string) => {
          const p = props?.[k]
          return typeof p?.getValue === 'function' ? p.getValue() : p
        }
        const pick = (payload: NonNullable<Target>) => applyTarget(payload, ent)
        const kind = prop('kind')
        if (kind === 'aircraft') {
          const icao = (props.icao?.getValue?.() || '').toLowerCase()
          pick({
            kind, title: `✈ ${props.callsign?.getValue?.()}`,
            entityId: icao ? `aircraft:${icao}` : undefined,
            lines: [
              `ICAO24: ${icao}`,
              `COUNTRY: ${props.country?.getValue?.()}`,
              `ALTITUDE: ${Math.round(props.alt?.getValue?.() ?? 0)} m`,
              `VELOCITY: ${Math.round(props.vel?.getValue?.() ?? 0)} m/s`,
              `HEADING: ${Math.round(props.heading?.getValue?.() ?? 0)}°`,
              trailsEnabledRef.current ? 'TRAIL: fetching…' : 'TRAIL: disabled',
            ],
          })
          viewer!.trackedEntity = ent
          if (trailsEnabledRef.current && icao) trailsApi.fetchTrail(icao)
        } else if (kind === 'satellite') {
          pick({
            kind, title: `🛰 ${props.name?.getValue?.()}`,
            lines: [`ALTITUDE: ${Math.round(props.alt?.getValue?.() ?? 0)} m`, 'ORBIT: TRACKING'],
          })
          viewer!.trackedEntity = ent
        } else if (kind === 'quake') {
          const place = props.place?.getValue?.() || 'Unknown location'
          const mag = props.mag?.getValue?.()
          pick({
            kind, title: `⊕ M${mag} SEISMIC — ${place}`,
            lines: [
              `DEPTH: ${props.depth?.getValue?.()} km`,
              `TIME: ${new Date(props.time?.getValue?.()).toLocaleString()}`,
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'event') {
          const evTitle = props.title?.getValue?.() || 'Event'
          const category = props.category?.getValue?.()
          pick({
            kind, title: `⚠ ${evTitle}`,
            lines: [
              ...(category ? [`CATEGORY: ${category}`] : []),
              `DATE: ${new Date(props.date?.getValue?.()).toLocaleString()}`,
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'military') {
          const sq = props.squawk?.getValue?.()
          pick({
            kind, title: `🎖 ${props.flight?.getValue?.() || props.hex?.getValue?.()}`,
            lines: [
              `HEX: ${props.hex?.getValue?.()}`,
              `TYPE: ${props.type?.getValue?.() || '—'}`,
              `ALTITUDE: ${Math.round(props.alt?.getValue?.() ?? 0)} m`,
              `SPEED: ${(props.speed?.getValue?.() ?? 0).toFixed(1)} m/s`,
              ...(sq ? [`SQUAWK: ${sq}${['7500', '7600', '7700'].includes(sq) ? ' ⚠ EMERGENCY' : ''}`] : []),
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'transit') {
          pick({
            kind, title: `🚌 TRANSIT ${props.route_id?.getValue?.() || '—'}`,
            lines: [
              `ID: ${props.id?.getValue?.() ?? '—'}`,
              `ROUTE: ${props.route_id?.getValue?.() ?? '—'}`,
              `BEARING: ${props.bearing?.getValue?.() ?? '—'}°`,
              `SPEED: ${props.speed?.getValue?.() != null ? props.speed.getValue() + ' m/s' : '—'}`,
              `LABEL: ${props.label?.getValue?.() ?? '—'}`,
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'maritime') {
          const mmsi = String(props.mmsi?.getValue?.() ?? '')
          const flagged = sanctionedRef.current.has(mmsi)
          pick({
            kind, title: `🚢 ${flagged ? '⚠ ' : ''}${props.name?.getValue?.() || 'Vessel'}`,
            lines: [
              `MMSI: ${mmsi || '—'}`,
              `TYPE: ${props.type?.getValue?.() ?? '—'}`,
              `COURSE: ${props.course?.getValue?.() ?? '—'}°`,
              `SPEED: ${props.speed?.getValue?.() != null ? props.speed.getValue() + ' kn' : '—'}`,
              `DESTINATION: ${props.destination?.getValue?.() ?? '—'}`,
              `FLAG: ${props.flag?.getValue?.() ?? '—'}`,
              `LENGTH: ${props.length?.getValue?.() != null ? props.length.getValue() + ' m' : '—'}`,
              ...(flagged ? ['⚠ ON OPENSANCTIONS WATCHLIST'] : []),
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'fusion_cell') {
          pick({
            kind, title: `⛶ FUSION CELL`,
            lines: [
              `INTENSITY: ${props.intensity?.getValue?.()}`,
              `SCORE: ${(props.score?.getValue?.() ?? 0).toFixed(2)}`,
              `SOURCES: ${props.sources?.getValue?.() || '—'}`,
              `SAMPLES: ${(props.samples?.getValue?.() || '').slice(0, 120) || '—'}`,
            ],
          })
        } else if (kind === 'wildfire') {
          pick({
            kind, title: `🔥 WILDFIRE (${props.confidence_label?.getValue?.() || 'unknown'})`,
            lines: [
              `CONFIDENCE: ${props.confidence?.getValue?.() ?? '—'}%`,
              `BRIGHTNESS: ${props.brightness?.getValue?.() ?? '—'}K`,
              `FRP: ${props.frp?.getValue?.() ?? '—'} MW`,
              `SATELLITE: ${props.satellite?.getValue?.() ?? '—'}`,
              `DATE: ${props.acq_date?.getValue?.() ?? '—'}`,
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'lightning') {
          pick({
            kind, title: `⚡ LIGHTNING STRIKE`,
            lines: [
              `TIME: ${props.time?.getValue?.() ?? '—'}`,
              `STATIONS: ${props.stations?.getValue?.() ?? '—'}`,
              `PARTICIPANTS: ${props.participants?.getValue?.() ?? '—'}`,
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'intel_ftm') {
          const datasets = props.datasets?.getValue?.() || []
          pick({
            kind,
            title: props.caption?.getValue?.() || 'Intel entity',
            lines: [
              `SCHEMA: ${props.schema?.getValue?.() ?? '—'}`,
              `ID: ${props.id?.getValue?.() ?? '—'}`,
              `DATASETS: ${Array.isArray(datasets) ? datasets.join(', ') : '—'}`,
              `LAST SEEN: ${props.last_seen?.getValue?.() ?? '—'}`,
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'node') {
          const svcs = props.services?.getValue?.() || {}
          const svcLines = Object.entries(svcs).map(([k, v]) => `  ${k}: ${v}`)
          const s = props.sensors?.getValue?.() || {}
          const sensorLines = Object.entries(s).map(([k, v]) => `  ${k}: ${v}`)
          const ph = props.pihole?.getValue?.() || {}
          pick({
            kind, title: `📡 ${props.name?.getValue?.()}`,
            nodeId: String(props.node_id?.getValue?.() || ''),
            lines: [
              `CPU TEMP: ${props.temp?.getValue?.()}°C`,
              `STATUS: ${props.online?.getValue?.() ? 'ONLINE' : 'OFFLINE'}`,
              `AGE: ${Math.round(props.age_seconds?.getValue?.() ?? 0)}s`,
              `MESH NODES: ${props.mesh_count?.getValue?.() ?? 0}`,
              ...(ph.blocked ? [`PI-HOLE: ${ph.blocked} blocked (${ph.percent}%)`] : []),
              ...(sensorLines.length ? ['SENSORS:', ...sensorLines] : []),
              ...(svcLines.length ? ['SERVICES:', ...svcLines] : []),
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'mesh_node') {
          pick({
            kind, title: `📻 MESH ${props.name?.getValue?.() || 'Node'}`,
            lines: [
              `ID: ${props.id?.getValue?.() ?? '—'}`,
              `SNR: ${props.snr?.getValue?.() ?? '—'} dB`,
              `LAST SEEN: ${props.last_seen?.getValue?.() ?? '—'}`,
              `PI GATEWAY: ${props.pi_node?.getValue?.() ?? '—'}`,
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'gdacs') {
          pick({
            kind,
            title: props.title?.getValue?.() || 'GDACS Alert',
            lines: [
              (props.description?.getValue?.() || '').slice(0, 160),
              `PUBLISHED: ${props.published?.getValue?.() ?? '—'}`,
            ],
            link: props.link?.getValue?.(),
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'outage') {
          pick({
            kind,
            title: `📡 ${props.title?.getValue?.() || 'Outage'}`,
            lines: [
              `SOURCE: ${props.source?.getValue?.() ?? '—'}`,
              `LEVEL: ${props.level?.getValue?.() ?? '—'}`,
              `DATASOURCE: ${props.datasource?.getValue?.() ?? '—'}`,
              props.duration_h?.getValue?.() != null ? `DURATION: ${props.duration_h.getValue()} h` : 'DURATION: —',
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'volcano') {
          const name = props.name?.getValue?.() || ''
          pick({
            kind,
            title: `🌋 ${name || 'Volcano'}`,
            entityId: name ? `volcano:${name}` : undefined,
            lines: [
              `COUNTRY: ${props.country?.getValue?.() ?? '—'}`,
              `TYPE: ${props.type?.getValue?.() ?? '—'}`,
              `LAST ERUPTION: ${props.last_eruption?.getValue?.() ?? '—'}`,
              `ELEV: ${props.elevation_m?.getValue?.() ?? '—'} m`,
              `ACTIVE: ${props.active?.getValue?.() ? 'yes' : 'no'}`,
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'hazard' || kind === 'gdelt_geo') {
          pick({
            kind,
            title: props.event?.getValue?.() || props.title?.getValue?.() || 'Hazard',
            lines: [
              `SEVERITY: ${props.severity?.getValue?.() ?? '—'}`,
              `AREA: ${(props.area_desc?.getValue?.() || '').slice(0, 120)}`,
              `FEED: ${props.feed?.getValue?.() ?? 'gdelt'}`,
              `EFFECTIVE: ${props.effective?.getValue?.() ?? props.date?.getValue?.() ?? '—'}`,
            ],
            link: props.url?.getValue?.(),
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'airquality') {
          pick({
            kind,
            title: `💨 ${props.city?.getValue?.()}`,
            lines: [
              `PM2.5: ${props.pm25?.getValue?.() ?? '—'} µg/m³`,
              `PM10: ${props.pm10?.getValue?.() ?? '—'} µg/m³`,
              `TIME: ${props.time?.getValue?.() ?? '—'}`,
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'energy') {
          pick({
            kind,
            title: `⚡ ${props.label?.getValue?.()}`,
            lines: [
              `OUTPUT: ${props.mw?.getValue?.() ?? '—'} MW`,
              `DE LOAD: ${props.load_mw?.getValue?.() ?? '—'} MW`,
              `PRICE: ${props.price?.getValue?.() ?? '—'} €/MWh`,
              `CO₂: ${props.co2_g_per_kwh?.getValue?.() ?? '—'} g/kWh`,
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'pegel') {
          const uuid = props.uuid?.getValue?.() || ''
          pick({
            kind,
            title: `🌊 ${props.name?.getValue?.()} (${props.water?.getValue?.()})`,
            entityId: uuid ? `pegel:${uuid}` : undefined,
            pegelUuid: uuid || undefined,
            lines: [
              `LEVEL: ${props.value?.getValue?.() ?? '—'} ${props.unit?.getValue?.() ?? ''}`,
              `STATUS: ${props.severity?.getValue?.() ?? '—'}`,
              `${props.state_mnw_mhw?.getValue?.() ?? '—'} / ${props.state_nsw_hsw?.getValue?.() ?? '—'}`,
              `TIME: ${props.timestamp?.getValue?.() ?? '—'}`,
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'geopolitics') {
          pick({
            kind,
            title: props.name?.getValue?.() || 'Crisis',
            lines: [`STATUS: ${props.status?.getValue?.() ?? '—'}`, `ID: ${props.id?.getValue?.() ?? '—'}`],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'weather') {
          const lat = Number(prop('lat'))
          const lon = Number(prop('lon'))
          pick({
            kind,
            title: '🌡 WEATHER CELL',
            lines: [
              `LAT/LON: ${lat.toFixed(4)}, ${lon.toFixed(4)}`,
              `TEMP: ${prop('temperature_c') != null ? `${Math.round(prop('temperature_c'))}°C` : '—'}`,
              `WIND: ${prop('wind_speed_ms') != null ? `${prop('wind_speed_ms')} m/s` : '—'}`,
              `RAIN 3H: ${prop('precip_mm_3h') != null ? `${Number(prop('precip_mm_3h')).toFixed(1)} mm` : '—'}`,
            ],
            weatherCell: {
              lat,
              lon,
              temperature_c: prop('temperature_c'),
              wind_speed_ms: prop('wind_speed_ms'),
              precip_mm_3h: prop('precip_mm_3h'),
            },
          })
          viewer!.camera.flyTo({
            destination: Cartesian3.fromDegrees(lon, lat, 280000),
            orientation: { heading: 0, pitch: CMath.toRadians(-55), roll: 0 },
            duration: 1.0,
          })
        } else if (kind === 'traffic_cam') {
          const camId = String(prop('cam_id') ?? ent.id ?? '')
          const lat = Number(prop('lat') ?? 0)
          const lon = Number(prop('lon') ?? 0)
          const imageUrl = String(prop('image_url') ?? '')
          const cam: TrafficCamRef = {
            id: camId,
            name: String(prop('name') || 'Traffic camera'),
            lat,
            lon,
            image_url: imageUrl,
            source: String(prop('source') ?? ''),
            country: String(prop('country') ?? ''),
            refresh_ms: Number(prop('refresh_ms') ?? 120_000),
          }
          pick({
            kind,
            title: `🚦 ${cam.name}`,
            entityId: camId ? `traffic_cam:${camId}` : undefined,
            link: imageUrl || undefined,
            lines: [
              `SOURCE: ${cam.source || '—'}`,
              `COUNTRY: ${cam.country || '—'}`,
              `LAT/LON: ${lat.toFixed(4)}, ${lon.toFixed(4)}`,
            ],
            trafficCam: cam,
          })
          viewer!.camera.flyTo({
            destination: Cartesian3.fromDegrees(lon, lat, 14000),
            orientation: { heading: 0, pitch: CMath.toRadians(-48), roll: 0 },
            duration: 1.2,
          })
        } else if (kind === 'osint') {
          pick({
            kind,
            title: props.title?.getValue?.() || 'OSINT',
            lines: [
              `TOOL: ${props.tool?.getValue?.() ?? '—'}`,
              `QUERY: ${props.query?.getValue?.() ?? '—'}`,
              ...(props.line1?.getValue?.() ? [props.line1.getValue()] : []),
              ...(props.line2?.getValue?.() ? [props.line2.getValue()] : []),
              ...(props.line3?.getValue?.() ? [props.line3.getValue()] : []),
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        }
      }

      handler.setInputAction((click: any) => {
        const gp = resolveGlobePick(scene.pick(click.position))
        if (gp?.entity) {
          selectEntity(gp.entity)
        } else if (gp && gp.prop('kind') === 'aircraft') {
          const prop = gp.prop
          const lon = Number(prop('lon'))
          const lat = Number(prop('lat'))
          const alt = Number(prop('alt') ?? 0)
          const icao = String(prop('icao') || '').toLowerCase()
          applyTarget({
            kind: 'aircraft',
            title: `✈ ${prop('callsign') || icao}`,
            entityId: icao ? `aircraft:${icao}` : undefined,
            lat: Number.isFinite(lat) ? lat : undefined,
            lon: Number.isFinite(lon) ? lon : undefined,
            lines: [
              `ICAO24: ${icao}`,
              `COUNTRY: ${prop('country') ?? '—'}`,
              `ALTITUDE: ${Math.round(Number.isFinite(alt) ? alt : 0)} m`,
              `VELOCITY: ${Math.round(Number(prop('vel') ?? 0))} m/s`,
              `HEADING: ${Math.round(Number(prop('heading') ?? 0))}°`,
              trailsEnabledRef.current ? 'TRAIL: fetching…' : 'TRAIL: disabled',
            ],
          })
          if (Number.isFinite(lon) && Number.isFinite(lat)) {
            viewer!.camera.flyTo({
              destination: Cartesian3.fromDegrees(lon, lat, Math.max(alt + 8000, 12000)),
              duration: 1.2,
            })
          }
          viewer!.trackedEntity = undefined
          if (trailsEnabledRef.current && icao) trailsApi.fetchTrail(icao)
        } else if (gp && gp.prop('kind') === 'satellite') {
          const prop = gp.prop
          const lon = Number(prop('lon'))
          const lat = Number(prop('lat'))
          const alt = Number(prop('alt') ?? 0)
          applyTarget({
            kind: 'satellite',
            title: `🛰 ${prop('name') || 'Satellite'}`,
            lat: Number.isFinite(lat) ? lat : undefined,
            lon: Number.isFinite(lon) ? lon : undefined,
            lines: [`ALTITUDE: ${Math.round(Number.isFinite(alt) ? alt : 0)} m`, 'ORBIT: TRACKING'],
          })
          if (Number.isFinite(lon) && Number.isFinite(lat)) {
            viewer!.camera.flyTo({
              destination: Cartesian3.fromDegrees(lon, lat, Math.max(alt + 500000, 800000)),
              duration: 1.2,
            })
          }
          viewer!.trackedEntity = undefined
        } else if (gp && gp.prop('kind') === 'wildfire') {
          const prop = gp.prop
          const lon = Number(prop('lon'))
          const lat = Number(prop('lat'))
          applyTarget({
            kind: 'wildfire',
            title: `🔥 WILDFIRE (${prop('confidence_label') || 'unknown'})`,
            lat: Number.isFinite(lat) ? lat : undefined,
            lon: Number.isFinite(lon) ? lon : undefined,
            lines: [
              `CONFIDENCE: ${prop('confidence') ?? '—'}%`,
              `BRIGHTNESS: ${prop('brightness') ?? '—'}K`,
              `FRP: ${prop('frp') ?? '—'} MW`,
              `SATELLITE: ${prop('satellite') ?? '—'}`,
              `DATE: ${prop('acq_date') ?? '—'}`,
            ],
          })
          if (Number.isFinite(lon) && Number.isFinite(lat)) {
            viewer!.camera.flyTo({
              destination: Cartesian3.fromDegrees(lon, lat, 400000),
              duration: 1.5,
            })
          }
        } else {
          setDetailOpen(false)
          setTarget(null)
          if (viewer) viewer.trackedEntity = undefined
        }
      }, ScreenSpaceEventType.LEFT_CLICK)

      // ---------- FPS ----------
      let frames = 0, lastT = performance.now()
      scene.postRender.addEventListener(() => {
        if (!visibleRef.current) return
        frames++
        const now = performance.now()
        if (now - lastT >= 1000) {
          if (!cancelled) setStats((p) => ({ ...p, fps: frames }))
          frames = 0; lastT = now
        }
      })

      // ---------- Vision modes ----------
      let activeStage: PostProcessStage | null = null
      const applyVision = (mode: VisionMode) => {
        if (!viewer) return
        if (activeStage) { scene.postProcessStages.remove(activeStage); activeStage = null }
        let frag: string | null = null
        let uniforms: any
        if (mode === 'nvg') frag = NVG_FRAGMENT
        else if (mode === 'thermal') frag = THERMAL_FRAGMENT
        else if (mode === 'crt') { frag = CRT_FRAGMENT; uniforms = { aberration: 1.0 } }
        else if (mode === 'night') frag = NIGHT_FRAGMENT
        if (frag) {
          activeStage = scene.postProcessStages.add(new PostProcessStage({ fragmentShader: frag, uniforms })) as PostProcessStage
        }
      }

      // ---------- Bundled snapshot (one HTTP round-trip for slow feeds) ----------

      apiRef.current = {
        applyVision,
        flyTo: (poi: typeof POIS[number]) => {
          if (!viewer) return
          viewer.trackedEntity = undefined
          viewer.camera.flyTo({
            destination: Cartesian3.fromDegrees(poi.lon, poi.lat, poi.height),
            orientation: {
              heading: CMath.toRadians(poi.heading ?? 0),
              pitch: CMath.toRadians(poi.pitch ?? -45),
              roll: 0,
            },
            duration: 2.5,
          })
        },
        unlock: () => { if (viewer) viewer.trackedEntity = undefined; focusSrc.entities.removeAll(); setDetailOpen(false); setTarget(null) },
        focusOn: (f: FocusTarget) => {
          if (!viewer) return
          viewer.trackedEntity = undefined
          const height =
            f.height ??
            (f.kind === 'webcam' ? 12000 : f.kind === 'traffic_cam' ? 14000 : 400000)
          viewer.camera.flyTo({
            destination: Cartesian3.fromDegrees(f.lon, f.lat, height),
            orientation: {
              heading: 0,
              pitch: CMath.toRadians(f.kind === 'webcam' ? -42 : -55),
              roll: 0,
            },
            duration: 2.2,
          })
          applyTarget({
            kind: f.kind,
            title: f.title,
            lines: f.lines,
            link: f.link,
            webcam: f.webcam,
            lat: f.lat,
            lon: f.lon,
          })
          focusPulseCleanup?.()
          focusPulseCleanup = null
          focusSrc.entities.removeAll()
          const focusEnt = focusSrc.entities.add({
            position: Cartesian3.fromDegrees(f.lon, f.lat, 0),
            point: {
              pixelSize: 11,
              color: Color.fromCssColorString('#00ffa3'),
              outlineColor: Color.WHITE,
              outlineWidth: 2,
            },
          })
          focusPulseCleanup = attachPulseEllipse(focusEnt, {
            cycleMs: 1600,
            baseRadius: 20000,
            pulseScale: 200000,
            color: Color.fromCssColorString('#00ffa3'),
            alphaScale: 0.5,
          })
        }
      }

      timers.push(window.setTimeout(() => {
        if (!feedActive()) return
        fetchApi('/api/gibs/latest').then((r) => r.json()).then((d) => { gibsDateRef.current = d.date || '' }).catch(() => {})
      }, 1200))

      
      

      if (focusRef.current) apiRef.current.focusOn(focusRef.current)

      
      recoverAfterOnline = () => {
        if (cancelled || !feedActive()) return
        
        
      }
      window.addEventListener('online', recoverAfterOnline)

      // Basemap first — must not wait on slow Ion 3D assets
      if (!cancelled && viewerRef.current === viewer) {
        await applyGlobeMapMode(viewer, mapModeRef.current, {
          labelOverlay: labelOverlayRef,
          osmBuildings: osmBuildingsRef,
          photoreal: photorealRef,
          gibsOverlay: gibsImageryRef,
        })
        apiRef.current.applyMapMode = () =>
          applyGlobeMapMode(viewer!, mapModeRef.current, {
            labelOverlay: labelOverlayRef,
            osmBuildings: osmBuildingsRef,
            photoreal: photorealRef,
            gibsOverlay: gibsImageryRef,
          })
      }

      ;(async () => {
        if (Ion.defaultAccessToken) {
          try {
            const buildings = await createOsmBuildingsAsync()
            if (!cancelled && viewerRef.current === viewer) {
              osmBuildingsRef.current = buildings
              buildings.show = mapModeRef.current.buildings && !mapModeRef.current.photorealistic
              scene.primitives.add(buildings)
            }
          } catch (e) {
            console.warn('[Globe] OSM Buildings unavailable:', e)
          }
        }
      })()
    })()

    return () => {
      cancelled = true
      applyPowerRef.current = null
      focusPulseCleanup?.()
      if (pumpRaf) cancelAnimationFrame(pumpRaf)
      detachIdleWake?.()
      detachTerrainFailover?.()
      if (recoverAfterOnline) window.removeEventListener('online', recoverAfterOnline)
      resizeObserver?.disconnect()
      intersectionObserver?.disconnect()
      window.clearTimeout(fxaaIdleTimer)
      timers.forEach((id) => {
        clearTimeout(id)
        clearInterval(id)
      })
      if (viewer && !(viewer as any).isDestroyed?.()) {
        try { viewer.destroy() } catch { /* already torn down */ }
      }
      viewerRef.current = null
      setViewer(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transitCity])

  useEffect(() => {
    focusRef.current = focus ?? null
    if (focus) apiRef.current.focusOn?.(focus)
  }, [focus])

  useEffect(() => { apiRef.current.applyVision?.(vision) }, [vision])
  useEffect(() => { apiRef.current.setSatGroup?.(satGroup) }, [satGroup])
  useEffect(() => {
    // Hooks handle layer visibility and fetching.
  }, [layers, visible])
  useEffect(() => { apiRef.current.setHeatmap?.(heatmapOn) }, [heatmapOn])
  useEffect(() => { apiRef.current.applyMapMode?.() }, [mapMode])
  useEffect(() => {
    if (!trailsEnabled) trailsApi.clearAllTrails()
  }, [trailsEnabled])

  useEffect(() => {
    const viewer = viewerRef.current
    if (!viewer) return
    if (gibsImageryRef.current) {
      viewer.imageryLayers.remove(gibsImageryRef.current, false)
      gibsImageryRef.current = null
    }
    if (gibsLayer === 'off') return
    const layerMap = {
      fires: 'MODIS_Terra_Thermal_Anomalies_All',
      goes: 'GOES-East_ABI_GeoColor',
      viirs: 'VIIRS_SNPP_CorrectedReflectance_TrueColor',
    } as const
    const layerId = layerMap[gibsLayer]
    const date = gibsDateRef.current || new Date(Date.now() - 86400000).toISOString().slice(0, 10)
    const provider = new UrlTemplateImageryProvider({
      url: `https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/${layerId}/default/${date}/250m/{z}/{y}/{x}.jpg`,
      tilingScheme: new GeographicTilingScheme(),
      maximumLevel: 8,
      credit: 'NASA GIBS',
    })
    gibsImageryRef.current = viewer.imageryLayers.addImageryProvider(provider)
    if (gibsImageryRef.current) gibsImageryRef.current.alpha = 0.72
  }, [gibsLayer])

  const toggleMvt = async () => {
    const viewer = viewerRef.current
    if (!viewer) return
    if (mvtProvider) {
      viewer.imageryLayers.remove(mvtProvider, false)
      setMvtProvider(null)
    } else {
      try {
        const mvt = await MVTDataProvider.fromUrl(`http://127.0.0.1:8088/thailand/{z}/{x}/{y}.mvt`, {
           style: {
             version: 8,
             sources: {
               protomaps: {
                 type: "vector",
                 tiles: [`http://127.0.0.1:8088/thailand/{z}/{x}/{y}.mvt`]
               }
             },
             layers: [{
               id: "water",
               type: "fill",
               source: "protomaps",
               "source-layer": "water",
               paint: { "fill-color": "rgba(0, 100, 200, 0.4)" }
             }, {
               id: "roads",
               type: "line",
               source: "protomaps",
               "source-layer": "roads",
               paint: { "line-color": "rgba(255, 255, 255, 0.6)" }
             }]
           }
        } as any)
        const layer = viewer.imageryLayers.addImageryProvider(mvt as any)
        setMvtProvider(layer)
      } catch (err) {
        console.error("MVTDataProvider error:", err)
      }
    }
  }

  useEffect(() => {
    if (!syncCamera || syncCamera.source === 'globe' || !viewerRef.current) return
    if (!containerHasSize(containerRef.current)) return
    const viewer = viewerRef.current
    const pos = sanitizeLonLat(syncCamera.lon, syncCamera.lat)
    if (!pos) return
    const height = syncCamera.height != null
      ? clampCameraHeight(syncCamera.height)
      : zoomToGlobeHeight(syncCamera.zoom ?? 4)
    const pitchDeg = Number.isFinite(syncCamera.pitch)
      ? mapPitchToCesiumDeg(syncCamera.pitch!, mapMode.render3d ? -45 : -90)
      : (mapMode.render3d ? -45 : -90)
    syncSuppressUntilRef.current = performance.now() + 500
    cameraSyncingRef.current = true
    try {
      viewer.camera.setView({
        destination: Cartesian3.fromDegrees(pos.lon, pos.lat, height),
        orientation: {
          heading: 0,
          pitch: CMath.toRadians(pitchDeg),
          roll: 0,
        },
      })
      viewer.resize()
      viewer.scene.requestRender()
    } finally {
      window.setTimeout(() => {
        cameraSyncingRef.current = false
      }, 500)
    }
  }, [syncCamera, mapMode.render3d, visible, layoutSplit])

  useEffect(() => {
    timelineRef.current = { scrubT, hours: timelineHours }
    apiRef.current.applyTimeline?.()
  }, [scrubT, timelineHours])

  const isTimelineLive = scrubT >= 0.995
  const timelineCutoff = timelineCutoffMs(scrubT, timelineHours)

  useEffect(() => {
    const src = osintSrcRef.current
    if (!src) return
    src.entities.removeAll()
    for (const p of osintPins) {
      const lines = p.lines || []
      src.entities.add({
        id: `osint-${p.id}`,
        position: Cartesian3.fromDegrees(p.lon, p.lat, 0),
        point: {
          pixelSize: 13,
          color: Color.fromCssColorString('#00ffa3').withAlpha(0.95),
          outlineColor: Color.WHITE,
          outlineWidth: 2,
        },
        label: {
          text: p.tool.toUpperCase(),
          font: '700 9px "Courier New"',
          fillColor: Color.fromCssColorString('#00ffa3'),
          outlineColor: Color.BLACK,
          outlineWidth: 2,
          style: LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: VerticalOrigin.BOTTOM,
          pixelOffset: new Cartesian2(0, -12),
          distanceDisplayCondition: new DistanceDisplayCondition(0, 2e7),
        },
        properties: {
          kind: 'osint',
          title: p.title,
          tool: p.tool,
          query: p.query,
          line1: lines[0] || '',
          line2: lines[1] || '',
          line3: lines[2] || '',
        } as any,
      })
    }
    setStats((s) => ({ ...s, osint: osintPins.length }))
  }, [osintPins])

  const toggle = (k: LayerKey) => setLayers((l) => ({ ...l, [k]: !l[k] }))

  const toggleTelemetryGroup = (id: string) => {
    setTelemetryCollapsed((c) => ({ ...c, [id]: !c[id] }))
  }

  const layerCount = Object.values(layers).filter(Boolean).length
  const freshFeeds = Object.values(feedHealth).filter((f) => f.status === 'fresh').length

  const renderTelemetryRow = (entry: TelemetryEntry) => {
    if (!entry.layer) return null
    const on = layers[entry.layer]
    const health = resolveFeedHealth(feedHealth, entry.healthKeys)
    const count = entry.statKey != null
      ? (entry.formatValue ? entry.formatValue(stats) : String(stats[entry.statKey]))
      : (on ? 'ON' : 'OFF')
    const extra = entry.layer === 'aircraft' && aircraftSource ? aircraftSource : undefined
    const meta = telemetryMeta(entry, feedHud, health, extra)
    const hidden = telemetryCompact && !on && entry.statKey != null && stats[entry.statKey] === 0
    if (hidden) return null
    const baseTip = entry.layer === 'spaceweather'
      ? kpTooltip(stats.spaceweather)
      : entry.tip
    const tip = (() => {
      if (!health) return baseTip
      const ageStr = fmtTelemetryAge(health.age_sec)
      if (health.status === 'stale' && ageStr) {
        return `${baseTip || entry.label} — STALE (${ageStr} old)`
      }
      if (health.status === 'warn' && ageStr) {
        return `${baseTip || entry.label} — WARN (${ageStr})`
      }
      return baseTip
    })()
    return (
      <button
        key={entry.label}
        type="button"
        className={['hud-row', 'telemetry-row', on ? 'telemetry-row--on' : 'telemetry-row--off'].join(' ')}
        onClick={() => toggle(entry.layer!)}
        data-tip={tip || undefined}
      >
        <span className="hud-dot" style={{ background: entry.color, opacity: on ? 1 : 0.35 }} />
        <span className="telemetry-label">{entry.label}</span>
        {health?.status && (
          <span className={['telemetry-status', feedStatusClass(health.status)].join(' ')} aria-hidden />
        )}
        <span className="hud-val">
          {count}{meta}
        </span>
      </button>
    )
  }

  return (
    <div className={`globe-wrap vision-${vision}${layoutSplit ? ' globe-wrap--split' : ''}`}>
      
      <GlobeLayerManager
        viewer={viewer}
        layers={layers}
        feedActive={visible}
        canFetch={canFetch()}
        setStats={setStats}
        setFeedHud={setFeedHud}
        satGroup={satGroup}
        orbitsActive={layers.orbits}
        transitCity={transitCity}
        scrubT={scrubT}
        timelineHours={timelineHours}
        setAircraftSource={setAircraftSource}
        heatmapOn={heatmapOn}
        setHeatmapMeta={setHeatmapMeta}
        setSanctionedMmsi={setSanctionedMmsi}
      />
      <div ref={containerRef} className="globe-canvas" />

      <div className="reticle">
        <div className="reticle-cross" />
        <span className="bracket tl" /><span className="bracket tr" />
        <span className="bracket bl" /><span className="bracket br" />
      </div>

      {layoutSplit && (
        <div className="globe-split-bar">
          <span className="globe-split-bar-title">TELEMETRY</span>
          <div className="telemetry-presets">
            {TELEMETRY_QUICK_PRESETS.map((id) => (
              <button
                key={id}
                type="button"
                className={['telemetry-preset', viewPreset === id ? 'telemetry-preset--on' : ''].join(' ')}
                onClick={() => applyViewPreset(id)}
                title={`Preset: ${VIEW_PRESETS[id].label}`}
              >
                {VIEW_PRESETS[id].label}
              </button>
            ))}
          </div>
          <span className="telemetry-summary">{layerCount} layers · {freshFeeds || '—'} fresh</span>
        </div>
      )}

      <div className="globe-hud">
        <div className="telemetry-head">
          <div className="hud-title">LIVE TELEMETRY</div>
          <div className="telemetry-presets">
            {TELEMETRY_QUICK_PRESETS.map((id) => (
              <button
                key={id}
                type="button"
                className={['telemetry-preset', viewPreset === id ? 'telemetry-preset--on' : ''].join(' ')}
                onClick={() => applyViewPreset(id)}
                title={`Preset: ${VIEW_PRESETS[id].label}`}
              >
                {VIEW_PRESETS[id].label}
              </button>
            ))}
          </div>
          <div className="telemetry-summary">
            {layerCount} layers · {freshFeeds || '—'} fresh
          </div>
          <button
            type="button"
            className="telemetry-filter"
            onClick={() => setTelemetryCompact((v) => !v)}
            title={telemetryCompact ? 'Show all feeds' : 'Active feeds only'}
          >
            {telemetryCompact ? 'ALL' : 'ACTIVE'}
          </button>
        </div>

        {TELEMETRY_GROUPS.map((group) => {
          const collapsed = telemetryCollapsed[group.id]
          const visibleRows = group.rows.filter((row) => {
            if (!row.layer) return true
            if (!telemetryCompact) return true
            const on = layers[row.layer]
            const n = row.statKey ? stats[row.statKey] : 0
            return on || n > 0 || row.layer === 'orbits'
          })
          if (!visibleRows.length) return null
          const groupTotal = group.rows.reduce((sum, row) => {
            if (!row.statKey || row.formatValue) return sum
            return sum + (stats[row.statKey] || 0)
          }, 0)
          return (
            <div key={group.id} className="telemetry-group">
              <button
                type="button"
                className="telemetry-group-head"
                onClick={() => toggleTelemetryGroup(group.id)}
              >
                <span>{collapsed ? '▸' : '▾'} {group.label}</span>
                <span className="telemetry-group-sum">{groupTotal > 0 ? groupTotal : '—'}</span>
              </button>
              {!collapsed && visibleRows.map((row) => renderTelemetryRow(row))}
            </div>
          )
        })}

        <div className="hud-divider" />
        <div className="hud-row">RENDER<span className="hud-val">{stats.fps} FPS</span></div>
        <div className="hud-row sub">LON {cursor.lon}  LAT {cursor.lat}</div>
        <div className="hud-row sub">ELEV {cursor.alt} m</div>
      </div>

      <div className="globe-controls">
        <div className="ctl-block">
          <div className="hud-title">OPTICS</div>
          <div className="vision-bar">
            {VISION_MODES.map((m) => (
              <button key={m.id} className={vision === m.id ? 'on' : ''} onClick={() => setVision(m.id)}>{m.label}</button>
            ))}
          </div>
        </div>

        <div className="ctl-block">
          <div className="hud-title">TRANSIT ({transitCity.toUpperCase()})</div>
          <div className="vision-bar">
            {TRANSIT_CITIES.map((c) => (
              <button key={c.id} className={transitCity === c.id ? 'on' : ''} onClick={() => setTransitCity(c.id)}>{c.label}</button>
            ))}
          </div>
        </div>

        <div className="ctl-block">
          <div className="hud-title">NASA GIBS</div>
          <div className="vision-bar">
            {([
              { id: 'off', label: 'OFF' },
              { id: 'fires', label: 'FIRES' },
              { id: 'goes', label: 'GOES' },
              { id: 'viirs', label: 'VIIRS' },
            ] as const).map((g) => (
              <button key={g.id} className={gibsLayer === g.id ? 'on' : ''} onClick={() => setGibsLayer(g.id)}>{g.label}</button>
            ))}
          </div>
        </div>

        <div className="ctl-block">
          <div className="hud-title">CONSTELLATION</div>
          <div className="vision-bar">
            {SAT_GROUPS.map((g) => (
              <button key={g.id} className={satGroup === g.id ? 'on' : ''} onClick={() => setSatGroup(g.id)}>{g.label}</button>
            ))}
          </div>
        </div>

        <div className="ctl-block">
          <button
            type="button"
            className="layers-advanced-toggle"
            onClick={() => setLayersPanelOpen((v) => !v)}
          >
            {layersPanelOpen ? '▾' : '▸'} LAYERS (advanced)
          </button>
          {layersPanelOpen && (
            <>
              {(['aircraft', 'satellites', 'orbits', 'quakes', 'events', 'nodes', 'military', 'spaceweather', 'geopolitics', 'wildfires', 'lightning', 'transit', 'trafficCams', 'maritime', 'gdacs', 'hazards', 'outages', 'volcanoes', 'airquality', 'weather', 'pegel', 'energy', 'intelFt', 'osint'] as const).map((k) => (
                <label key={k} className={layers[k] ? 'on' : ''}>
                  <input type="checkbox" checked={layers[k]} onChange={() => toggle(k)} />{k.toUpperCase()}
                </label>
              ))}
              <label className={trailsEnabled ? 'on' : ''} style={{ color: '#ffd23f', marginTop: 4 }}>
                <input type="checkbox" checked={trailsEnabled} onChange={() => setTrailsEnabled(v => !v)} />AIRCRAFT TRAILS
              </label>
              <button
                type="button"
                className="web-search"
                style={{ marginTop: 6, fontSize: 10 }}
                onClick={() => applyViewPreset('full')}
              >
                APPLY FULL PRESET
              </button>
              <label className={heatmapOn ? 'on' : ''} style={{ color: '#ff6b35' }}>
                <input type="checkbox" checked={heatmapOn} onChange={() => setHeatmapOn(v => !v)} />FUSION HEATMAP
              </label>
              {sanctionedMmsi.size > 0 && (
                <div style={{ marginTop: 6, fontSize: 10, color: '#ff2d00' }}>
                  ⚠ {sanctionedMmsi.size} vessel{sanctionedMmsi.size > 1 ? 's' : ''} flagged (OpenSanctions)
                </div>
              )}
              <label className={mvtProvider ? 'on' : ''} style={{ color: '#00e5a0', marginTop: 4 }}>
                <input type="checkbox" checked={!!mvtProvider} onChange={toggleMvt} />MVT (EXPERIMENTAL)
              </label>
              {onClearOsintPins && stats.osint > 0 && (
                <button type="button" className="web-search" style={{ marginTop: 6, fontSize: 10 }} onClick={onClearOsintPins}>
                  CLEAR OSINT PINS
                </button>
              )}
            </>
          )}
        </div>

        <div className="ctl-block">
          <div className="hud-title">FLY TO</div>
          <select className="poi-select" defaultValue="" onChange={(e) => {
            const poi = POIS.find((p) => p.name === e.target.value)
            if (poi) apiRef.current.flyTo?.(poi)
          }}>
            <option value="">— select —</option>
            {POIS.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
          </select>
        </div>
      </div>

      <div className="globe-timeline">
        <div className="tl-head">
          <span>TIMELINE</span>
          {isTimelineLive ? (
            <span className="tl-live">● LIVE</span>
          ) : (
            <span className="tl-time">{fmtTimelineLabel(timelineCutoff)}</span>
          )}
          <button
            type="button"
            className="web-search"
            style={{ fontSize: 9, padding: '2px 6px' }}
            onClick={() => setScrubT(1)}
          >
            LIVE
          </button>
        </div>
        <input
          type="range"
          min={0}
          max={1000}
          value={Math.round(scrubT * 1000)}
          onChange={(e) => setScrubT(Number(e.target.value) / 1000)}
          aria-label="Timeline scrub"
        />
        <div className="tl-hint">
          SEISMIC + EVENTS cumulative · {stats.quakes} quakes · {stats.events} events at cursor
        </div>
        <div className="tl-window">
          {TIMELINE_WINDOWS.map((h) => (
            <button
              key={h}
              type="button"
              className={timelineHours === h ? 'on' : ''}
              onClick={() => setTimelineHours(h)}
            >
              {h}H
            </button>
          ))}
        </div>
      </div>

      {heatmapOn && heatmapMeta && (
        <div className="fusion-legend">
          <div className="fusion-legend-title">FUSION HEATMAP · {heatmapMeta.cells} cells</div>
          <div className="fusion-legend-gradient" />
          <div className="fusion-legend-scale">
            <span>low</span>
            <span>max {heatmapMeta.max.toFixed(1)}</span>
          </div>
          <div className="fusion-legend-contrib">
            {Object.entries(heatmapMeta.contrib).filter(([, n]) => n > 0).map(([k, n]) => (
              <span key={k}>{k}:{n}</span>
            ))}
          </div>
        </div>
      )}

      {hoverTip && (
        <div
          className="globe-tooltip"
          style={{ left: Math.min(hoverTip.x + 14, window.innerWidth - 280), top: hoverTip.y + 14 }}
        >
          <div className="tt-title">{hoverTip.title}</div>
          {hoverTip.lines.map((line, i) => (
            <div key={i} className="tt-line">{line}</div>
          ))}
        </div>
      )}

      {detailOpen && target && (
        <GlobeDetailModal
          target={target}
          onClose={closeDetail}
          onSelectTrafficCam={handleTrafficCamSelect}
          onOpenWindy={onOpenWindy}
          onAskAI={onAskAI}
        />
      )}
    </div>
  )
}
