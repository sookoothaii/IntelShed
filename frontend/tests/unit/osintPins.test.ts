import { describe, it, expect, beforeEach } from 'vitest'
import { loadOsintPins, saveOsintPins, mergeImportedPins, type OsintPin } from '../../src/lib/osintPins'

describe('osintPins', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  const mockPin = (id: string, overrides: Partial<OsintPin> = {}): OsintPin => ({
    id,
    tool: 'test',
    query: 'q',
    lon: 100,
    lat: 13,
    title: 'Test Pin',
    lines: [],
    ts: Date.now(),
    ...overrides,
  })

  describe('loadOsintPins', () => {
    it('returns empty array when nothing stored', () => {
      expect(loadOsintPins()).toEqual([])
    })

    it('returns parsed pins', () => {
      const pins = [mockPin('p1'), mockPin('p2')]
      saveOsintPins(pins)
      const loaded = loadOsintPins()
      expect(loaded).toHaveLength(2)
      expect(loaded[0].id).toBe('p1')
    })

    it('filters out pins without valid coordinates', () => {
      const badPin = { ...mockPin('bad'), lon: 'NaN' as any }
      saveOsintPins([badPin, mockPin('good')])
      const loaded = loadOsintPins()
      expect(loaded).toHaveLength(1)
      expect(loaded[0].id).toBe('good')
    })

    it('returns empty array for invalid JSON', () => {
      localStorage.setItem('worldbase_osint_pins_v1', '{broken')
      expect(loadOsintPins()).toEqual([])
    })

    it('returns empty array for non-array JSON', () => {
      localStorage.setItem('worldbase_osint_pins_v1', '{"a":1}')
      expect(loadOsintPins()).toEqual([])
    })

    it('limits to MAX_PINS (24)', () => {
      const pins = Array.from({ length: 30 }, (_, i) => mockPin(`p${i}`))
      saveOsintPins(pins)
      const loaded = loadOsintPins()
      expect(loaded).toHaveLength(24)
      expect(loaded[0].id).toBe('p6') // last 24
    })
  })

  describe('saveOsintPins', () => {
    it('writes JSON to localStorage', () => {
      saveOsintPins([mockPin('p1')])
      const raw = localStorage.getItem('worldbase_osint_pins_v1')
      expect(raw).not.toBeNull()
      const parsed = JSON.parse(raw!)
      expect(parsed).toHaveLength(1)
      expect(parsed[0].id).toBe('p1')
    })

    it('truncates to MAX_PINS', () => {
      const pins = Array.from({ length: 30 }, (_, i) => mockPin(`p${i}`))
      saveOsintPins(pins)
      const raw = JSON.parse(localStorage.getItem('worldbase_osint_pins_v1')!)
      expect(raw).toHaveLength(24)
    })
  })

  describe('mergeImportedPins', () => {
    it('deduplicates by id', () => {
      const existing = [mockPin('p1'), mockPin('p2')]
      const imported = [mockPin('p2', { title: 'Updated' }), mockPin('p3')]
      const merged = mergeImportedPins(existing, imported)
      expect(merged).toHaveLength(3)
      const p2 = merged.find((p) => p.id === 'p2')
      expect(p2?.title).toBe('Updated')
    })

    it('limits to MAX_PINS', () => {
      const existing = Array.from({ length: 20 }, (_, i) => mockPin(`e${i}`))
      const imported = Array.from({ length: 20 }, (_, i) => mockPin(`i${i}`))
      const merged = mergeImportedPins(existing, imported)
      expect(merged).toHaveLength(24)
    })
  })
})
