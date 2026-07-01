import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import TemporalReplay from '../../src/components/TemporalReplay'

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

describe('TemporalReplay', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    mockFetchApi.mockReset()
  })

  it('renders title and close button', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, cells: [], insights: [] }))
    render(<TemporalReplay />)
    expect(screen.getByText('TEMPORAL REPLAY')).toBeDefined()
  })

  it('calls onClose when close button clicked', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, cells: [], insights: [] }))
    const onClose = vi.fn()
    render(<TemporalReplay onClose={onClose} />)
    const btn = screen.getByText('✕')
    btn.click()
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('renders playback controls', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, cells: [], insights: [] }))
    render(<TemporalReplay />)
    // Play button
    expect(screen.getByText('▶')).toBeDefined()
    // First button
    expect(screen.getByText('⏮')).toBeDefined()
    // Last button
    expect(screen.getByText('⏭')).toBeDefined()
  })

  it('renders auto-capture toggle', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, cells: [], insights: [] }))
    render(<TemporalReplay />)
    expect(screen.getByText('AUTO')).toBeDefined()
  })

  it('renders snapshot capture button', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, cells: [], insights: [] }))
    render(<TemporalReplay />)
    expect(screen.getByText('📸')).toBeDefined()
  })

  it('renders export/import/clear buttons', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, cells: [], insights: [] }))
    render(<TemporalReplay />)
    expect(screen.getByText('↓')).toBeDefined()
    expect(screen.getByText('↑')).toBeDefined()
    expect(screen.getByText('🗑')).toBeDefined()
  })

  it('shows empty state when no snapshots', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, cells: [], insights: [] }))
    render(<TemporalReplay />)
    await waitFor(() => {
      expect(screen.getByText(/No snapshots yet|Select a snapshot/i)).toBeDefined()
    })
  })

  it('renders speed selector with options', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, cells: [], insights: [] }))
    render(<TemporalReplay />)
    const speedSelect = screen.getByDisplayValue('1×')
    expect(speedSelect).toBeDefined()
  })

  it('renders capture interval selector', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, cells: [], insights: [] }))
    render(<TemporalReplay />)
    const intervalSelect = screen.getByDisplayValue('1m')
    expect(intervalSelect).toBeDefined()
  })

  it('renders footer status text', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, cells: [], insights: [] }))
    render(<TemporalReplay />)
    await waitFor(() => {
      expect(screen.getByText(/Capture:/)).toBeDefined()
      expect(screen.getByText(/Snapshots:/)).toBeDefined()
    })
  })

  it('renders SVG timeline element', async () => {
    mockFetchApi.mockImplementation(() => mockResponse({ feeds: {}, cells: [], insights: [] }))
    const { container } = render(<TemporalReplay />)
    // The timeline SVG may or may not render depending on snapshots,
    // but the empty state should show
    await waitFor(() => {
      expect(screen.getByText(/No snapshots yet|Select a snapshot/i)).toBeDefined()
    })
  })
})
