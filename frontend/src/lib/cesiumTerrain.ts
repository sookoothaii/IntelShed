import {
  createWorldTerrainAsync,
  EllipsoidTerrainProvider,
  Ion,
  type TerrainProvider,
  type Viewer,
} from 'cesium'

/** World Terrain when Ion token works; flat ellipsoid when Ion is down or missing. */
export async function createTerrainWithFallback(): Promise<TerrainProvider> {
  if (!Ion.defaultAccessToken) {
    console.warn('[WorldBase] Cesium Ion token missing — ellipsoid terrain only.')
    return new EllipsoidTerrainProvider()
  }
  try {
    return await createWorldTerrainAsync()
  } catch (err) {
    console.warn('[WorldBase] World Terrain init failed — ellipsoid fallback.', err)
    return new EllipsoidTerrainProvider()
  }
}

/** After repeated tile 503/401 errors, switch to ellipsoid so the globe stays usable. */
export function attachTerrainFailover(viewer: Viewer, provider: TerrainProvider): () => void {
  if (provider instanceof EllipsoidTerrainProvider) return () => {}

  let fails = 0
  const onError = () => {
    fails += 1
    if (fails < 5) return
    if (viewer.isDestroyed?.()) return
    try {
      viewer.terrainProvider = new EllipsoidTerrainProvider()
      viewer.scene.globe.depthTestAgainstTerrain = false
      viewer.scene.requestRender()
      console.warn(
        '[WorldBase] Cesium Ion terrain tiles failing (503/quota) — switched to ellipsoid fallback.',
      )
    } catch {
      /* ignore during teardown */
    }
  }

  provider.errorEvent.addEventListener(onError)
  return () => {
    try {
      provider.errorEvent.removeEventListener(onError)
    } catch {
      /* ignore */
    }
  }
}
