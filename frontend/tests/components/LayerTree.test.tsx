import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, fireEvent, waitFor } from '@testing-library/react'
import LayerTree from '../../src/components/LayerTree'

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

function mockHealthResponse() {
  return mockResponse({
    status: 'ok',
    feeds: {
      aircraft: { status: 'fresh', fresh: true, count: 42 },
      maritime: { status: 'fresh', fresh: true, count: 74 },
      quakes: { status: 'stale', fresh: false, count: 3 },
      gdacs: { status: 'error', fresh: false, count: 0 },
    },
  })
}

describe('LayerTree', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockFetch.mockReturnValue(Promise.resolve(mockHealthResponse()))
  })

  it('renders tree with role="tree"', () => {
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={vi.fn()} />,
    )
    const tree = container.querySelector('.layer-tree')
    expect(tree).not.toBeNull()
    expect(tree?.getAttribute('role')).toBe('tree')
  })

  it('renders all 5 group headers', () => {
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={vi.fn()} />,
    )
    const headers = container.querySelectorAll('.layer-tree-group-header')
    expect(headers.length).toBe(5)
  })

  it('renders group labels with correct text', () => {
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={vi.fn()} />,
    )
    const labels = Array.from(container.querySelectorAll('.layer-tree-group-label')).map(
      (el) => el.textContent,
    )
    expect(labels).toContain('Live Tracking')
    expect(labels).toContain('Geo Hazards')
    expect(labels).toContain('Environment')
    expect(labels).toContain('Intelligence')
    expect(labels).toContain('Disasters & Events')
  })

  it('renders all layer items when groups are expanded', () => {
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={vi.fn()} />,
    )
    const items = container.querySelectorAll('.layer-tree-item')
    // 6 (Live Tracking) + 6 (Geo Hazards) + 5 (Environment) + 6 (Intelligence) + 5 (Disasters) = 28
    expect(items.length).toBe(28)
  })

  it('renders checkbox for each layer item', () => {
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={vi.fn()} />,
    )
    const checkboxes = container.querySelectorAll('.layer-tree-checkbox')
    expect(checkboxes.length).toBe(28)
  })

  it('marks active layers with --on class and aria-selected', () => {
    const { container } = render(
      <LayerTree
        layers={{ aircraft: true, maritime: true }}
        onToggleLayer={vi.fn()}
      />,
    )
    const onItems = container.querySelectorAll('.layer-tree-item--on')
    expect(onItems.length).toBe(2)
    onItems.forEach((item) => {
      expect(item.getAttribute('aria-selected')).toBe('true')
    })
  })

  it('calls onToggleLayer when checkbox is clicked', () => {
    const onToggle = vi.fn()
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={onToggle} />,
    )
    const firstCheckbox = container.querySelector('.layer-tree-checkbox') as HTMLInputElement
    fireEvent.click(firstCheckbox)
    expect(onToggle).toHaveBeenCalledWith('aircraft')
  })

  it('calls onToggleLayer when item row is clicked', () => {
    const onToggle = vi.fn()
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={onToggle} />,
    )
    const firstItem = container.querySelector('.layer-tree-item') as HTMLDivElement
    fireEvent.click(firstItem)
    expect(onToggle).toHaveBeenCalledWith('aircraft')
  })

  it('collapses group when header is clicked', () => {
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={vi.fn()} />,
    )
    const firstHeader = container.querySelector('.layer-tree-group-header') as HTMLDivElement
    // Initially expanded
    expect(firstHeader.getAttribute('aria-expanded')).toBe('true')
    const itemsBefore = container.querySelectorAll('.layer-tree-item')
    expect(itemsBefore.length).toBe(28)

    fireEvent.click(firstHeader)
    // Now collapsed
    expect(firstHeader.getAttribute('aria-expanded')).toBe('false')
    const itemsAfter = container.querySelectorAll('.layer-tree-item')
    // Only items from other groups remain
    expect(itemsAfter.length).toBe(22) // 28 - 6 (Live Tracking)
  })

  it('collapses group on Enter key', () => {
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={vi.fn()} />,
    )
    const firstHeader = container.querySelector('.layer-tree-group-header') as HTMLDivElement
    fireEvent.keyDown(firstHeader, { key: 'Enter' })
    expect(firstHeader.getAttribute('aria-expanded')).toBe('false')
  })

  it('collapses group on Space key', () => {
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={vi.fn()} />,
    )
    const firstHeader = container.querySelector('.layer-tree-group-header') as HTMLDivElement
    fireEvent.keyDown(firstHeader, { key: ' ' })
    expect(firstHeader.getAttribute('aria-expanded')).toBe('false')
  })

  it('shows group count as active/total', () => {
    const { container } = render(
      <LayerTree
        layers={{ aircraft: true, satellites: true }}
        onToggleLayer={vi.fn()}
      />,
    )
    const counts = container.querySelectorAll('.layer-tree-group-count')
    // First group (Live Tracking) has 2 active out of 6
    expect(counts[0].textContent).toBe('2/6')
    // Other groups have 0 active
    expect(counts[1].textContent).toBe('0/6')
  })

  it('selects all layers in group when bulk button is clicked', () => {
    const onToggle = vi.fn()
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={onToggle} />,
    )
    const bulkBtn = container.querySelector('.layer-tree-bulk-btn') as HTMLButtonElement
    fireEvent.click(bulkBtn)
    // Should toggle all 6 layers in first group on
    expect(onToggle).toHaveBeenCalledTimes(6)
    const toggledKeys = onToggle.mock.calls.map((c) => c[0])
    expect(toggledKeys).toContain('aircraft')
    expect(toggledKeys).toContain('satellites')
    expect(toggledKeys).toContain('military')
    expect(toggledKeys).toContain('maritime')
    expect(toggledKeys).toContain('piAis')
    expect(toggledKeys).toContain('transit')
  })

  it('deselects all layers in group when bulk button is clicked and all are on', () => {
    const onToggle = vi.fn()
    const { container } = render(
      <LayerTree
        layers={{
          aircraft: true, satellites: true, military: true,
          maritime: true, piAis: true, transit: true,
        }}
        onToggleLayer={onToggle} />,
    )
    const bulkBtn = container.querySelector('.layer-tree-bulk-btn') as HTMLButtonElement
    fireEvent.click(bulkBtn)
    expect(onToggle).toHaveBeenCalledTimes(6)
  })

  it('bulk button stopPropagation prevents group collapse', () => {
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={vi.fn()} />,
    )
    const bulkBtn = container.querySelector('.layer-tree-bulk-btn') as HTMLButtonElement
    const header = container.querySelector('.layer-tree-group-header') as HTMLDivElement
    fireEvent.click(bulkBtn)
    // Header should still be expanded (stopPropagation prevented toggle)
    expect(header.getAttribute('aria-expanded')).toBe('true')
  })

  it('fetches feed health on mount', async () => {
    render(<LayerTree layers={{}} onToggleLayer={vi.fn()} />)
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith('/api/health')
    })
  })

  it('renders item count badges from stats prop', () => {
    const { container } = render(
      <LayerTree
        layers={{ aircraft: true }}
        onToggleLayer={vi.fn()}
        stats={{ aircraft: 42, satellites: 100, quakes: 3 }}
      />,
    )
    const badges = container.querySelectorAll('.layer-tree-badge')
    expect(badges.length).toBeGreaterThan(0)
    expect(badges[0].textContent).toBe('42')
  })

  it('does not render badge when count is 0', () => {
    const { container } = render(
      <LayerTree
        layers={{ aircraft: true }}
        onToggleLayer={vi.fn()}
        stats={{ aircraft: 42, quakes: 0 }}
      />,
    )
    const items = container.querySelectorAll('.layer-tree-item')
    // Find the quakes item
    const quakesItem = Array.from(items).find((it) =>
      it.querySelector('.layer-tree-label')?.textContent === 'Earthquakes',
    )
    expect(quakesItem?.querySelector('.layer-tree-badge')).toBeNull()
  })

  it('renders chevron that rotates when collapsed', () => {
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={vi.fn()} />,
    )
    const chevron = container.querySelector('.layer-tree-chevron') as HTMLSpanElement
    expect(chevron.classList.contains('layer-tree-chevron--collapsed')).toBe(false)

    const header = container.querySelector('.layer-tree-group-header') as HTMLDivElement
    fireEvent.click(header)
    expect(chevron.classList.contains('layer-tree-chevron--collapsed')).toBe(true)
  })

  it('toggles layer on Space key when item is focused', () => {
    const onToggle = vi.fn()
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={onToggle} />,
    )
    const firstItem = container.querySelector('.layer-tree-item') as HTMLDivElement
    fireEvent.keyDown(firstItem, { key: ' ' })
    expect(onToggle).toHaveBeenCalledWith('aircraft')
  })

  it('toggles layer on Enter key when item is focused', () => {
    const onToggle = vi.fn()
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={onToggle} />,
    )
    const firstItem = container.querySelector('.layer-tree-item') as HTMLDivElement
    fireEvent.keyDown(firstItem, { key: 'Enter' })
    expect(onToggle).toHaveBeenCalledWith('aircraft')
  })

  it('renders role="group" on group containers', () => {
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={vi.fn()} />,
    )
    const groups = container.querySelectorAll('[role="group"]')
    expect(groups.length).toBe(5)
  })

  it('renders role="treeitem" on layer items', () => {
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={vi.fn()} />,
    )
    const treeItems = container.querySelectorAll('.layer-tree-item[role="treeitem"]')
    expect(treeItems.length).toBe(28)
  })

  it('renders aria-label on tree', () => {
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={vi.fn()} />,
    )
    const tree = container.querySelector('.layer-tree')
    expect(tree?.getAttribute('aria-label')).toBe('Globe layers')
  })

  it('handles fetchApi error gracefully', async () => {
    mockFetch.mockReturnValue(Promise.resolve({ ok: false, json: () => Promise.resolve({}) }))
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={vi.fn()} />,
    )
    // Component should still render all items
    const items = container.querySelectorAll('.layer-tree-item')
    expect(items.length).toBe(28)
  })

  it('handles fetchApi throw gracefully', async () => {
    mockFetch.mockReturnValue(Promise.reject(new Error('network error')))
    const { container } = render(
      <LayerTree layers={{}} onToggleLayer={vi.fn()} />,
    )
    // Component should still render all items
    const items = container.querySelectorAll('.layer-tree-item')
    expect(items.length).toBe(28)
  })
})
