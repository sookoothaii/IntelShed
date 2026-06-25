// Minimal Cesium mock for unit/component tests — avoids loading 30MB WASM

export const Ion = {
  defaultAccessToken: '',
}

export class EllipsoidTerrainProvider {
  errorEvent = { addEventListener: () => {}, removeEventListener: () => {} }
}

export async function createWorldTerrainAsync() {
  return new EllipsoidTerrainProvider()
}

export const Viewer = class MockViewer {
  scene = {
    globe: { depthTestAgainstTerrain: false },
    renderError: { addEventListener: () => {} },
    requestRender: () => {},
  }
  terrainProvider = null
  camera = {
    flyTo: () => Promise.resolve(),
    lookAt: () => {},
  }
  entities = {
    add: () => ({ id: 'mock-entity' }),
    removeAll: () => {},
    values: [],
  }
  imageryLayers = {
    addImageryProvider: () => {},
    removeAll: () => {},
  }
  dataSources = {
    add: () => Promise.resolve(),
    getByName: () => null,
  }
  isDestroyed = () => false
  destroy = () => {}
}

export type TerrainProvider = EllipsoidTerrainProvider
