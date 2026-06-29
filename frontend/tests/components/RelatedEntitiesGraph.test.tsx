import { describe, it, expect, vi } from 'vitest'
import { render, fireEvent } from '@testing-library/react'
import RelatedEntitiesGraph from '../../src/components/RelatedEntitiesGraph'

const baseNodes = [
  { id: 'root-1', schema: 'Person', caption: 'Alice' },
  { id: 'ent-2', schema: 'Organization', caption: 'Acme Corp' },
  { id: 'ent-3', schema: 'Address', caption: '123 Main St' },
]

const baseEdges = [
  { source_id: 'root-1', target_id: 'ent-2', kind: 'directorOf', confidence: 0.9 },
  { source_id: 'root-1', target_id: 'ent-3', kind: 'residence', confidence: 0.8 },
]

describe('RelatedEntitiesGraph', () => {
  it('renders empty message when only 1 node (no connections)', () => {
    const { container } = render(
      <RelatedEntitiesGraph
        rootEntityId="root-1"
        nodes={[{ id: 'root-1', schema: 'Person', caption: 'Alice' }]}
        edges={[]}
        onSelectEntity={vi.fn()}
      />,
    )
    expect(container.querySelector('.related-graph-empty')).not.toBeNull()
    expect(container.textContent).toContain('No connected entities')
  })

  it('renders empty message when 0 nodes', () => {
    const { container } = render(
      <RelatedEntitiesGraph
        rootEntityId="root-1"
        nodes={[]}
        edges={[]}
        onSelectEntity={vi.fn()}
      />,
    )
    expect(container.querySelector('.related-graph-empty')).not.toBeNull()
  })

  it('renders SVG with nodes and edges when graph has connections', () => {
    const { container } = render(
      <RelatedEntitiesGraph
        rootEntityId="root-1"
        nodes={baseNodes}
        edges={baseEdges}
        onSelectEntity={vi.fn()}
      />,
    )
    const svg = container.querySelector('.related-graph-svg')
    expect(svg).not.toBeNull()
    // 3 circles (one per node)
    const circles = container.querySelectorAll('.related-graph-node')
    expect(circles.length).toBe(3)
    // 2 edge lines
    const edgeLines = container.querySelectorAll('.related-graph-edge')
    expect(edgeLines.length).toBe(2)
  })

  it('marks root node with root class', () => {
    const { container } = render(
      <RelatedEntitiesGraph
        rootEntityId="root-1"
        nodes={baseNodes}
        edges={baseEdges}
        onSelectEntity={vi.fn()}
      />,
    )
    const rootCircle = container.querySelector('.related-graph-node--root')
    expect(rootCircle).not.toBeNull()
  })

  it('renders edge labels for small graphs (≤6 edges)', () => {
    const { container } = render(
      <RelatedEntitiesGraph
        rootEntityId="root-1"
        nodes={baseNodes}
        edges={baseEdges}
        onSelectEntity={vi.fn()}
      />,
    )
    const labels = container.querySelectorAll('.related-graph-edge-label')
    expect(labels.length).toBe(2)
    expect(labels[0].textContent).toContain('directorOf')
  })

  it('hides edge labels for large graphs (>6 edges)', () => {
    const manyNodes = Array.from({ length: 10 }, (_, i) => ({
      id: `ent-${i}`,
      schema: 'Person',
      caption: `Entity ${i}`,
    }))
    const manyEdges = Array.from({ length: 8 }, (_, i) => ({
      source_id: 'ent-0',
      target_id: `ent-${i + 1}`,
      kind: `rel${i}`,
    }))
    const { container } = render(
      <RelatedEntitiesGraph
        rootEntityId="ent-0"
        nodes={manyNodes}
        edges={manyEdges}
        onSelectEntity={vi.fn()}
      />,
    )
    const labels = container.querySelectorAll('.related-graph-edge-label')
    expect(labels.length).toBe(0)
  })

  it('calls onSelectEntity when a non-root node is clicked', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <RelatedEntitiesGraph
        rootEntityId="root-1"
        nodes={baseNodes}
        edges={baseEdges}
        onSelectEntity={onSelect}
      />,
    )
    const nodeGroups = container.querySelectorAll('.related-graph-node-g')
    // Find a non-root node group (should have cursor: pointer)
    const nonRoot = Array.from(nodeGroups).find(
      (g) => (g as HTMLElement).style.cursor === 'pointer',
    )
    expect(nonRoot).toBeDefined()
    nonRoot!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(onSelect).toHaveBeenCalledTimes(1)
  })

  it('does not call onSelectEntity when root node is clicked', () => {
    const onSelect = vi.fn()
    const { container } = render(
      <RelatedEntitiesGraph
        rootEntityId="root-1"
        nodes={baseNodes}
        edges={baseEdges}
        onSelectEntity={onSelect}
      />,
    )
    const rootGroup = container.querySelector('.related-graph-node--root')
    expect(rootGroup).not.toBeNull()
    const parentG = rootGroup!.closest('g')
    parentG!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('renders node labels with truncated captions', () => {
    const longCaptionNodes = [
      { id: 'root-1', schema: 'Person', caption: 'A' },
      { id: 'ent-2', schema: 'Person', caption: 'This is a very long caption that should be truncated' },
    ]
    const { container } = render(
      <RelatedEntitiesGraph
        rootEntityId="root-1"
        nodes={longCaptionNodes}
        edges={[{ source_id: 'root-1', target_id: 'ent-2', kind: 'knows' }]}
        onSelectEntity={vi.fn()}
      />,
    )
    const labels = container.querySelectorAll('.related-graph-node-label')
    const truncatedLabel = Array.from(labels).find((l) => l.textContent?.includes('…'))
    expect(truncatedLabel).not.toBeNull()
  })

  it('handles nodes without caption (falls back to id)', () => {
    const { container } = render(
      <RelatedEntitiesGraph
        rootEntityId="root/1"
        nodes={[
          { id: 'root/1', schema: null, caption: null },
          { id: 'ent/2', schema: null, caption: null },
        ]}
        edges={[{ source_id: 'root/1', target_id: 'ent/2', kind: 'link' }]}
        onSelectEntity={vi.fn()}
      />,
    )
    const labels = container.querySelectorAll('.related-graph-node-label')
    // Should use the last segment of the id as fallback
    expect(Array.from(labels).some((l) => l.textContent?.includes('1')))
    expect(Array.from(labels).some((l) => l.textContent?.includes('2')))
  })

  it('highlights edges connected to hovered node', () => {
    const { container } = render(
      <RelatedEntitiesGraph
        rootEntityId="root-1"
        nodes={baseNodes}
        edges={baseEdges}
        onSelectEntity={vi.fn()}
      />,
    )
    const nodeGroups = container.querySelectorAll('.related-graph-node-g')
    const nonRoot = Array.from(nodeGroups).find(
      (g) => (g as HTMLElement).style.cursor === 'pointer',
    )
    // Hover over a non-root node
    fireEvent.mouseEnter(nonRoot!)
    const highlighted = container.querySelectorAll('.related-graph-edge--hl')
    expect(highlighted.length).toBeGreaterThan(0)
    // Mouse leave should remove highlight
    fireEvent.mouseLeave(nonRoot!)
    const afterLeave = container.querySelectorAll('.related-graph-edge--hl')
    expect(afterLeave.length).toBe(0)
  })
})
