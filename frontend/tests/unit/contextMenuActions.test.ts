import { describe, it, expect, vi } from 'vitest'
import { buildContextMenuActions, type ContextMenuContext } from '../../src/lib/contextMenuActions'

const baseCallbacks = {
  onFocus: vi.fn(),
  onCopyCoords: vi.fn(),
  onAddPin: vi.fn(),
  onViewDetails: vi.fn(),
  onTrackFlight: vi.fn(),
  onFetchTrail: vi.fn(),
  onOpenLink: vi.fn(),
  onOpenWindy: vi.fn(),
  onAskAI: vi.fn(),
}

function makeCtx(partial: Partial<ContextMenuContext>): ContextMenuContext {
  return {
    kind: 'location',
    title: 'Test',
    lon: 100.5,
    lat: 13.7,
    rawProps: {},
    ...partial,
  }
}

describe('buildContextMenuActions', () => {
  it('returns empty array when no coords and no special kind', () => {
    const ctx = makeCtx({ kind: 'unknown', lon: undefined, lat: undefined })
    const actions = buildContextMenuActions(ctx, baseCallbacks)
    // Ask AI is always added
    expect(actions.length).toBe(1)
    expect(actions[0].id).toBe('ask-ai')
  })

  it('includes focus and copy-coords when coords present', () => {
    const actions = buildContextMenuActions(makeCtx({}), baseCallbacks)
    const ids = actions.map((a) => a.id)
    expect(ids).toContain('focus')
    expect(ids).toContain('copy-coords')
  })

  it('includes add-pin when coords present', () => {
    const actions = buildContextMenuActions(makeCtx({}), baseCallbacks)
    expect(actions.map((a) => a.id)).toContain('add-pin')
  })

  it('includes ask-ai always', () => {
    const actions = buildContextMenuActions(makeCtx({}), baseCallbacks)
    expect(actions.map((a) => a.id)).toContain('ask-ai')
  })

  it('aircraft includes track and trail when icao present', () => {
    const actions = buildContextMenuActions(
      makeCtx({ kind: 'aircraft', rawProps: { icao: 'abc123' } }),
      baseCallbacks,
    )
    const ids = actions.map((a) => a.id)
    expect(ids).toContain('track')
    expect(ids).toContain('trail')
  })

  it('aircraft without icao does not include trail', () => {
    const actions = buildContextMenuActions(
      makeCtx({ kind: 'aircraft', rawProps: {} }),
      baseCallbacks,
    )
    const ids = actions.map((a) => a.id)
    expect(ids).toContain('track')
    expect(ids).not.toContain('trail')
  })

  it('intel_ftm includes view details', () => {
    const actions = buildContextMenuActions(
      makeCtx({ kind: 'intel_ftm' }),
      baseCallbacks,
    )
    expect(actions.map((a) => a.id)).toContain('details')
  })

  it('fusion_cell includes analyze', () => {
    const actions = buildContextMenuActions(
      makeCtx({ kind: 'fusion_cell', rawProps: { intensity: 'high', score: 0.9, sources: 'gdelt' } }),
      baseCallbacks,
    )
    expect(actions.map((a) => a.id)).toContain('analyze')
  })

  it('maritime includes view vessel and web search when mmsi present', () => {
    const actions = buildContextMenuActions(
      makeCtx({ kind: 'maritime', rawProps: { mmsi: '123456789' } }),
      baseCallbacks,
    )
    const ids = actions.map((a) => a.id)
    expect(ids).toContain('maritime-details')
    expect(ids).toContain('web-search')
  })

  it('includes open-link when ctx.link is set', () => {
    const actions = buildContextMenuActions(
      makeCtx({ kind: 'gdacs', link: 'https://example.com' }),
      baseCallbacks,
    )
    expect(actions.map((a) => a.id)).toContain('open-link')
  })

  it('includes windy for weather-sensitive kinds', () => {
    const kinds = ['wildfire', 'quake', 'hazard', 'gdelt_geo', 'weather', 'volcano', 'geopolitics', 'event', 'gdacs']
    for (const kind of kinds) {
      const actions = buildContextMenuActions(makeCtx({ kind }), baseCallbacks)
      expect(actions.map((a) => a.id)).toContain('windy')
    }
  })

  it('does not include windy for non-weather kinds', () => {
    const actions = buildContextMenuActions(makeCtx({ kind: 'aircraft' }), baseCallbacks)
    expect(actions.map((a) => a.id)).not.toContain('windy')
  })

  it('handlers call correct callbacks', () => {
    const actions = buildContextMenuActions(makeCtx({}), baseCallbacks)
    const focusAction = actions.find((a) => a.id === 'focus')!
    focusAction.handler()
    expect(baseCallbacks.onFocus).toHaveBeenCalledWith(100.5, 13.7)

    const copyAction = actions.find((a) => a.id === 'copy-coords')!
    copyAction.handler()
    expect(baseCallbacks.onCopyCoords).toHaveBeenCalledWith(100.5, 13.7)

    const pinAction = actions.find((a) => a.id === 'add-pin')!
    pinAction.handler()
    expect(baseCallbacks.onAddPin).toHaveBeenCalledWith(100.5, 13.7, 'Test')
  })

  it('ask-ai handler builds lines from rawProps', () => {
    const actions = buildContextMenuActions(
      makeCtx({ kind: 'quake', rawProps: { mag: 5.5, place: 'Tokyo', kind: 'quake' } }),
      baseCallbacks,
    )
    const askAction = actions.find((a) => a.id === 'ask-ai')!
    askAction.handler()
    expect(baseCallbacks.onAskAI).toHaveBeenCalled()
    const [title, lines] = baseCallbacks.onAskAI.mock.calls[0]
    expect(title).toBe('Test')
    expect(lines.some((l: string) => l.includes('MAG:'))).toBe(true)
    expect(lines.some((l: string) => l.includes('PLACE:'))).toBe(true)
    // kind should be skipped
    expect(lines.some((l: string) => l.startsWith('KIND:'))).toBe(false)
  })

  it('separatorAfter is set on track action', () => {
    const actions = buildContextMenuActions(
      makeCtx({ kind: 'aircraft', rawProps: { icao: 'abc' } }),
      baseCallbacks,
    )
    const trackAction = actions.find((a) => a.id === 'track')!
    expect(trackAction.separatorAfter).toBe(true)
  })

  it('location kind with coords produces focus, copy, pin, ask-ai', () => {
    const actions = buildContextMenuActions(
      makeCtx({ kind: 'location', title: 'Location' }),
      baseCallbacks,
    )
    const ids = actions.map((a) => a.id)
    expect(ids).toEqual(['focus', 'copy-coords', 'add-pin', 'ask-ai'])
  })
})
