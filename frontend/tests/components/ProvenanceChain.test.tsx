import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import ProvenanceChain, { ProvenanceGlobalStats } from '../../src/components/ProvenanceChain'

/* ── Mock fetchApi ─────────────────────────────────────────────────────────── */

vi.mock('../../src/lib/networkFetch', () => ({
  fetchApi: vi.fn(),
}))

import { fetchApi } from '../../src/lib/networkFetch'
const mockFetch = fetchApi as ReturnType<typeof vi.fn>

function mockResponse(data: unknown) {
  return {
    ok: true,
    json: () => Promise.resolve(data),
  }
}

beforeEach(() => {
  mockFetch.mockReset()
})

/* ── ProvenanceChain ──────────────────────────────────────────────────────── */

describe('ProvenanceChain', () => {
  it('renders null when entityId is empty', () => {
    const { container } = render(<ProvenanceChain entityId="" />)
    expect(container.firstChild).toBeNull()
  })

  it('renders loading state initially', () => {
    mockFetch.mockReturnValue(new Promise(() => {})) // never resolves
    const { container } = render(<ProvenanceChain entityId="ent-123" />)
    expect(container.querySelector('.provenance-chain-loading')).not.toBeNull()
  })

  it('renders provenance data after successful fetch', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-123',
        datasets: ['gdacs', 'gdelt'],
        total_statements: 5,
        by_prop: {
          name: { count: 2, datasets: ['gdacs', 'gdelt'] },
          country: { count: 1, datasets: ['gdacs'] },
        },
        by_dataset: { gdacs: 3, gdelt: 2 },
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        total: 5,
        scored: 5,
        avg_score: 0.8,
        min_score: 0.5,
        max_score: 1.0,
        by_dataset: { gdacs: { count: 3, avg_score: 0.85 }, gdelt: { count: 2, avg_score: 0.7 } },
        conflicts: 0,
        entity_id: 'ent-123',
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-123',
        conflicts: [],
      })))

    const { container } = render(<ProvenanceChain entityId="ent-123" />)

    await waitFor(() => {
      expect(container.querySelector('.provenance-chain-header')).not.toBeNull()
    })

    expect(container.textContent).toContain('5')
    expect(container.textContent).toContain('80%')
    expect(container.textContent).toContain('gdacs')
    expect(container.textContent).toContain('gdelt')
  })

  it('renders conflict badge when conflicts exist', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-conflict',
        datasets: ['gdacs', 'gdelt'],
        total_statements: 3,
        by_prop: { name: { count: 2, datasets: ['gdacs', 'gdelt'] } },
        by_dataset: { gdacs: 2, gdelt: 1 },
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        total: 3,
        scored: 3,
        avg_score: 0.6,
        min_score: 0.4,
        max_score: 0.8,
        by_dataset: { gdacs: { count: 2, avg_score: 0.7 }, gdelt: { count: 1, avg_score: 0.4 } },
        conflicts: 1,
        entity_id: 'ent-conflict',
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-conflict',
        conflicts: [{
          prop: 'name',
          conflict_type: 'value_dispute',
          values: [
            { value: 'Alpha', dataset: 'gdacs', seen_at: '2026-06-25T08:00:00Z' },
            { value: 'Beta', dataset: 'gdelt', seen_at: '2026-06-25T09:00:00Z' },
          ],
        }],
      })))

    const { container } = render(<ProvenanceChain entityId="ent-conflict" />)

    await waitFor(() => {
      const badge = container.querySelector('.provenance-chain-badge--conflict')
      expect(badge).not.toBeNull()
      expect(badge?.textContent).toContain('1 conflict')
    })
  })

  it('renders corroboration badge when multiple sources agree', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-corrob',
        datasets: ['gdacs', 'gdelt', 'ais'],
        total_statements: 4,
        by_prop: {
          name: { count: 2, datasets: ['gdacs', 'gdelt'] },
          country: { count: 1, datasets: ['gdacs'] },
          lat: { count: 1, datasets: ['ais'] },
        },
        by_dataset: { gdacs: 2, gdelt: 1, ais: 1 },
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        total: 4,
        scored: 4,
        avg_score: 0.75,
        min_score: 0.5,
        max_score: 0.9,
        by_dataset: { gdacs: { count: 2, avg_score: 0.8 }, gdelt: { count: 1, avg_score: 0.7 }, ais: { count: 1, avg_score: 0.7 } },
        conflicts: 0,
        entity_id: 'ent-corrob',
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-corrob',
        conflicts: [],
      })))

    const { container } = render(<ProvenanceChain entityId="ent-corrob" />)

    await waitFor(() => {
      const badge = container.querySelector('.provenance-chain-badge--corrob')
      expect(badge).not.toBeNull()
      expect(badge?.textContent).toContain('1 corroborated')
    })
  })

  it('renders empty state when no statements', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-empty',
        datasets: [],
        total_statements: 0,
        by_prop: {},
        by_dataset: {},
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        total: 0,
        scored: 0,
        avg_score: 0.0,
        min_score: 0.0,
        max_score: 0.0,
        by_dataset: {},
        conflicts: 0,
        entity_id: 'ent-empty',
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-empty',
        conflicts: [],
      })))

    const { container } = render(<ProvenanceChain entityId="ent-empty" />)

    await waitFor(() => {
      expect(container.querySelector('.provenance-chain-empty')).not.toBeNull()
    })
  })

  it('renders error state on fetch failure', async () => {
    mockFetch.mockRejectedValue(new Error('Network error'))

    const { container } = render(<ProvenanceChain entityId="ent-err" />)

    await waitFor(() => {
      expect(container.querySelector('.provenance-chain-error')).not.toBeNull()
    })
  })

  it('applies compact class when compact=true', () => {
    mockFetch.mockReturnValue(new Promise(() => {}))
    const { container } = render(<ProvenanceChain entityId="ent-1" compact />)
    expect(container.querySelector('.provenance-chain--compact')).not.toBeNull()
  })

  it('does not apply compact class by default', () => {
    mockFetch.mockReturnValue(new Promise(() => {}))
    const { container } = render(<ProvenanceChain entityId="ent-1" />)
    expect(container.querySelector('.provenance-chain--compact')).toBeNull()
  })

  it('sets ARIA region label with entity id', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-aria',
        datasets: ['gdacs'],
        total_statements: 1,
        by_prop: { name: { count: 1, datasets: ['gdacs'] } },
        by_dataset: { gdacs: 1 },
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        total: 1,
        scored: 1,
        avg_score: 0.8,
        min_score: 0.8,
        max_score: 0.8,
        by_dataset: { gdacs: { count: 1, avg_score: 0.8 } },
        conflicts: 0,
        entity_id: 'ent-aria',
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-aria',
        conflicts: [],
      })))

    const { container } = render(<ProvenanceChain entityId="ent-aria" />)

    await waitFor(() => {
      const region = container.querySelector('[role="region"]')
      expect(region).not.toBeNull()
      expect(region?.getAttribute('aria-label')).toContain('ent-aria')
    })
  })

  it('renders conflict details in non-compact mode', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-detail',
        datasets: ['gdacs', 'gdelt'],
        total_statements: 2,
        by_prop: { name: { count: 2, datasets: ['gdacs', 'gdelt'] } },
        by_dataset: { gdacs: 1, gdelt: 1 },
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        total: 2,
        scored: 2,
        avg_score: 0.5,
        min_score: 0.4,
        max_score: 0.6,
        by_dataset: { gdacs: { count: 1, avg_score: 0.6 }, gdelt: { count: 1, avg_score: 0.4 } },
        conflicts: 1,
        entity_id: 'ent-detail',
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-detail',
        conflicts: [{
          prop: 'name',
          conflict_type: 'value_dispute',
          values: [
            { value: 'Alpha', dataset: 'gdacs', seen_at: '2026-06-25T08:00:00Z' },
            { value: 'Beta', dataset: 'gdelt', seen_at: '2026-06-25T09:00:00Z' },
          ],
        }],
      })))

    const { container } = render(<ProvenanceChain entityId="ent-detail" />)

    await waitFor(() => {
      const conflictsSection = container.querySelector('.provenance-chain-conflicts')
      expect(conflictsSection).not.toBeNull()
      expect(conflictsSection?.textContent).toContain('name')
      expect(conflictsSection?.textContent).toContain('Alpha')
      expect(conflictsSection?.textContent).toContain('Beta')
    })
  })

  it('hides conflict details in compact mode', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-compact',
        datasets: ['gdacs', 'gdelt'],
        total_statements: 2,
        by_prop: { name: { count: 2, datasets: ['gdacs', 'gdelt'] } },
        by_dataset: { gdacs: 1, gdelt: 1 },
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        total: 2,
        scored: 2,
        avg_score: 0.5,
        min_score: 0.4,
        max_score: 0.6,
        by_dataset: { gdacs: { count: 1, avg_score: 0.6 }, gdelt: { count: 1, avg_score: 0.4 } },
        conflicts: 1,
        entity_id: 'ent-compact',
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-compact',
        conflicts: [{
          prop: 'name',
          conflict_type: 'value_dispute',
          values: [
            { value: 'Alpha', dataset: 'gdacs', seen_at: '2026-06-25T08:00:00Z' },
          ],
        }],
      })))

    const { container } = render(<ProvenanceChain entityId="ent-compact" compact />)

    await waitFor(() => {
      expect(container.querySelector('.provenance-chain-conflicts')).toBeNull()
    })
  })

  it('renders corroboration details in non-compact mode', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-corr-detail',
        datasets: ['gdacs', 'gdelt'],
        total_statements: 2,
        by_prop: { name: { count: 2, datasets: ['gdacs', 'gdelt'] } },
        by_dataset: { gdacs: 1, gdelt: 1 },
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        total: 2,
        scored: 2,
        avg_score: 0.7,
        min_score: 0.6,
        max_score: 0.8,
        by_dataset: { gdacs: { count: 1, avg_score: 0.8 }, gdelt: { count: 1, avg_score: 0.6 } },
        conflicts: 0,
        entity_id: 'ent-corr-detail',
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-corr-detail',
        conflicts: [],
      })))

    const { container } = render(<ProvenanceChain entityId="ent-corr-detail" />)

    await waitFor(() => {
      const corrobSection = container.querySelector('.provenance-chain-corrob')
      expect(corrobSection).not.toBeNull()
      expect(corrobSection?.textContent).toContain('name')
      expect(corrobSection?.textContent).toContain('gdacs')
      expect(corrobSection?.textContent).toContain('gdelt')
      expect(corrobSection?.textContent).toContain('2 sources')
    })
  })

  it('hides corroboration details in compact mode', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-corr-compact',
        datasets: ['gdacs', 'gdelt'],
        total_statements: 2,
        by_prop: { name: { count: 2, datasets: ['gdacs', 'gdelt'] } },
        by_dataset: { gdacs: 1, gdelt: 1 },
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        total: 2,
        scored: 2,
        avg_score: 0.7,
        min_score: 0.6,
        max_score: 0.8,
        by_dataset: { gdacs: { count: 1, avg_score: 0.8 }, gdelt: { count: 1, avg_score: 0.6 } },
        conflicts: 0,
        entity_id: 'ent-corr-compact',
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-corr-compact',
        conflicts: [],
      })))

    const { container } = render(<ProvenanceChain entityId="ent-corr-compact" compact />)

    await waitFor(() => {
      expect(container.querySelector('.provenance-chain-corrob')).toBeNull()
    })
  })

  it('applies green dot for high reliability score', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-green',
        datasets: ['gdacs'],
        total_statements: 1,
        by_prop: { name: { count: 1, datasets: ['gdacs'] } },
        by_dataset: { gdacs: 1 },
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        total: 1,
        scored: 1,
        avg_score: 0.85,
        min_score: 0.85,
        max_score: 0.85,
        by_dataset: { gdacs: { count: 1, avg_score: 0.85 } },
        conflicts: 0,
        entity_id: 'ent-green',
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-green',
        conflicts: [],
      })))

    const { container } = render(<ProvenanceChain entityId="ent-green" />)

    await waitFor(() => {
      const dot = container.querySelector('.provenance-chain-dot') as HTMLElement
      expect(dot.style.background).toBe('var(--green)')
    })
  })

  it('applies amber dot for medium reliability score', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-amber',
        datasets: ['gdacs'],
        total_statements: 1,
        by_prop: { name: { count: 1, datasets: ['gdacs'] } },
        by_dataset: { gdacs: 1 },
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        total: 1,
        scored: 1,
        avg_score: 0.5,
        min_score: 0.5,
        max_score: 0.5,
        by_dataset: { gdacs: { count: 1, avg_score: 0.5 } },
        conflicts: 0,
        entity_id: 'ent-amber',
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-amber',
        conflicts: [],
      })))

    const { container } = render(<ProvenanceChain entityId="ent-amber" />)

    await waitFor(() => {
      const dot = container.querySelector('.provenance-chain-dot') as HTMLElement
      expect(dot.style.background).toBe('var(--amber)')
    })
  })

  it('applies red dot for low reliability score', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-red',
        datasets: ['gdacs'],
        total_statements: 1,
        by_prop: { name: { count: 1, datasets: ['gdacs'] } },
        by_dataset: { gdacs: 1 },
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        total: 1,
        scored: 1,
        avg_score: 0.2,
        min_score: 0.2,
        max_score: 0.2,
        by_dataset: { gdacs: { count: 1, avg_score: 0.2 } },
        conflicts: 0,
        entity_id: 'ent-red',
      })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({
        entity_id: 'ent-red',
        conflicts: [],
      })))

    const { container } = render(<ProvenanceChain entityId="ent-red" />)

    await waitFor(() => {
      const dot = container.querySelector('.provenance-chain-dot') as HTMLElement
      expect(dot.style.background).toBe('var(--red)')
    })
  })

  it('calls fetchApi with correct entity-encoded URLs', () => {
    mockFetch.mockReturnValue(new Promise(() => {}))
    render(<ProvenanceChain entityId="ent with spaces" />)
    expect(mockFetch).toHaveBeenCalledWith('/api/intel/entity/ent%20with%20spaces/provenance')
    expect(mockFetch).toHaveBeenCalledWith('/api/intel/statements/provenance/summary?entity_id=ent%20with%20spaces')
    expect(mockFetch).toHaveBeenCalledWith('/api/intel/statements/conflicts?entity_id=ent%20with%20spaces')
  })
})

/* ── ProvenanceGlobalStats ────────────────────────────────────────────────── */

describe('ProvenanceGlobalStats', () => {
  it('renders null when no data', async () => {
    mockFetch.mockReturnValue(Promise.resolve({ ok: true, json: () => Promise.resolve(null) }))
    const { container } = render(<ProvenanceGlobalStats />)
    await waitFor(() => {
      expect(container.firstChild).toBeNull()
    })
  })

  it('renders null when total_statements is 0', async () => {
    mockFetch.mockReturnValue(Promise.resolve(mockResponse({
      total_statements: 0,
      by_dataset: {},
      by_prop: {},
    })))
    const { container } = render(<ProvenanceGlobalStats />)
    await waitFor(() => {
      expect(container.firstChild).toBeNull()
    })
  })

  it('renders global stats with dataset breakdown', async () => {
    mockFetch.mockReturnValue(Promise.resolve(mockResponse({
      total_statements: 1000,
      by_dataset: { gdacs: 500, gdelt: 300, ais: 200 },
      by_prop: { name: 400, country: 300 },
    })))

    const { container } = render(<ProvenanceGlobalStats />)

    await waitFor(() => {
      expect(container.querySelector('.provenance-chain-header')).not.toBeNull()
    })

    expect(container.textContent).toContain('1000')
    expect(container.textContent).toContain('3 datasets')
    expect(container.textContent).toContain('gdacs')
    expect(container.textContent).toContain('500')
    expect(container.textContent).toContain('gdelt')
    expect(container.textContent).toContain('ais')
  })

  it('sorts datasets by count descending', async () => {
    mockFetch.mockReturnValue(Promise.resolve(mockResponse({
      total_statements: 100,
      by_dataset: { small: 10, big: 80, medium: 10 },
      by_prop: {},
    })))

    const { container } = render(<ProvenanceGlobalStats />)

    await waitFor(() => {
      const rows = container.querySelectorAll('.provenance-chain-row')
      expect(rows.length).toBe(3)
      expect(rows[0].textContent).toContain('big')
      expect(rows[0].textContent).toContain('80')
    })
  })

  it('limits to 12 datasets', async () => {
    const byDataset: Record<string, number> = {}
    for (let i = 0; i < 15; i++) byDataset[`ds${i}`] = i + 1
    mockFetch.mockReturnValue(Promise.resolve(mockResponse({
      total_statements: 120,
      by_dataset: byDataset,
      by_prop: {},
    })))

    const { container } = render(<ProvenanceGlobalStats />)

    await waitFor(() => {
      const rows = container.querySelectorAll('.provenance-chain-row')
      expect(rows.length).toBe(12)
    })
  })

  it('sets ARIA region label', async () => {
    mockFetch.mockReturnValue(Promise.resolve(mockResponse({
      total_statements: 10,
      by_dataset: { gdacs: 10 },
      by_prop: {},
    })))

    const { container } = render(<ProvenanceGlobalStats />)

    await waitFor(() => {
      const region = container.querySelector('[role="region"]')
      expect(region?.getAttribute('aria-label')).toContain('provenance')
    })
  })

  it('handles fetch error gracefully', async () => {
    mockFetch.mockRejectedValue(new Error('Network'))
    const { container } = render(<ProvenanceGlobalStats />)
    // Should render null (catch → setStats never called → stats stays null)
    await waitFor(() => {
      expect(container.firstChild).toBeNull()
    })
  })
})
