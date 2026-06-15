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

export function containerHasSize(el: HTMLElement | null): boolean {
  return !!el && el.clientWidth > 0 && el.clientHeight > 0
}
