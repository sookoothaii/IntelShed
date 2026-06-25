import { describe, it, expect, beforeEach } from 'vitest'
import {
  HUD_SESSION_KEY,
  readHudSessionStore,
  writeHudSessionStore,
  readHudSessionField,
  writeHudSessionField,
} from '../../src/lib/hudSessionState'

describe('hudSessionState', () => {
  beforeEach(() => {
    sessionStorage.clear()
  })

  describe('readHudSessionStore', () => {
    it('returns empty object when nothing stored', () => {
      expect(readHudSessionStore()).toEqual({})
    })

    it('returns parsed object', () => {
      sessionStorage.setItem(HUD_SESSION_KEY, JSON.stringify({ tab: 'globe', zoom: 5 }))
      expect(readHudSessionStore()).toEqual({ tab: 'globe', zoom: 5 })
    })

    it('returns empty object for invalid JSON', () => {
      sessionStorage.setItem(HUD_SESSION_KEY, '{broken')
      expect(readHudSessionStore()).toEqual({})
    })

    it('returns empty object for array', () => {
      sessionStorage.setItem(HUD_SESSION_KEY, '[1,2,3]')
      expect(readHudSessionStore()).toEqual({})
    })

    it('returns empty object for null', () => {
      sessionStorage.setItem(HUD_SESSION_KEY, 'null')
      expect(readHudSessionStore()).toEqual({})
    })
  })

  describe('writeHudSessionStore', () => {
    it('writes JSON to sessionStorage', () => {
      writeHudSessionStore({ tab: 'chat', dark: true })
      const raw = sessionStorage.getItem(HUD_SESSION_KEY)
      expect(raw).not.toBeNull()
      expect(JSON.parse(raw!)).toEqual({ tab: 'chat', dark: true })
    })
  })

  describe('readHudSessionField', () => {
    it('returns value when present', () => {
      writeHudSessionField('tab', 'globe')
      expect(readHudSessionField('tab', 'default')).toBe('globe')
    })

    it('returns fallback when missing', () => {
      expect(readHudSessionField('missing', 'fallback')).toBe('fallback')
    })

    it('uses validator when provided', () => {
      writeHudSessionField('num', 42)
      const isNum = (v: unknown): v is number => typeof v === 'number'
      expect(readHudSessionField('num', 0, isNum)).toBe(42)
    })

    it('returns fallback when validator fails', () => {
      writeHudSessionField('str', 'hello')
      const isNum = (v: unknown): v is number => typeof v === 'number'
      expect(readHudSessionField('str', 0, isNum)).toBe(0)
    })
  })

  describe('writeHudSessionField', () => {
    it('merges with existing store', () => {
      writeHudSessionField('a', 1)
      writeHudSessionField('b', 2)
      expect(readHudSessionStore()).toEqual({ a: 1, b: 2 })
    })

    it('overwrites existing key', () => {
      writeHudSessionField('x', 'old')
      writeHudSessionField('x', 'new')
      expect(readHudSessionField('x', '')).toBe('new')
    })
  })
})
