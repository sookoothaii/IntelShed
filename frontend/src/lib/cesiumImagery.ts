import { Resource, WebMercatorTilingScheme, type Globe, type Scene } from 'cesium'

/** Disable createImageBitmap decode — falls back to Image() path (H3 imagery stall fix). */
const DISABLE_IMAGE_BITMAP =
  import.meta.env.VITE_WORLDBASE_CESIUM_DISABLE_IMAGE_BITMAP !== '0'

let patchesInstalled = false

/** Call before the first Cesium Viewer is constructed. */
export function installCesiumImageryPatches(): void {
  if (patchesInstalled) return
  patchesInstalled = true

  if (DISABLE_IMAGE_BITMAP) {
    ;(Resource as any).supportsImageBitmapOptions = () => Promise.resolve(false)
  }
}

/** Shared ESRI / XYZ tile provider defaults (Web Mercator, CORS-safe). */
export function esriTileProviderOptions(url: string, credit: string) {
  return {
    url,
    credit,
    maximumLevel: 19,
    tilingScheme: new WebMercatorTilingScheme(),
  }
}

/**
 * Reduce imagery reproject pressure — stuck TRANSITIONING tiles keep tilesLoaded false
 * and force continuous globe repaints.
 */
export function tuneGlobeImageryLoading(globe: Globe): void {
  globe.preloadAncestors = false
  globe.preloadSiblings = false
  // Default Cesium SSE is 2.0; 1.0 loads ~4× more tiles at idle.
  if (globe.maximumScreenSpaceError < 2) {
    globe.maximumScreenSpaceError = 2
  }
}

/** Re-apply basemap when tiles stay unloaded (recovery for orphaned reproject queue). */
export function attachTilesLoadedWatchdog(
  scene: Scene,
  recover: () => void,
  stuckMs = 8000,
  cooldownMs = 30000,
): () => void {
  let stuckSince = 0
  let lastRecovery = 0

  const onPostRender = () => {
    if (scene.globe.tilesLoaded) {
      stuckSince = 0
      return
    }
    const now = performance.now()
    if (!stuckSince) stuckSince = now
    if (now - stuckSince < stuckMs) return
    if (now - lastRecovery < cooldownMs) return
    lastRecovery = now
    stuckSince = 0
    console.warn('[Globe] tilesLoaded stuck — recovering imagery pipeline')
    recover()
  }

  scene.postRender.addEventListener(onPostRender)
  return () => {
    try {
      scene.postRender.removeEventListener(onPostRender)
    } catch {
      /* ignore during teardown */
    }
  }
}
