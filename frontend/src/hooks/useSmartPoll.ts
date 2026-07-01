/**
 * V4-46 SmartPollLoop — adaptive polling with exponential backoff,
 * hidden-tab throttle, and circuit breaker pattern.
 *
 * - Exponential backoff on consecutive errors (capped at maxInterval)
 * - Hidden-tab throttle: polls at `hiddenInterval` when document.hidden
 * - Circuit breaker: after `breakerThreshold` consecutive failures,
 *   stops polling for `breakerCooldownMs` before retrying
 * - Cleanup on unmount: no leaked timers
 */

import { useCallback, useEffect, useRef, useState } from 'react';

export type SmartPollStatus = 'idle' | 'polling' | 'backoff' | 'circuit-open';

export type SmartPollState<T> = {
  data: T | null;
  error: Error | null;
  status: SmartPollStatus;
  consecutiveErrors: number;
  pollCount: number;
  lastPollAt: number | null;
};

export type SmartPollOptions<T> = {
  /** Fetcher function — should return data or throw */
  fetcher: () => Promise<T>;
  /** Base interval in ms (default 30_000) */
  interval?: number;
  /** Max interval after backoff (default 300_000 = 5 min) */
  maxInterval?: number;
  /** Interval when tab is hidden (default 300_000 = 5 min) */
  hiddenInterval?: number;
  /** Backoff multiplier per consecutive error (default 2) */
  backoffMultiplier?: number;
  /** Consecutive errors before circuit opens (default 5) */
  breakerThreshold?: number;
  /** How long to wait before retrying after circuit opens (default 60_000) */
  breakerCooldownMs?: number;
  /** Whether polling is enabled (default true) */
  enabled?: boolean;
  /** Immediate first poll on mount (default true) */
  immediate?: boolean;
};

export function useSmartPoll<T>(
  options: SmartPollOptions<T>,
): SmartPollState<T> & {
  refetch: () => void;
  reset: () => void;
} {
  const {
    fetcher,
    interval = 30_000,
    maxInterval = 300_000,
    hiddenInterval = 300_000,
    backoffMultiplier = 2,
    breakerThreshold = 5,
    breakerCooldownMs = 60_000,
    enabled = true,
    immediate = true,
  } = options;

  const [state, setState] = useState<SmartPollState<T>>({
    data: null,
    error: null,
    status: 'idle',
    consecutiveErrors: 0,
    pollCount: 0,
    lastPollAt: null,
  });

  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  }, [fetcher]);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const consecutiveErrorsRef = useRef(0);
  const circuitOpenRef = useRef(false);
  const circuitOpenedAtRef = useRef(0);
  const mountedRef = useRef(true);
  const pollingRef = useRef(false);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const scheduleNext = useCallback(
    (delayMs: number) => {
      clearTimer();
      timerRef.current = setTimeout(() => {
        if (mountedRef.current) doPoll();
      }, Math.max(1000, delayMs));
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [clearTimer],
  );

  const doPoll = useCallback(async () => {
    if (!mountedRef.current || pollingRef.current) return;
    if (circuitOpenRef.current) {
      const elapsed = Date.now() - circuitOpenedAtRef.current;
      if (elapsed < breakerCooldownMs) {
        scheduleNext(breakerCooldownMs - elapsed);
        return;
      }
      // Half-open: reset and try again
      circuitOpenRef.current = false;
      setState((s) => ({ ...s, status: 'polling' }));
    }

    pollingRef.current = true;
    try {
      const data = await fetcherRef.current();
      if (!mountedRef.current) return;
      consecutiveErrorsRef.current = 0;
      setState((s) => ({
        data,
        error: null,
        status: 'polling',
        consecutiveErrors: 0,
        pollCount: s.pollCount + 1,
        lastPollAt: Date.now(),
      }));

      const isHidden = typeof document !== 'undefined' && document.hidden;
      scheduleNext(isHidden ? hiddenInterval : interval);
    } catch (err) {
      if (!mountedRef.current) return;
      consecutiveErrorsRef.current += 1;
      const errors = consecutiveErrorsRef.current;

      if (errors >= breakerThreshold) {
        circuitOpenRef.current = true;
        circuitOpenedAtRef.current = Date.now();
        setState((s) => ({
          ...s,
          error: err instanceof Error ? err : new Error(String(err)),
          status: 'circuit-open',
          consecutiveErrors: errors,
        }));
        scheduleNext(breakerCooldownMs);
      } else {
        const backoff = Math.min(
          interval * Math.pow(backoffMultiplier, errors),
          maxInterval,
        );
        setState((s) => ({
          ...s,
          error: err instanceof Error ? err : new Error(String(err)),
          status: 'backoff',
          consecutiveErrors: errors,
        }));
        scheduleNext(backoff);
      }
    } finally {
      pollingRef.current = false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [interval, maxInterval, hiddenInterval, backoffMultiplier, breakerThreshold, breakerCooldownMs, scheduleNext]);

  // Handle visibility change — reschedule when tab becomes visible
  useEffect(() => {
    if (!enabled) return;
    const onVisibility = () => {
      if (!document.hidden && !circuitOpenRef.current && !pollingRef.current) {
        // Tab visible again — poll immediately
        clearTimer();
        doPoll();
      } else if (document.hidden) {
        // Tab hidden — reschedule to hiddenInterval
        clearTimer();
        scheduleNext(hiddenInterval);
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, [enabled, clearTimer, doPoll]);

  // Main polling lifecycle
  useEffect(() => {
    mountedRef.current = true;
    if (!enabled) {
      setState((s) => ({ ...s, status: 'idle' }));
      return;
    }

    if (immediate) {
      doPoll();
    } else {
      scheduleNext(interval);
    }

    return () => {
      mountedRef.current = false;
      clearTimer();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  const refetch = useCallback(() => {
    if (!circuitOpenRef.current && !pollingRef.current) {
      clearTimer();
      doPoll();
    }
  }, [clearTimer, doPoll]);

  const reset = useCallback(() => {
    consecutiveErrorsRef.current = 0;
    circuitOpenRef.current = false;
    circuitOpenedAtRef.current = 0;
    clearTimer();
    setState({
      data: null,
      error: null,
      status: 'idle',
      consecutiveErrors: 0,
      pollCount: 0,
      lastPollAt: null,
    });
    if (enabled) doPoll();
  }, [clearTimer, doPoll, enabled]);

  return { ...state, refetch, reset };
}
