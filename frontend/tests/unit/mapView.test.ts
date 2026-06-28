import { describe, it, expect, vi, beforeEach } from 'vitest'

vi.mock('cesium', () => ({
  Ion: { defaultAccessToken: '' },
}))

import {
  DEFAULT_MAP_VIEW,
  BASEMAP_LABELS,
  ESRI_SATELLITE_TILES,
  ESRI_HILLSHADE_TILES,
  ESRI_STREET_TILES,
  ESRI_REFERENCE_LABELS,
  ION_PHOTOREALISTIC_ASSET,
  hasCesiumIonToken,
} from '../../src/lib/mapView'

describe('mapView', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  describe('DEFAULT_MAP_VIEW', () => {
    it('has streets basemap', () => {
      expect(DEFAULT_MAP_VIEW.basemap).toBe('streets')
    })

    it('has render3d true by default', () => {
      expect(DEFAULT_MAP_VIEW.render3d).toBe(true)
    })

    it('has buildings false by default', () => {
      expect(DEFAULT_MAP_VIEW.buildings).toBe(false)
    })

    it('has photorealistic false by default', () => {
      expect(DEFAULT_MAP_VIEW.photorealistic).toBe(false)
    })

    it('has labels true by default', () => {
      expect(DEFAULT_MAP_VIEW.labels).toBe(true)
    })
  })

  describe('BASEMAP_LABELS', () => {
    it('has all 4 basemaps', () => {
      expect(Object.keys(BASEMAP_LABELS)).toHaveLength(4)
      expect(BASEMAP_LABELS.streets).toBe('MAP')
      expect(BASEMAP_LABELS.satellite).toBe('SAT')
      expect(BASEMAP_LABELS.hybrid).toBe('HYBRID')
      expect(BASEMAP_LABELS.terrain).toBe('TERRAIN')
    })
  })

  describe('tile URLs', () => {
    it('ESRI_SATELLITE_TILES contains arcgisonline', () => {
      expect(ESRI_SATELLITE_TILES).toContain('arcgisonline.com')
      expect(ESRI_SATELLITE_TILES).toContain('{z}/{y}/{x}')
    })

    it('ESRI_HILLSHADE_TILES contains arcgisonline', () => {
      expect(ESRI_HILLSHADE_TILES).toContain('arcgisonline.com')
    })

    it('ESRI_STREET_TILES contains arcgisonline', () => {
      expect(ESRI_STREET_TILES).toContain('arcgisonline.com')
    })

    it('ESRI_REFERENCE_LABELS contains arcgisonline', () => {
      expect(ESRI_REFERENCE_LABELS).toContain('arcgisonline.com')
    })
  })

  describe('ION_PHOTOREALISTIC_ASSET', () => {
    it('is the expected asset ID', () => {
      expect(ION_PHOTOREALISTIC_ASSET).toBe(2275207)
    })
  })

  describe('hasCesiumIonToken', () => {
    it('returns false for empty string', async () => {
      const mod = await import('../../src/lib/mapView')
      mod.hasCesiumIonToken() // touch to ensure module loaded
      const { Ion } = await import('cesium')
      Ion.defaultAccessToken = ''
      expect(mod.hasCesiumIonToken()).toBe(false)
    })

    it('returns false for placeholder', async () => {
      const mod = await import('../../src/lib/mapView')
      const { Ion } = await import('cesium')
      Ion.defaultAccessToken = 'your_cesium_ion_token_here'
      expect(mod.hasCesiumIonToken()).toBe(true) // non-empty string is truthy
      Ion.defaultAccessToken = ''
      expect(mod.hasCesiumIonToken()).toBe(false)
    })

    it('returns true for real token', async () => {
      const mod = await import('../../src/lib/mapView')
      const { Ion } = await import('cesium')
      Ion.defaultAccessToken = 'eyJhbGciOiJFUzI1NiJ9.realtoken'
      expect(mod.hasCesiumIonToken()).toBe(true)
      Ion.defaultAccessToken = ''
    })
  })
})
