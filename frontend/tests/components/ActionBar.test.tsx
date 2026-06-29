import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import ActionBar from '../../src/components/ActionBar'

describe('ActionBar', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('renders all 3 buttons by default', () => {
    render(<ActionBar itemId="test-1" itemTitle="Test Item" />)
    expect(screen.getByText('⚑ FLAG')).toBeDefined()
    expect(screen.getByText('⟳ RE-ANALYZE')).toBeDefined()
    expect(screen.getByText('▶ PUBLISH')).toBeDefined()
  })

  it('hides Flag when showFlag=false', () => {
    render(<ActionBar itemId="test-1" showFlag={false} />)
    expect(screen.queryByText('⚑ FLAG')).toBeNull()
    expect(screen.getByText('⟳ RE-ANALYZE')).toBeDefined()
    expect(screen.getByText('▶ PUBLISH')).toBeDefined()
  })

  it('hides Re-Analyze when showReAnalyze=false', () => {
    render(<ActionBar itemId="test-1" showReAnalyze={false} />)
    expect(screen.getByText('⚑ FLAG')).toBeDefined()
    expect(screen.queryByText('⟳ RE-ANALYZE')).toBeNull()
    expect(screen.getByText('▶ PUBLISH')).toBeDefined()
  })

  it('hides Publish when showPublish=false', () => {
    render(<ActionBar itemId="test-1" showPublish={false} />)
    expect(screen.getByText('⚑ FLAG')).toBeDefined()
    expect(screen.getByText('⟳ RE-ANALYZE')).toBeDefined()
    expect(screen.queryByText('▶ PUBLISH')).toBeNull()
  })

  it('renders no buttons when all show flags are false', () => {
    const { container } = render(
      <ActionBar itemId="test-1" showFlag={false} showReAnalyze={false} showPublish={false} />,
    )
    const buttons = container.querySelectorAll('.action-bar-btn')
    expect(buttons.length).toBe(0)
  })

  it('has role="toolbar" with aria-label', () => {
    render(<ActionBar itemId="test-1" itemTitle="My Insight" />)
    const toolbar = screen.getByRole('toolbar')
    expect(toolbar.getAttribute('aria-label')).toContain('My Insight')
  })

  it('Flag button calls /api/briefing/pipeline/move and shows success', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{"ok":true}', { status: 200 }),
    )
    render(<ActionBar itemId="item-123" />)

    const flagBtn = screen.getByText('⚑ FLAG')
    fireEvent.click(flagBtn)

    await waitFor(() => {
      expect(screen.getByText('✓ FLAGGED')).toBeDefined()
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const call = fetchMock.mock.calls[0]
    const url = typeof call[0] === 'string' ? call[0] : (call[0] as Request).url
    expect(url).toContain('/api/briefing/pipeline/move')
    const body = JSON.parse(call[1]?.body as string)
    expect(body.item_id).toBe('item-123')
    expect(body.target_stage).toBe('INGEST')
    fetchMock.mockRestore()
  })

  it('Flag button is disabled after flagging', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{"ok":true}', { status: 200 }),
    )
    render(<ActionBar itemId="item-123" />)

    const flagBtn = screen.getByText('⚑ FLAG')
    fireEvent.click(flagBtn)

    await waitFor(() => {
      const flaggedBtn = screen.getByText('✓ FLAGGED')
      expect((flaggedBtn as HTMLButtonElement).disabled).toBe(true)
    })
  })

  it('Re-Analyze calls /api/intel/semantic/run', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{"ok":true}', { status: 200 }),
    )
    render(<ActionBar itemId="item-456" entityId="ent-abc" />)

    const analyzeBtn = screen.getByText('⟳ RE-ANALYZE')
    fireEvent.click(analyzeBtn)

    await waitFor(() => {
      expect(screen.getByText('✓ DONE')).toBeDefined()
    })

    const call = fetchMock.mock.calls[0]
    const url = typeof call[0] === 'string' ? call[0] : (call[0] as Request).url
    expect(url).toContain('/api/intel/semantic/run')
    expect(call[1]?.method).toBe('POST')
    fetchMock.mockRestore()
  })

  it('Publish calls /api/briefing/generate', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{"ok":true}', { status: 200 }),
    )
    render(<ActionBar itemId="item-789" />)

    const publishBtn = screen.getByText('▶ PUBLISH')
    fireEvent.click(publishBtn)

    await waitFor(() => {
      expect(screen.getByText('✓ PUBLISHED')).toBeDefined()
    })

    const call = fetchMock.mock.calls[0]
    const url = typeof call[0] === 'string' ? call[0] : (call[0] as Request).url
    expect(url).toContain('/api/briefing/generate')
    expect(call[1]?.method).toBe('POST')
    fetchMock.mockRestore()
  })

  it('shows ERROR on Flag when fetch fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('network down'))
    render(<ActionBar itemId="item-err" />)

    fireEvent.click(screen.getByText('⚑ FLAG'))

    await waitFor(() => {
      expect(screen.getByText('✗ ERROR')).toBeDefined()
    })
  })

  it('shows ERROR on Re-Analyze when fetch returns non-ok', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{"error":"fail"}', { status: 503 }),
    )
    render(<ActionBar itemId="item-err" />)

    fireEvent.click(screen.getByText('⟳ RE-ANALYZE'))

    await waitFor(() => {
      expect(screen.getByText('✗ ERROR')).toBeDefined()
    })
  })

  it('shows ERROR on Publish when fetch fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('server crash'))
    render(<ActionBar itemId="item-err" />)

    fireEvent.click(screen.getByText('▶ PUBLISH'))

    await waitFor(() => {
      expect(screen.getByText('✗ ERROR')).toBeDefined()
    })
  })

  it('calls onFlagged callback after successful flag', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{"ok":true}', { status: 200 }),
    )
    const onFlagged = vi.fn()
    render(<ActionBar itemId="cb-1" onFlagged={onFlagged} />)

    fireEvent.click(screen.getByText('⚑ FLAG'))

    await waitFor(() => {
      expect(onFlagged).toHaveBeenCalledWith('cb-1')
    })
  })

  it('calls onReAnalyzed callback after successful re-analyze', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{"ok":true}', { status: 200 }),
    )
    const onReAnalyzed = vi.fn()
    render(<ActionBar itemId="cb-2" onReAnalyzed={onReAnalyzed} />)

    fireEvent.click(screen.getByText('⟳ RE-ANALYZE'))

    await waitFor(() => {
      expect(onReAnalyzed).toHaveBeenCalledWith('cb-2')
    })
  })

  it('calls onPublished callback after successful publish', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('{"ok":true}', { status: 200 }),
    )
    const onPublished = vi.fn()
    render(<ActionBar itemId="cb-3" onPublished={onPublished} />)

    fireEvent.click(screen.getByText('▶ PUBLISH'))

    await waitFor(() => {
      expect(onPublished).toHaveBeenCalledWith('cb-3')
    })
  })

  it('buttons have correct CSS classes', () => {
    const { container } = render(<ActionBar itemId="css-1" />)
    expect(container.querySelector('.action-bar-btn--flag')).not.toBeNull()
    expect(container.querySelector('.action-bar-btn--analyze')).not.toBeNull()
    expect(container.querySelector('.action-bar-btn--publish')).not.toBeNull()
  })

  it('buttons have aria-labels', () => {
    render(<ActionBar itemId="a11y-1" itemTitle="Important Event" />)
    expect(screen.getByLabelText('Flag as false positive / requires review')).not.toBeNull()
    expect(screen.getByLabelText('Re-run agent orchestrator on this item')).not.toBeNull()
    expect(screen.getByLabelText('Add to next briefing and push to Pi')).not.toBeNull()
  })

  it('buttons are disabled while pending', async () => {
    let resolveFn: (val: Response) => void = () => {}
    vi.spyOn(globalThis, 'fetch').mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveFn = resolve
      }),
    )
    render(<ActionBar itemId="pend-1" />)

    const flagBtn = screen.getByText('⚑ FLAG') as HTMLButtonElement
    fireEvent.click(flagBtn)

    await waitFor(() => {
      const pendingBtn = screen.getByText('FLAGGING…') as HTMLButtonElement
      expect(pendingBtn.disabled).toBe(true)
    })

    // Also check other buttons are still enabled (independent)
    const analyzeBtn = screen.getByText('⟳ RE-ANALYZE') as HTMLButtonElement
    expect(analyzeBtn.disabled).toBe(false)

    resolveFn(new Response('{"ok":true}', { status: 200 }))
  })

  it('recovers from error state back to idle', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new Error('fail'))
    render(<ActionBar itemId="rec-1" />)

    fireEvent.click(screen.getByText('⚑ FLAG'))
    await waitFor(() => expect(screen.getByText('✗ ERROR')).toBeDefined())

    // After timeout, should return to idle
    await waitFor(
      () => expect(screen.getByText('⚑ FLAG')).toBeDefined(),
      { timeout: 5000 },
    )
  })
})
