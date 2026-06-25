import { describe, it, expect, vi, beforeEach } from 'vitest'
import { canFetch, logFetchError, fetchApi } from '../../src/lib/networkFetch'

describe('networkFetch', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  describe('canFetch', () => {
    it('returns true when navigator.onLine is true', () => {
      Object.defineProperty(navigator, 'onLine', { value: true, configurable: true })
      expect(canFetch()).toBe(true)
    })

    it('returns false when navigator.onLine is false', () => {
      Object.defineProperty(navigator, 'onLine', { value: false, configurable: true })
      expect(canFetch()).toBe(false)
    })
  })

  describe('logFetchError', () => {
    it('logs warning on first call', () => {
      const spy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      logFetchError('test', 'label1')
      expect(spy).toHaveBeenCalledOnce()
    })

    it('suppresses duplicate within cooldown', () => {
      const spy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      logFetchError('test', 'label2')
      logFetchError('test', 'label2')
      expect(spy).toHaveBeenCalledOnce()
    })

    it('logs for different labels', () => {
      const spy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      logFetchError('test', 'labelA')
      logFetchError('test', 'labelB')
      expect(spy).toHaveBeenCalledTimes(2)
    })
  })

  describe('fetchApi', () => {
    it('throws when offline', async () => {
      Object.defineProperty(navigator, 'onLine', { value: false, configurable: true })
      await expect(fetchApi('/api/test')).rejects.toThrow('Browser is offline')
    })

    it('injects API key from localStorage', async () => {
      Object.defineProperty(navigator, 'onLine', { value: true, configurable: true })
      localStorage.setItem('WORLDBASE_API_KEY', 'test-key-123')
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}') as any)
      await fetchApi('/api/test')
      expect(fetchSpy).toHaveBeenCalledOnce()
      const init = fetchSpy.mock.calls[0][1] as RequestInit
      const headers = init.headers as Headers
      expect(headers.get('X-API-Key')).toBe('test-key-123')
    })

    it('does not set X-API-Key when no key present', async () => {
      Object.defineProperty(navigator, 'onLine', { value: true, configurable: true })
      const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}') as any)
      await fetchApi('/api/test')
      const init = fetchSpy.mock.calls[0][1] as RequestInit
      const headers = init.headers as Headers
      expect(headers.get('X-API-Key')).toBeNull()
    })
  })
})
