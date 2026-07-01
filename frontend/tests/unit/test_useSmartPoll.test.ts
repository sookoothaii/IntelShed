import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useSmartPoll } from '../../src/hooks/useSmartPoll'

describe('useSmartPoll', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('starts in idle status when disabled', () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true })
    const { result } = renderHook(() =>
      useSmartPoll({ fetcher, enabled: false, immediate: false }),
    )
    expect(result.current.status).toBe('idle')
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('polls immediately on mount when enabled+immediate', async () => {
    const fetcher = vi.fn().mockResolvedValue({ value: 42 })
    const { result } = renderHook(() =>
      useSmartPoll({ fetcher, interval: 5000, immediate: true }),
    )
    // Flush microtasks for the async fetcher
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(result.current.pollCount).toBe(1)
    expect(result.current.data).toEqual({ value: 42 })
    expect(result.current.status).toBe('polling')
    expect(result.current.error).toBeNull()
  })

  it('applies exponential backoff on consecutive errors', async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error('network'))
    const { result } = renderHook(() =>
      useSmartPoll({
        fetcher,
        interval: 1000,
        maxInterval: 60_000,
        backoffMultiplier: 2,
        breakerThreshold: 10,
        immediate: true,
      }),
    )
    // First poll fails
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(result.current.consecutiveErrors).toBe(1)
    expect(result.current.status).toBe('backoff')

    // Advance past backoff (1000 * 2^1 = 2000ms, clamped to min 1000)
    await act(async () => { await vi.advanceTimersByTimeAsync(2100) })
    expect(result.current.consecutiveErrors).toBe(2)
    expect(result.current.status).toBe('backoff')

    // Advance past next backoff (1000 * 2^2 = 4000ms)
    await act(async () => { await vi.advanceTimersByTimeAsync(4100) })
    expect(result.current.consecutiveErrors).toBe(3)
  })

  it('opens circuit breaker after threshold consecutive errors', async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error('server down'))
    const { result } = renderHook(() =>
      useSmartPoll({
        fetcher,
        interval: 500,
        breakerThreshold: 3,
        breakerCooldownMs: 5000,
        immediate: true,
      }),
    )

    // First failure
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(result.current.consecutiveErrors).toBe(1)

    // Second failure (backoff: 500*2=1000)
    await act(async () => { await vi.advanceTimersByTimeAsync(1100) })
    expect(result.current.consecutiveErrors).toBe(2)

    // Third failure — circuit opens (backoff: 500*4=2000)
    await act(async () => { await vi.advanceTimersByTimeAsync(2100) })
    expect(result.current.consecutiveErrors).toBe(3)
    expect(result.current.status).toBe('circuit-open')
  })

  it('recovers from circuit-open after cooldown', async () => {
    let shouldFail = true
    const fetcher = vi.fn().mockImplementation(async () => {
      if (shouldFail) throw new Error('fail')
      return { recovered: true }
    })
    const { result } = renderHook(() =>
      useSmartPoll({
        fetcher,
        interval: 500,
        breakerThreshold: 2,
        breakerCooldownMs: 2000,
        immediate: true,
      }),
    )

    // First failure
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(result.current.consecutiveErrors).toBe(1)

    // Second failure — circuit opens
    await act(async () => { await vi.advanceTimersByTimeAsync(1100) })
    expect(result.current.consecutiveErrors).toBe(2)
    expect(result.current.status).toBe('circuit-open')

    // Fix the fetcher, advance past cooldown
    shouldFail = false
    await act(async () => { await vi.advanceTimersByTimeAsync(2500) })

    expect(result.current.status).toBe('polling')
    expect(result.current.data).toEqual({ recovered: true })
  })

  it('throttles when tab is hidden', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true })
    const hiddenInterval = 999_999
    const { result } = renderHook(() =>
      useSmartPoll({
        fetcher,
        interval: 1000,
        hiddenInterval,
        immediate: true,
      }),
    )

    // First poll succeeds
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(result.current.pollCount).toBe(1)

    // Hide tab
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })

    // Advance past normal interval — should NOT have polled (uses hiddenInterval)
    await act(async () => { await vi.advanceTimersByTimeAsync(1500) })
    expect(result.current.pollCount).toBe(1)

    // Show tab again — should poll immediately
    vi.spyOn(document, 'hidden', 'get').mockReturnValue(false)
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })

    // Flush microtasks for the immediate poll
    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(result.current.pollCount).toBe(2)
  })

  it('refetch triggers immediate poll', async () => {
    const fetcher = vi.fn().mockResolvedValue({ data: 'hello' })
    const { result } = renderHook(() =>
      useSmartPoll({ fetcher, interval: 100_000, immediate: true }),
    )

    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(result.current.pollCount).toBe(1)

    await act(async () => {
      result.current.refetch()
      await vi.advanceTimersByTimeAsync(0)
    })
    expect(result.current.pollCount).toBe(2)
  })

  it('reset clears state and re-polls', async () => {
    const fetcher = vi.fn().mockResolvedValue({ data: 'hello' })
    const { result } = renderHook(() =>
      useSmartPoll({ fetcher, interval: 100_000, immediate: true }),
    )

    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(result.current.pollCount).toBe(1)

    act(() => {
      result.current.reset()
    })

    expect(result.current.pollCount).toBe(0)
    expect(result.current.data).toBeNull()
    expect(result.current.status).toBe('idle')

    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(result.current.pollCount).toBe(1)
  })

  it('cleans up timers on unmount', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true })
    const { result, unmount } = renderHook(() =>
      useSmartPoll({ fetcher, interval: 1000, immediate: true }),
    )

    await act(async () => { await vi.advanceTimersByTimeAsync(0) })
    expect(result.current.pollCount).toBe(1)
    unmount()

    // After unmount, advancing timers should not cause errors or calls
    const callsBefore = fetcher.mock.calls.length
    act(() => {
      vi.advanceTimersByTime(10_000)
    })
    expect(fetcher.mock.calls.length).toBe(callsBefore)
  })
})
