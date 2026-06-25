import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import FeedsStatusPanel from '../../src/components/FeedsStatusPanel'

function wrapWithQueryClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const mockHealth = {
  feeds: {
    gdelt: { status: 'ok', fresh: true, age_sec: 30, count: 100 },
    maritime: { status: 'stale', fresh: false, age_sec: 600, count: 74 },
    quakes: { status: 'ok', fresh: true, age_sec: 60, count: 5 },
  },
}

const mockCredentials = {
  providers: [
    { id: 'gdelt', name: 'GDELT', category: 'osint', tier: 'free', configured: true },
  ],
}

const mockConnectors = {
  connectors: [
    {
      id: 'gdelt',
      name: 'GDELT Events',
      category: 'osint',
      endpoints: ['/api/gdelt/pulse'],
      ttl_sec: 600,
      license: 'free',
      region: ['global'],
      credential_ids: [],
      globe_layer: 'gdelt',
      tier: 'free',
      credentials_mode: 'none',
      credentials_ready: true,
    },
  ],
}

describe('FeedsStatusPanel', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('renders feed rows after load', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: any) => {
      const url = typeof input === 'string' ? input : input.url
      if (url?.includes('/api/health')) return new Response(JSON.stringify(mockHealth), { status: 200 })
      if (url?.includes('/api/credentials')) return new Response(JSON.stringify(mockCredentials), { status: 200 })
      if (url?.includes('/api/connectors')) return new Response(JSON.stringify(mockConnectors), { status: 200 })
      if (url?.includes('/api/stac')) return new Response(JSON.stringify({ features: [] }), { status: 200 })
      return new Response('{}', { status: 404 })
    })

    wrapWithQueryClient(<FeedsStatusPanel />)
    await waitFor(() => {
      // 'gdelt' appears in both connectors table and feed cache table
      expect(screen.getAllByText('gdelt').length).toBeGreaterThan(0)
    })
    expect(screen.getAllByText('maritime').length).toBeGreaterThan(0)
    expect(screen.getAllByText('quakes').length).toBeGreaterThan(0)
    fetchMock.mockRestore()
  })

  it('shows error message on fetch failure', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network down'))
    const { container } = wrapWithQueryClient(<FeedsStatusPanel />)
    await waitFor(() => {
      expect(container.textContent).toContain('network down')
    })
  })

  it('sorts stale feeds first', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: any) => {
      const url = typeof input === 'string' ? input : input.url
      if (url?.includes('/api/health')) return new Response(JSON.stringify(mockHealth), { status: 200 })
      if (url?.includes('/api/credentials')) return new Response(JSON.stringify(mockCredentials), { status: 200 })
      if (url?.includes('/api/connectors')) return new Response(JSON.stringify(mockConnectors), { status: 200 })
      if (url?.includes('/api/stac')) return new Response(JSON.stringify({ features: [] }), { status: 200 })
      return new Response('{}', { status: 404 })
    })

    const { container } = wrapWithQueryClient(<FeedsStatusPanel />)
    await waitFor(() => {
      expect(container.textContent).toContain('FEED CACHE')
    })
    // In the feed cache table, maritime (stale) should appear before gdelt (fresh)
    const feedCacheSection = container.querySelectorAll('table')[1]
    const feedCacheText = feedCacheSection?.textContent || ''
    const maritimeIdx = feedCacheText.indexOf('maritime')
    const gdeltIdx = feedCacheText.indexOf('gdelt')
    expect(maritimeIdx).toBeGreaterThan(-1)
    expect(gdeltIdx).toBeGreaterThan(-1)
    expect(maritimeIdx).toBeLessThan(gdeltIdx)
    fetchMock.mockRestore()
  })
})
