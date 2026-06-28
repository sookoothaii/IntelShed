import {
  GeoJsonPrimitive,
  BufferPoint,
  BufferPointMaterial,
  Color,
  type Viewer,
} from 'cesium'
import { viewerAlive } from './layerUtils'

/**
 * Feature count above which we use GeoJsonPrimitive (buffer primitive path)
 * instead of CustomDataSource (entity path). The buffer path bypasses the
 * Entity/DataSource layer and renders directly into BufferPointCollection,
 * providing 10x+ throughput for large datasets.
 *
 * Below this threshold, DataSource offers richer styling (labels,
 * DistanceDisplayCondition, NearFarScalar) at no performance cost.
 */
export const GEOJSON_PRIMITIVE_THRESHOLD = 1000

export type PointFeature = {
  lon: number
  lat: number
  properties: Record<string, unknown>
}

export type GeoJsonPointCollection = {
  type: 'FeatureCollection'
  features: Array<{
    type: 'Feature'
    geometry: { type: 'Point'; coordinates: [number, number] }
    properties: Record<string, unknown>
  }>
}

/** Convert array of point features into a GeoJSON FeatureCollection. */
export function pointsToGeoJson(points: PointFeature[]): GeoJsonPointCollection {
  return {
    type: 'FeatureCollection',
    features: points.map((p) => ({
      type: 'Feature' as const,
      geometry: { type: 'Point' as const, coordinates: [p.lon, p.lat] },
      properties: p.properties,
    })),
  }
}

export type PointStyle = {
  color: Color
  outlineColor?: Color
  outlineWidth?: number
  size?: number
}

export type PointStyler = (
  props: Record<string, unknown>,
  index: number,
) => PointStyle

export type PickFactory = (
  index: number,
  properties: Record<string, unknown>,
) => Record<string, unknown> | undefined

/**
 * Create a GeoJsonPrimitive from a GeoJSON FeatureCollection, add it to the
 * scene, and apply per-point styling. Returns null on failure (fail-soft).
 *
 * The primitive is added to `scene.primitives` (not `viewer.dataSources`),
 * bypassing the Entity layer for high-throughput rendering.
 */
export function addGeoJsonPrimitive(
  viewer: Viewer,
  geoJson: GeoJsonPointCollection,
  styler: PointStyler,
  pickFactory?: PickFactory,
): GeoJsonPrimitive | null {
  if (!viewerAlive(viewer)) return null
  try {
    const prim = GeoJsonPrimitive.fromGeoJson(geoJson, {
      allowPicking: pickFactory != null,
      pickObjectFactory: pickFactory
        ? (index: number, _collection: unknown, properties: Record<string, unknown>) =>
            pickFactory(index, properties ?? {})
        : undefined,
    })
    viewer.scene.primitives.add(prim)

    // Apply per-point materials by iterating the BufferPointCollection.
    // BufferPoint is a flyweight — reuse a single instance across the loop.
    if (prim.points) {
      const point = new BufferPoint()
      const material = new BufferPointMaterial()
      for (let i = 0; i < prim.points.primitiveCount; i++) {
        prim.points.get(i, point)
        const props = prim.properties[point.featureId] || {}
        const style = styler(props, i)
        material.color = style.color
        material.outlineColor = style.outlineColor ?? Color.WHITE
        material.outlineWidth = style.outlineWidth ?? 0
        material.size = style.size ?? 4
        point.setMaterial(material)
      }
    }

    return prim
  } catch (e) {
    console.warn('[GeoJsonPrimitive] Failed to create primitive:', e)
    return null
  }
}

/** Remove and destroy a GeoJsonPrimitive from the scene. */
export function removeGeoJsonPrimitive(
  viewer: Viewer | null,
  prim: GeoJsonPrimitive | null,
): void {
  if (!prim || !viewerAlive(viewer)) return
  try {
    viewer.scene.primitives.remove(prim)
  } catch {
    /* viewer already destroyed */
  }
}
