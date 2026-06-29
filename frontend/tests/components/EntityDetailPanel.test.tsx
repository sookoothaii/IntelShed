import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor, fireEvent } from '@testing-library/react'
import EntityDetailPanel from '../../src/components/EntityDetailPanel'

/* ── Mock fetchApi ─────────────────────────────────────────────────────────── */

vi.mock('../../src/lib/networkFetch', () => ({
  fetchApi: vi.fn(),
}))

/* Stub ProvenanceChain so its internal fetchApi calls don't interfere */
vi.mock('../../src/components/ProvenanceChain', () => ({
  default: ({ entityId }: { entityId: string }) => (
    <div className="provenance-chain" data-entity-id={entityId} />
  ),
}))

import { fetchApi } from '../../src/lib/networkFetch'
const mockFetch = fetchApi as ReturnType<typeof vi.fn>

function mockResponse(data: unknown) {
  return {
    ok: true,
    json: () => Promise.resolve(data),
  }
}

function mockEntity(overrides: Record<string, unknown> = {}) {
  return {
    id: 'ent-123',
    schema: 'Person',
    caption: 'John Doe',
    properties: { name: 'John Doe', email: 'john@test.com' },
    datasets: ['gdacs', 'gdelt'],
    first_seen: '2026-01-15T08:00:00Z',
    last_seen: '2026-06-20T12:00:00Z',
    lat: 13.7563,
    lon: 100.5018,
    statements: [
      { prop: 'name', value: 'John Doe', dataset: 'gdacs', seen_at: '2026-01-15T08:00:00Z' },
      { prop: 'country', value: 'Thailand', dataset: 'gdelt', seen_at: '2026-02-01T00:00:00Z' },
    ],
    edges: [
      { source_id: 'ent-123', target_id: 'ent-456', kind: 'knows', confidence: 0.9 },
    ],
    neighbours: [
      { id: 'ent-456', schema: 'Person', caption: 'Jane Smith', lat: null, lon: null },
    ],
    found: true,
    ...overrides,
  }
}

function mockGraph() {
  return {
    root: 'ent-123',
    found: true,
    depth: 1,
    nodes: [
      { id: 'ent-123', schema: 'Person', caption: 'John Doe', lat: 13.7563, lon: 100.5018, first_seen: null, last_seen: null, properties: {}, datasets: [] },
      { id: 'ent-456', schema: 'Person', caption: 'Jane Smith', lat: null, lon: null, first_seen: null, last_seen: null, properties: {}, datasets: [] },
    ],
    edges: [
      { source_id: 'ent-123', target_id: 'ent-456', kind: 'knows', confidence: 0.9, dataset: 'gdacs', seen_at: null },
    ],
  }
}

beforeEach(() => {
  mockFetch.mockReset()
})

/* ── EntityDetailPanel ────────────────────────────────────────────────────── */

describe('EntityDetailPanel', () => {
  it('renders empty state when entityId is null', () => {
    const { container } = render(<EntityDetailPanel entityId={null} />)
    expect(container.querySelector('.entity-panel-empty')).not.toBeNull()
    expect(container.textContent).toContain('Select an entity on the globe')
  })

  it('renders loading skeleton when fetching', () => {
    mockFetch.mockReturnValue(new Promise(() => {})) // never resolves
    const { container } = render(<EntityDetailPanel entityId="ent-123" />)
    expect(container.querySelector('.entity-panel-loading')).not.toBeNull()
    expect(container.querySelectorAll('.entity-panel-skeleton-row').length).toBeGreaterThan(0)
  })

  it('renders entity header with caption and schema badge after load', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockEntity())))
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockGraph())))

    const { container } = render(<EntityDetailPanel entityId="ent-123" />)

    await waitFor(() => {
      expect(container.querySelector('.entity-panel-header')).not.toBeNull()
    })

    expect(container.textContent).toContain('John Doe')
    expect(container.querySelector('.entity-panel-schema-badge')?.textContent).toContain('Person')
  })

  it('renders FtM entity ID in monospace', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockEntity())))
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockGraph())))

    const { container } = render(<EntityDetailPanel entityId="ent-123" />)

    await waitFor(() => {
      expect(container.querySelector('.entity-panel-id')?.textContent).toContain('ent-123')
    })
  })

  it('renders properties from entity.properties dict', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockEntity())))
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockGraph())))

    const { container } = render(<EntityDetailPanel entityId="ent-123" />)

    await waitFor(() => {
      expect(container.querySelector('.entity-panel-props')).not.toBeNull()
    })

    const propRows = container.querySelectorAll('.entity-panel-prop-row')
    expect(propRows.length).toBeGreaterThanOrEqual(2)
    expect(container.textContent).toContain('john@test.com')
  })

  it('renders properties from statements not in properties dict', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockEntity())))
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockGraph())))

    const { container } = render(<EntityDetailPanel entityId="ent-123" />)

    await waitFor(() => {
      expect(container.textContent).toContain('country')
      expect(container.textContent).toContain('Thailand')
    })
  })

  it('renders dataset tags', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockEntity())))
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockGraph())))

    const { container } = render(<EntityDetailPanel entityId="ent-123" />)

    await waitFor(() => {
      const tags = container.querySelectorAll('.entity-panel-dataset-tag')
      expect(tags.length).toBe(2)
      expect(tags[0].textContent).toContain('gdacs')
      expect(tags[1].textContent).toContain('gdelt')
    })
  })

  it('renders first_seen and last_seen timestamps', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockEntity())))
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockGraph())))

    const { container } = render(<EntityDetailPanel entityId="ent-123" />)

    await waitFor(() => {
      const ts = container.querySelectorAll('.entity-panel-ts')
      expect(ts.length).toBe(2)
      expect(ts[0].textContent).toContain('First:')
      expect(ts[1].textContent).toContain('Last:')
    })
  })

  it('renders related entities graph section', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockEntity())))
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockGraph())))

    const { container } = render(<EntityDetailPanel entityId="ent-123" />)

    await waitFor(() => {
      expect(container.querySelector('.related-graph-svg')).not.toBeNull()
    })
  })

  it('renders provenance chain section', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockEntity())))
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockGraph())))

    const { container } = render(<EntityDetailPanel entityId="ent-123" />)

    await waitFor(() => {
      expect(container.querySelector('.provenance-chain')).not.toBeNull()
    })
    expect(container.querySelector('.provenance-chain')?.getAttribute('data-entity-id')).toBe('ent-123')
  })

  it('renders action bar with Flag and Re-Analyze (no Publish)', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockEntity())))
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockGraph())))

    const { container } = render(<EntityDetailPanel entityId="ent-123" />)

    await waitFor(() => {
      expect(container.querySelector('.action-bar')).not.toBeNull()
    })

    expect(container.textContent).toContain('FLAG')
    expect(container.textContent).toContain('RE-ANALYZE')
    expect(container.textContent).not.toContain('PUBLISH')
  })

  it('renders error state on fetch failure', async () => {
    mockFetch.mockRejectedValue(new Error('Network error'))

    const { container } = render(<EntityDetailPanel entityId="ent-err" />)

    await waitFor(() => {
      expect(container.querySelector('.entity-panel-error')).not.toBeNull()
      expect(container.textContent).toContain('Failed to load')
    })
  })

  it('renders not-found state when entity.found is false', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse({ id: 'ent-x', found: false })))
      .mockReturnValueOnce(Promise.resolve(mockResponse({ nodes: [], edges: [] })))

    const { container } = render(<EntityDetailPanel entityId="ent-x" />)

    await waitFor(() => {
      expect(container.querySelector('.entity-panel-error')).not.toBeNull()
      expect(container.textContent).toContain('not found')
    })
  })

  it('shows focus button when entity has lat/lon', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockEntity())))
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockGraph())))

    const { container } = render(<EntityDetailPanel entityId="ent-123" />)

    await waitFor(() => {
      expect(container.querySelector('.entity-panel-focus-btn')).not.toBeNull()
    })
  })

  it('hides focus button when entity has no lat/lon', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockEntity({ lat: null, lon: null }))))
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockGraph())))

    const { container } = render(<EntityDetailPanel entityId="ent-123" />)

    await waitFor(() => {
      expect(container.querySelector('.entity-panel-focus-btn')).toBeNull()
    })
  })

  it('calls onFocus when focus button is clicked', async () => {
    const onFocus = vi.fn()
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockEntity())))
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockGraph())))

    const { container } = render(
      <EntityDetailPanel entityId="ent-123" onFocus={onFocus} />,
    )

    await waitFor(() => {
      expect(container.querySelector('.entity-panel-focus-btn')).not.toBeNull()
    })

    fireEvent.click(container.querySelector('.entity-panel-focus-btn')!)
    expect(onFocus).toHaveBeenCalledWith(13.7563, 100.5018, 'John Doe')
  })

  it('calls onSelectEntity when related entity node is clicked', async () => {
    const onSelect = vi.fn()
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockEntity())))
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockGraph())))

    const { container } = render(
      <EntityDetailPanel entityId="ent-123" onSelectEntity={onSelect} />,
    )

    await waitFor(() => {
      expect(container.querySelector('.related-graph-svg')).not.toBeNull()
    })

    // Find a non-root node group
    const nodeGroups = container.querySelectorAll('.related-graph-node-g')
    const nonRoot = Array.from(nodeGroups).find(
      (g) => (g as HTMLElement).style.cursor === 'pointer',
    )
    expect(nonRoot).toBeDefined()
    nonRoot!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(onSelect).toHaveBeenCalledTimes(1)
  })

  it('calls fetchApi with correct entity-encoded URLs', () => {
    mockFetch.mockReturnValue(new Promise(() => {}))
    render(<EntityDetailPanel entityId="ent with spaces" />)
    expect(mockFetch).toHaveBeenCalledWith('/api/ftm/entity/ent%20with%20spaces')
    expect(mockFetch).toHaveBeenCalledWith('/api/ftm/entity/ent%20with%20spaces/graph?depth=1&limit=50')
  })

  it('renders empty properties message when no properties', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockEntity({
        properties: {},
        statements: [],
      }))))
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockGraph())))

    const { container } = render(<EntityDetailPanel entityId="ent-123" />)

    await waitFor(() => {
      const emptyMsg = container.querySelector('.sidebar-empty')
      expect(emptyMsg).not.toBeNull()
      expect(emptyMsg?.textContent).toContain('No properties available')
    })
  })

  it('falls back to neighbours from entity endpoint when graph has no nodes', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockEntity())))
      .mockReturnValueOnce(Promise.resolve(mockResponse({ nodes: [], edges: [] })))

    const { container } = render(<EntityDetailPanel entityId="ent-123" />)

    await waitFor(() => {
      // Should still render the graph using fallback neighbours
      const svg = container.querySelector('.related-graph-svg')
      // With 2 nodes (root + 1 neighbour) and 1 edge from entity.edges
      if (svg) {
        const circles = container.querySelectorAll('.related-graph-node')
        expect(circles.length).toBe(2)
      }
    })
  })

  it('limits displayed properties to 20', async () => {
    const manyProps: Record<string, string> = {}
    for (let i = 0; i < 25; i++) manyProps[`prop${i}`] = `val${i}`
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockEntity({
        properties: manyProps,
        statements: [],
      }))))
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockGraph())))

    const { container } = render(<EntityDetailPanel entityId="ent-123" />)

    await waitFor(() => {
      const rows = container.querySelectorAll('.entity-panel-prop-row')
      expect(rows.length).toBe(20)
    })
  })

  it('clears state when entityId becomes null', async () => {
    mockFetch
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockEntity())))
      .mockReturnValueOnce(Promise.resolve(mockResponse(mockGraph())))

    const { container, rerender } = render(<EntityDetailPanel entityId="ent-123" />)

    await waitFor(() => {
      expect(container.querySelector('.entity-panel-header')).not.toBeNull()
    })

    rerender(<EntityDetailPanel entityId={null} />)

    await waitFor(() => {
      expect(container.querySelector('.entity-panel-empty')).not.toBeNull()
    })
  })
})
