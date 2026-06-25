import { describe, it, expect } from 'vitest'
import type { FocusTarget, WebcamFocusRef } from '../../src/lib/focus'

describe('focus types', () => {
  it('FocusTarget has required fields', () => {
    const target: FocusTarget = {
      ts: Date.now(),
      kind: 'quake',
      lon: 100.5,
      lat: 13.7,
      height: 400000,
      title: 'Test Event',
      lines: ['line1', 'line2'],
    }
    expect(target.kind).toBe('quake')
    expect(target.lon).toBe(100.5)
    expect(target.lat).toBe(13.7)
    expect(target.lines).toHaveLength(2)
  })

  it('FocusTarget has optional fields', () => {
    const target: FocusTarget = {
      ts: Date.now(),
      kind: 'webcam',
      lon: 100,
      lat: 13,
      title: 'Cam',
      lines: [],
      link: 'https://example.com',
      webcam: {
        id: 'cam1',
        name: 'Test Cam',
        url: 'https://example.com/stream',
      },
    }
    expect(target.link).toBe('https://example.com')
    expect(target.webcam?.id).toBe('cam1')
  })

  it('WebcamFocusRef has id and optional fields', () => {
    const ref: WebcamFocusRef = {
      id: 'cam1',
      name: 'Test',
      source: 'test',
      url: 'https://example.com',
      embed: null,
      detail_url: 'https://example.com/detail',
      category: 'traffic',
      country: 'TH',
    }
    expect(ref.id).toBe('cam1')
    expect(ref.embed).toBeNull()
  })
})
