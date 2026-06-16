export const MIN_CAMERA_HEIGHT = 50
export const MAX_CAMERA_HEIGHT = 40_000_000

export function clampCameraHeight(height: number, fallback = 400_000): number {
  if (!Number.isFinite(height)) return fallback
  return Math.min(MAX_CAMERA_HEIGHT, Math.max(MIN_CAMERA_HEIGHT, height))
}

export function zoomToGlobeHeight(zoom: number, fallback = 400_000): number {
  if (!Number.isFinite(zoom)) return fallback
  const z = Math.min(22, Math.max(0, zoom))
  return clampCameraHeight(MAX_CAMERA_HEIGHT / Math.pow(2, z), fallback)
}

export function globeHeightToZoom(height: number, fallback = 4): number {
  const h = clampCameraHeight(height)
  const z = Math.log2(MAX_CAMERA_HEIGHT / h)
  if (!Number.isFinite(z)) return fallback
  return Math.min(22, Math.max(0, z))
}

export function sanitizeLonLat(
  lon: number,
  lat: number,
): { lon: number; lat: number } | null {
  if (!Number.isFinite(lon) || !Number.isFinite(lat)) return null
  if (lat < -90 || lat > 90) return null
  let lng = lon
  while (lng > 180) lng -= 360
  while (lng < -180) lng += 360
  return { lon: lng, lat }
}

export const MAP_PITCH_MAX = 85

/** MapLibre pitch 0 = straight down; Cesium pitch -90 = straight down. */
export function mapPitchToCesiumDeg(mapPitch: number, fallback = -45): number {
  if (!Number.isFinite(mapPitch)) return fallback
  const mp = Math.min(MAP_PITCH_MAX, Math.max(0, mapPitch))
  return mp - 90
}

/** Inverse: Cesium pitch (deg, negative = down) → MapLibre pitch. */
export function cesiumPitchToMapDeg(cesiumPitchDeg: number, fallback = 0): number {
  if (!Number.isFinite(cesiumPitchDeg)) return fallback
  const cp = Math.min(0, Math.max(-90, cesiumPitchDeg))
  return Math.min(MAP_PITCH_MAX, Math.max(0, cp + 90))
}

export function containerHasSize(el: HTMLElement | null): boolean {
  return !!el && el.clientWidth > 0 && el.clientHeight > 0
}
