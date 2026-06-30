import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  getEntityTimeline,
  listCredentials,
  setCredential,
  deleteCredential,
} from '../../src/lib/session7Api'

// Mock fetchApi
vi.mock('../../src/lib/networkFetch', () => ({
  fetchApi: vi.fn(),
}))

import { fetchApi } from '../../src/lib/networkFetch'
const mockFetchApi = vi.mocked(fetchApi)

describe('session7Api', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    mockFetchApi.mockReset()
  })

  describe('getEntityTimeline', () => {
    it('fetches timeline for entity id', async () => {
      const mockData = {
        entity_id: 'test-id',
        found: true,
        schema: 'Person',
        caption: 'Alice',
        first_seen: '2024-01-01T00:00:00Z',
        last_seen: '2024-06-01T00:00:00Z',
        event_count: 2,
        events: [
          { type: 'entity_created', timestamp: '2024-01-01T00:00:00Z', detail: 'Entity created (Person)' },
        ],
      }
      mockFetchApi.mockResolvedValue({
        ok: true,
        json: async () => mockData,
      } as Response)

      const result = await getEntityTimeline('test-id')
      expect(result.found).toBe(true)
      expect(result.schema).toBe('Person')
      expect(result.events).toHaveLength(1)
      expect(mockFetchApi).toHaveBeenCalledWith(
        '/api/intel/entities/test-id/timeline',
      )
    })

    it('handles not found entity', async () => {
      mockFetchApi.mockResolvedValue({
        ok: true,
        json: async () => ({
          entity_id: 'nonexistent',
          found: false,
          events: [],
        }),
      } as Response)

      const result = await getEntityTimeline('nonexistent')
      expect(result.found).toBe(false)
      expect(result.events).toEqual([])
    })
  })

  describe('listCredentials', () => {
    it('returns stored credentials', async () => {
      mockFetchApi.mockResolvedValue({
        ok: true,
        json: async () => ({
          credentials: [
            { env_var: 'API_KEY', masked: '********', has_value: true },
          ],
        }),
      } as Response)

      const result = await listCredentials()
      expect(result.credentials).toHaveLength(1)
      expect(result.credentials[0].env_var).toBe('API_KEY')
    })

    it('throws on non-ok response', async () => {
      mockFetchApi.mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
      } as Response)

      await expect(listCredentials()).rejects.toThrow('500')
    })
  })

  describe('setCredential', () => {
    it('posts credential to API', async () => {
      mockFetchApi.mockResolvedValue({
        ok: true,
        json: async () => ({ env_var: 'TEST_KEY', set: true }),
      } as Response)

      const result = await setCredential('TEST_KEY', 'secret123')
      expect(result.set).toBe(true)
      expect(mockFetchApi).toHaveBeenCalledWith(
        '/api/credentials',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ env_var: 'TEST_KEY', value: 'secret123' }),
        },
      )
    })
  })

  describe('deleteCredential', () => {
    it('deletes credential by env var', async () => {
      mockFetchApi.mockResolvedValue({
        ok: true,
        json: async () => ({ env_var: 'TEST_KEY', deleted: true }),
      } as Response)

      const result = await deleteCredential('TEST_KEY')
      expect(result.deleted).toBe(true)
      expect(mockFetchApi).toHaveBeenCalledWith(
        '/api/credentials/TEST_KEY',
        { method: 'DELETE' },
      )
    })
  })
})
