/** Shared map view state — Google Maps-style basemap + 2D/3D switching. */

import { Ion } from 'cesium'

export type BasemapMode = 'streets' | 'satellite' | 'hybrid' | 'terrain'

export type MapViewMode = {
  /** Vector streets, satellite imagery, hybrid labels, or hillshade terrain */
  basemap: BasemapMode
  /** 3D tilt + depth (Cesium SCENE3D or MapLibre pitch) */
  render3d: boolean
  /** OSM / vector building extrusion */
  buildings: boolean
  /** Cesium Ion Google Photorealistic 3D Tiles (needs Ion token from /api/config/cesium) */
  photorealistic: boolean
  /** Place/city name label overlay (Esri World Boundaries & Places) */
  labels: boolean
}

export const DEFAULT_MAP_VIEW: MapViewMode = {
  basemap: 'streets',
  render3d: true,
  buildings: false,
  photorealistic: false,
  labels: true,
}

export const BASEMAP_LABELS: Record<BasemapMode, string> = {
  streets: 'MAP',
  satellite: 'SAT',
  hybrid: 'HYBRID',
  terrain: 'TERRAIN',
}

/** ESRI World Imagery — free, no API key (attribution required). */
export const ESRI_SATELLITE_TILES =
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'

/** ESRI World Hillshade for terrain-shaded basemap. */
export const ESRI_HILLSHADE_TILES =
  'https://server.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}'

/** ESRI streets — CORS-safe in Vite dev (OSM tile server blocks browser XHR). */
export const ESRI_STREET_TILES =
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}'

/** Label overlay for hybrid satellite view. */
export const ESRI_REFERENCE_LABELS =
  'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}'

/** Cesium Ion asset: Google Photorealistic 3D Tiles */
export const ION_PHOTOREALISTIC_ASSET = 2275207

export function hasCesiumIonToken(): boolean {
  return Boolean(Ion.defaultAccessToken)
}
