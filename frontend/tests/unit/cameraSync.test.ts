import { describe, it, expect } from 'vitest'
import {
  clampCameraHeight,
  zoomToGlobeHeight,
  globeHeightToZoom,
  sanitizeLonLat,
  mapPitchToCesiumDeg,
  cesiumPitchToMapDeg,
  containerHasSize,
  MIN_CAMERA_HEIGHT,
  MAX_CAMERA_HEIGHT,
  MAP_PITCH_MAX,
} from '../../src/lib/cameraSync'

describe('cameraSync', () => {
  describe('clampCameraHeight', () => {
    it('clamps below minimum', () => {
      expect(clampCameraHeight(10)).toBe(MIN_CAMERA_HEIGHT)
    })

    it('clamps above maximum', () => {
      expect(clampCameraHeight(99_999_999)).toBe(MAX_CAMERA_HEIGHT)
    })

    it('passes through valid value', () => {
      expect(clampCameraHeight(500_000)).toBe(500_000)
    })

    it('returns fallback for NaN', () => {
      expect(clampCameraHeight(NaN, 300_000)).toBe(300_000)
    })

    it('returns fallback for Infinity', () => {
      expect(clampCameraHeight(Infinity, 300_000)).toBe(300_000)
    })
  })

  describe('zoomToGlobeHeight', () => {
    it('zoom 0 = max height', () => {
      expect(zoomToGlobeHeight(0)).toBe(MAX_CAMERA_HEIGHT)
    })

    it('zoom 22 = min height', () => {
      const h = zoomToGlobeHeight(22)
      expect(h).toBeGreaterThanOrEqual(MIN_CAMERA_HEIGHT)
      expect(h).toBeLessThan(100)
    })

    it('clamps zoom > 22', () => {
      expect(zoomToGlobeHeight(30)).toBe(zoomToGlobeHeight(22))
    })

    it('clamps zoom < 0', () => {
      expect(zoomToGlobeHeight(-5)).toBe(zoomToGlobeHeight(0))
    })

    it('returns fallback for NaN zoom', () => {
      expect(zoomToGlobeHeight(NaN, 999_999)).toBe(999_999)
    })
  })

  describe('globeHeightToZoom', () => {
    it('max height = zoom 0', () => {
      expect(globeHeightToZoom(MAX_CAMERA_HEIGHT)).toBeCloseTo(0, 5)
    })

    it('min height = high zoom', () => {
      const z = globeHeightToZoom(MIN_CAMERA_HEIGHT)
      expect(z).toBeGreaterThan(19)
      expect(z).toBeLessThanOrEqual(22)
    })

    it('clamps NaN height to fallback before computing zoom', () => {
      // NaN → clampCameraHeight returns fallback 400000 → log2(40M/400k) ≈ 6.64
      const z = globeHeightToZoom(NaN)
      expect(z).toBeGreaterThan(6)
      expect(z).toBeLessThan(8)
    })
  })

  describe('sanitizeLonLat', () => {
    it('passes valid coordinates', () => {
      expect(sanitizeLonLat(100.5, 13.7)).toEqual({ lon: 100.5, lat: 13.7 })
    })

    it('wraps longitude > 180', () => {
      const r = sanitizeLonLat(190, 13)
      expect(r).not.toBeNull()
      expect(r!.lon).toBe(-170)
    })

    it('wraps longitude < -180', () => {
      const r = sanitizeLonLat(-190, 13)
      expect(r).not.toBeNull()
      expect(r!.lon).toBe(170)
    })

    it('rejects lat > 90', () => {
      expect(sanitizeLonLat(100, 91)).toBeNull()
    })

    it('rejects lat < -90', () => {
      expect(sanitizeLonLat(100, -91)).toBeNull()
    })

    it('rejects NaN', () => {
      expect(sanitizeLonLat(NaN, 13)).toBeNull()
      expect(sanitizeLonLat(100, NaN)).toBeNull()
    })
  })

  describe('mapPitchToCesiumDeg', () => {
    it('pitch 0 = -90 (straight down)', () => {
      expect(mapPitchToCesiumDeg(0)).toBe(-90)
    })

    it('pitch 90 clamps to MAP_PITCH_MAX then converts', () => {
      expect(mapPitchToCesiumDeg(90)).toBe(MAP_PITCH_MAX - 90)
    })

    it('clamps pitch > 85', () => {
      expect(mapPitchToCesiumDeg(100)).toBe(MAP_PITCH_MAX - 90)
    })

    it('returns fallback for NaN', () => {
      expect(mapPitchToCesiumDeg(NaN, -45)).toBe(-45)
    })
  })

  describe('cesiumPitchToMapDeg', () => {
    it('-90 = pitch 0 (straight down)', () => {
      expect(cesiumPitchToMapDeg(-90)).toBe(0)
    })

    it('0 = pitch MAP_PITCH_MAX (clamped from 90)', () => {
      expect(cesiumPitchToMapDeg(0)).toBe(MAP_PITCH_MAX)
    })

    it('clamps to MAP_PITCH_MAX', () => {
      expect(cesiumPitchToMapDeg(10)).toBe(MAP_PITCH_MAX)
    })

    it('returns fallback for NaN', () => {
      expect(cesiumPitchToMapDeg(NaN, 30)).toBe(30)
    })
  })

  describe('containerHasSize', () => {
    it('returns true for element with dimensions', () => {
      const el = document.createElement('div')
      Object.defineProperty(el, 'clientWidth', { value: 800 })
      Object.defineProperty(el, 'clientHeight', { value: 600 })
      expect(containerHasSize(el)).toBe(true)
    })

    it('returns false for zero-width element', () => {
      const el = document.createElement('div')
      Object.defineProperty(el, 'clientWidth', { value: 0 })
      Object.defineProperty(el, 'clientHeight', { value: 600 })
      expect(containerHasSize(el)).toBe(false)
    })

    it('returns false for null', () => {
      expect(containerHasSize(null)).toBe(false)
    })
  })
})
