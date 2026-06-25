import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { NodeHealthBanner } from '../../src/components/NodeHealthBanner'

function wrapWithQueryClient(ui: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, refetchInterval: false } },
  })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

describe('NodeHealthBanner', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('renders online banner when Pi is online', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({
        count: 1,
        nodes: [{
          node_id: 'offgrid-pi',
          name: 'Pi Edge',
          online: true,
          age_seconds: 30,
          health: { cpu_temp_c: 55 },
          sensors: { temp_c: 28 },
        }],
      }), { status: 200 }),
    )
    wrapWithQueryClient(<NodeHealthBanner />)
    await waitFor(() => {
      expect(screen.getByText('EDGE ONLINE')).toBeDefined()
    })
    expect(screen.getByText(/CPU 55°C/)).toBeDefined()
    expect(screen.getByText(/room 28°C/)).toBeDefined()
    expect(screen.getByText(/30s ago/)).toBeDefined()
  })

  it('renders offline banner when Pi is offline', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({
        count: 1,
        nodes: [{
          node_id: 'offgrid-pi',
          name: 'Pi Edge',
          online: false,
          age_seconds: 3600,
        }],
      }), { status: 200 }),
    )
    wrapWithQueryClient(<NodeHealthBanner />)
    await waitFor(() => {
      expect(screen.getByText('EDGE OFFLINE')).toBeDefined()
    })
    expect(screen.getByText('Pi Edge')).toBeDefined()
    expect(screen.getByText(/last seen/)).toBeDefined()
  })

  it('renders dismiss button when offline', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({
        count: 1,
        nodes: [{
          node_id: 'offgrid-pi',
          online: false,
          age_seconds: 120,
        }],
      }), { status: 200 }),
    )
    wrapWithQueryClient(<NodeHealthBanner />)
    await waitFor(() => {
      expect(screen.getByText('EDGE OFFLINE')).toBeDefined()
    })
    expect(screen.getByLabelText('Dismiss banner')).toBeDefined()
  })

  it('hides offline banner when dismissed', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({
        count: 1,
        nodes: [{
          node_id: 'offgrid-pi',
          online: false,
          age_seconds: 120,
        }],
      }), { status: 200 }),
    )
    const { container } = wrapWithQueryClient(<NodeHealthBanner />)
    await waitFor(() => {
      expect(screen.getByText('EDGE OFFLINE')).toBeDefined()
    })
    fireEvent.click(screen.getByLabelText('Dismiss banner'))
    await waitFor(() => {
      expect(container.querySelector('.node-banner')).toBeNull()
    })
  })

  it('renders nothing when fetch fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network'))
    const { container } = wrapWithQueryClient(<NodeHealthBanner />)
    await waitFor(() => {
      expect(container.querySelector('.node-banner')).toBeNull()
    })
  })

  it('renders nothing when no nodes returned', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ count: 0, nodes: [] }), { status: 200 }),
    )
    const { container } = wrapWithQueryClient(<NodeHealthBanner />)
    await waitFor(() => {
      expect(container.querySelector('.node-banner')).toBeNull()
    })
  })
})
