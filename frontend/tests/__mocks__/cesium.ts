// Minimal Cesium mock for unit/component tests — avoids loading 30MB WASM

export const Ion = {
  defaultAccessToken: '',
}

export class Color {
  red = 1
  green = 1
  blue = 1
  alpha = 1
  static WHITE = new Color()
  static BLACK = Object.assign(new Color(), { red: 0, green: 0, blue: 0 })
  static fromCssColorString(_css: string): Color {
    return new Color()
  }
  withAlpha(a: number): Color {
    const c = new Color()
    c.red = this.red
    c.green = this.green
    c.blue = this.blue
    c.alpha = a
    return c
  }
}

export class Cartesian3 {
  x = 0
  y = 0
  z = 0
  static fromDegrees(_lon: number, _lat: number, _h = 0): Cartesian3 {
    return new Cartesian3()
  }
}

export class NearFarScalar {
  constructor(public near = 0, public nearVal = 1, public far = 0, public farVal = 1) {}
}

export class BufferPoint {
  featureId = 0
  get(_index: number, _target: BufferPoint): void {}
  setMaterial(_material: BufferPointMaterial): void {}
}

export class BufferPointMaterial {
  color = new Color()
  outlineColor = new Color()
  outlineWidth = 0
  size = 4
}

export class BufferPointCollection {
  primitiveCount = 0
  show = true
  get(index: number, target: BufferPoint): void {
    target.featureId = index
  }
}

export class GeoJsonPrimitive {
  points: BufferPointCollection | null = null
  polylines: unknown = null
  polygons: unknown = null
  properties: Record<number, Record<string, unknown>> = {}
  static fromGeoJson(geoJson: unknown, _opts?: unknown): GeoJsonPrimitive {
    const gj = geoJson as { features: Array<{ properties: Record<string, unknown> }> }
    const prim = new GeoJsonPrimitive()
    prim.points = new BufferPointCollection()
    prim.points.primitiveCount = gj.features?.length ?? 0
    prim.properties = {}
    gj.features?.forEach((f, i) => {
      prim.properties[i] = f.properties
    })
    return prim
  }
}

export class CustomDataSource {
  name: string
  show = true
  entities = {
    suspendEvents: () => {},
    resumeEvents: () => {},
    removeAll: () => {},
    add: () => ({ id: 'mock-entity' }),
    remove: () => {},
    getById: () => null,
    values: [] as unknown[],
  }
  constructor(name: string) {
    this.name = name
  }
}

export class PointPrimitiveCollection {
  show = true
  add() { return { show: true } }
  get() { return { show: true } }
  remove() {}
  destroy() {}
}

export class LabelCollection {
  show = true
  add() { return { show: true } }
  get() { return { show: true } }
  remove() {}
  destroy() {}
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
    primitives: {
      _items: [] as unknown[],
      add(item: unknown) { (this._items as unknown[]).push(item) },
      remove(item: unknown) {
        const idx = (this._items as unknown[]).indexOf(item)
        if (idx >= 0) (this._items as unknown[]).splice(idx, 1)
      },
      get length() { return (this._items as unknown[]).length },
    },
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
    remove: () => {},
  }
  isDestroyed = () => false
  destroy = () => {}
}

export type TerrainProvider = EllipsoidTerrainProvider
