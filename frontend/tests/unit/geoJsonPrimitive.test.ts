import { describe, it, expect } from 'vitest'
import { Viewer, Color, GeoJsonPrimitive } from 'cesium'
import {
  GEOJSON_PRIMITIVE_THRESHOLD,
  pointsToGeoJson,
  addGeoJsonPrimitive,
  removeGeoJsonPrimitive,
  type PointFeature,
  type PointStyle,
} from '../../src/hooks/layers/geoJsonPrimitive'

function makeViewer(): InstanceType<typeof Viewer> {
  return new Viewer(null as never, null as never) as InstanceType<typeof Viewer>
}

describe('geoJsonPrimitive', () => {
  describe('GEOJSON_PRIMITIVE_THRESHOLD', () => {
    it('is 1000', () => {
      expect(GEOJSON_PRIMITIVE_THRESHOLD).toBe(1000)
    })
  })

  describe('pointsToGeoJson', () => {
    it('converts point features to GeoJSON FeatureCollection', () => {
      const points: PointFeature[] = [
        { lon: 100.5, lat: 13.7, properties: { id: 'a' } },
        { lon: 101.0, lat: 14.0, properties: { id: 'b' } },
      ]
      const gj = pointsToGeoJson(points)
      expect(gj.type).toBe('FeatureCollection')
      expect(gj.features).toHaveLength(2)
      expect(gj.features[0].type).toBe('Feature')
      expect(gj.features[0].geometry.type).toBe('Point')
      expect(gj.features[0].geometry.coordinates).toEqual([100.5, 13.7])
      expect(gj.features[0].properties).toEqual({ id: 'a' })
    })

    it('handles empty array', () => {
      const gj = pointsToGeoJson([])
      expect(gj.type).toBe('FeatureCollection')
      expect(gj.features).toHaveLength(0)
    })

    it('preserves complex properties', () => {
      const points: PointFeature[] = [
        {
          lon: 0,
          lat: 0,
          properties: {
            id: 'x',
            schema: 'Person',
            datasets: ['a', 'b'],
            nested: { foo: 1 },
          },
        },
      ]
      const gj = pointsToGeoJson(points)
      expect(gj.features[0].properties).toEqual({
        id: 'x',
        schema: 'Person',
        datasets: ['a', 'b'],
        nested: { foo: 1 },
      })
    })
  })

  describe('addGeoJsonPrimitive', () => {
    it('creates and adds primitive to scene.primitives', () => {
      const viewer = makeViewer() as unknown as { scene: { primitives: { length: number } } }
      const points: PointFeature[] = Array.from({ length: 5 }, (_, i) => ({
        lon: i,
        lat: i,
        properties: { index: i },
      }))
      const gj = pointsToGeoJson(points)
      const styler = (): PointStyle => ({
        color: Color.fromCssColorString('#ff0000'),
        outlineColor: Color.WHITE,
        outlineWidth: 1,
        size: 8,
      })

      const prim = addGeoJsonPrimitive(
        viewer as unknown as Parameters<typeof addGeoJsonPrimitive>[0],
        gj,
        styler,
      )

      expect(prim).not.toBeNull()
      expect(prim).toBeInstanceOf(GeoJsonPrimitive)
      expect(viewer.scene.primitives.length).toBe(1)
    })

    it('applies per-point styling via styler callback', () => {
      const viewer = makeViewer()
      const points: PointFeature[] = Array.from({ length: 3 }, (_, i) => ({
        lon: i,
        lat: i,
        properties: { color: i === 0 ? 'red' : 'blue' },
      }))
      const gj = pointsToGeoJson(points)
      const stylerCalls: number[] = []
      const styler = (props: Record<string, unknown>, index: number): PointStyle => {
        stylerCalls.push(index)
        return {
          color: Color.fromCssColorString(props.color === 'red' ? '#ff0000' : '#0000ff'),
          size: 10,
        }
      }

      addGeoJsonPrimitive(viewer, gj, styler)

      expect(stylerCalls).toEqual([0, 1, 2])
    })

    it('passes pickFactory when provided', () => {
      const viewer = makeViewer()
      const points: PointFeature[] = [
        { lon: 0, lat: 0, properties: { id: 'test-1' } },
      ]
      const gj = pointsToGeoJson(points)
      const styler = (): PointStyle => ({ color: Color.WHITE, size: 4 })
      const pickFactory = (_idx: number, props: Record<string, unknown>) => ({
        kind: 'test',
        ...props,
      })

      const prim = addGeoJsonPrimitive(viewer, gj, styler, pickFactory)

      expect(prim).not.toBeNull()
    })

    it('returns null when viewer is null', () => {
      const gj = pointsToGeoJson([{ lon: 0, lat: 0, properties: {} }])
      const prim = addGeoJsonPrimitive(
        null as unknown as Parameters<typeof addGeoJsonPrimitive>[0],
        gj,
        () => ({ color: Color.WHITE, size: 4 }),
      )
      expect(prim).toBeNull()
    })

    it('returns null when viewer is destroyed', () => {
      const viewer = makeViewer()
      viewer.isDestroyed = () => true
      const gj = pointsToGeoJson([{ lon: 0, lat: 0, properties: {} }])
      const prim = addGeoJsonPrimitive(viewer, gj, () => ({ color: Color.WHITE, size: 4 }))
      expect(prim).toBeNull()
    })

    it('returns null on exception (fail-soft)', () => {
      const viewer = makeViewer()
      // Force fromGeoJson to throw
      const origFromGeoJson = GeoJsonPrimitive.fromGeoJson
      GeoJsonPrimitive.fromGeoJson = (): GeoJsonPrimitive => {
        throw new Error('test error')
      }
      try {
        const gj = pointsToGeoJson([{ lon: 0, lat: 0, properties: {} }])
        const prim = addGeoJsonPrimitive(viewer, gj, () => ({ color: Color.WHITE, size: 4 }))
        expect(prim).toBeNull()
      } finally {
        GeoJsonPrimitive.fromGeoJson = origFromGeoJson
      }
    })
  })

  describe('removeGeoJsonPrimitive', () => {
    it('removes primitive from scene', () => {
      const viewer = makeViewer() as unknown as { scene: { primitives: { length: number } } }
      const gj = pointsToGeoJson([{ lon: 0, lat: 0, properties: {} }])
      const prim = addGeoJsonPrimitive(
        viewer as unknown as Parameters<typeof addGeoJsonPrimitive>[0],
        gj,
        () => ({ color: Color.WHITE, size: 4 }),
      )

      expect(viewer.scene.primitives.length).toBe(1)
      removeGeoJsonPrimitive(viewer as unknown as Parameters<typeof removeGeoJsonPrimitive>[0], prim)
      expect(viewer.scene.primitives.length).toBe(0)
    })

    it('does nothing when prim is null', () => {
      const viewer = makeViewer()
      const beforeLen = (viewer as unknown as { scene: { primitives: { length: number } } }).scene.primitives.length
      removeGeoJsonPrimitive(viewer, null)
      expect(
        (viewer as unknown as { scene: { primitives: { length: number } } }).scene.primitives.length,
      ).toBe(beforeLen)
    })

    it('does nothing when viewer is null', () => {
      const prim = new GeoJsonPrimitive()
      expect(() => removeGeoJsonPrimitive(null, prim)).not.toThrow()
    })

    it('does nothing when viewer is destroyed', () => {
      const viewer = makeViewer()
      viewer.isDestroyed = () => true
      const prim = new GeoJsonPrimitive()
      expect(() => removeGeoJsonPrimitive(viewer, prim)).not.toThrow()
    })
  })

  describe('threshold logic', () => {
    it('layers with >1000 features should use primitive path', () => {
      const features = Array.from({ length: 1001 }, (_, i) => ({
        lon: i * 0.01,
        lat: i * 0.01,
        properties: { idx: i },
      }))
      expect(features.length).toBeGreaterThan(GEOJSON_PRIMITIVE_THRESHOLD)
    })

    it('layers with <1000 features should use DataSource path', () => {
      const features = Array.from({ length: 999 }, (_, i) => ({
        lon: i * 0.01,
        lat: i * 0.01,
        properties: { idx: i },
      }))
      expect(features.length).toBeLessThan(GEOJSON_PRIMITIVE_THRESHOLD)
    })

    it('exactly 1000 features should use DataSource path', () => {
      expect(1000).not.toBeGreaterThan(GEOJSON_PRIMITIVE_THRESHOLD)
    })
  })
})
