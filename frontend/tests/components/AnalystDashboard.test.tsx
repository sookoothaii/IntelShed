import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import AnalystDashboard from '../../src/components/AnalystDashboard'

// Mock fetchApi
vi.mock('../../src/lib/networkFetch', () => ({
  fetchApi: vi.fn(),
}))

import { fetchApi } from '../../src/lib/networkFetch'
const mockFetchApi = vi.mocked(fetchApi)

function mockResponse(data: unknown) {
  return Promise.resolve({
    ok: true,
    json: () => Promise.resolve(data),
  } as Response)
}

describe('AnalystDashboard', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    mockFetchApi.mockReset()
  })

  it('renders title and close button', async () => {
    mockFetchApi.mockImplementation((url: unknown) => {
      const u = String(url)
      if (u.includes('/api/health')) return mockResponse({ feeds: {} })
      if (u.includes('/api/insights')) return mockResponse({ insights: [] })
      if (u.includes('/api/fusion/heatmap')) return mockResponse({ cells: [] })
      return mockResponse({})
    })

    render(<AnalystDashboard />)
    expect(screen.getByText('ANALYST DASHBOARD')).toBeDefined()
  })

  it('renders close button and calls onClose', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, insights: [], cells: [] }))
    const onClose = vi.fn()
    render(<AnalystDashboard onClose={onClose} />)
    const btn = screen.getByText('✕')
    btn.click()
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('renders Sankey panel label', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, insights: [], cells: [] }))
    render(<AnalystDashboard />)
    expect(screen.getByText('FEED FLOW — SANKEY')).toBeDefined()
  })

  it('renders timeline panel label', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, insights: [], cells: [] }))
    render(<AnalystDashboard />)
    expect(screen.getByText('EVENT TIMELINE')).toBeDefined()
  })

  it('renders heatmap panel label', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, insights: [], cells: [] }))
    render(<AnalystDashboard />)
    expect(screen.getByText('FUSION HEATMAP')).toBeDefined()
  })

  it('renders poll metrics panel', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, insights: [], cells: [] }))
    render(<AnalystDashboard />)
    expect(screen.getByText('POLL METRICS')).toBeDefined()
  })

  it('shows poll status indicators', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, insights: [], cells: [] }))
    render(<AnalystDashboard />)
    await waitFor(() => {
      expect(screen.getByText(/HEALTH:/)).toBeDefined()
      expect(screen.getByText(/INSIGHTS:/)).toBeDefined()
      expect(screen.getByText(/HEATMAP:/)).toBeDefined()
    })
  })

  it('renders SVG elements for visualizations', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, insights: [], cells: [] }))
    const { container } = render(<AnalystDashboard />)
    await waitFor(() => {
      const svgs = container.querySelectorAll('svg.sankey-svg, svg.timeline-svg, svg.heatmap-svg')
      expect(svgs.length).toBeGreaterThanOrEqual(1)
    })
  })

  it('displays empty state for timeline when no events', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, insights: [], cells: [] }))
    render(<AnalystDashboard />)
    await waitFor(() => {
      expect(screen.getByText('No events in window')).toBeDefined()
    })
  })

  it('displays empty state for heatmap when no cells', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, insights: [], cells: [] }))
    render(<AnalystDashboard />)
    await waitFor(() => {
      expect(screen.getByText('No heatmap data')).toBeDefined()
    })
  })
})
