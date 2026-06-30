import { useQuery } from '@tanstack/react-query';
import { fetchApi } from '../lib/networkFetch';
import { fetchBootstrapFast, fetchBootstrapSlow } from '../lib/bootstrapApi';

/**
 * Shared React-Query hooks for endpoints that several components poll.
 * Components subscribing to the same query key share one cache entry, so the
 * duplicate /api/situations and /api/briefing polling (badge + board + overlay)
 * collapses into a single in-flight request per interval.
 */

async function getJson<T>(url: string): Promise<T> {
  const r = await fetchApi(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json() as T;
}

type SharedOpts = {
  enabled?: boolean;
  refetchInterval?: number | false;
};

export type SituationsResponse = {
  items?: unknown[];
  count?: number;
  [key: string]: unknown;
};

export function useSituationsQuery(opts?: SharedOpts) {
  return useQuery({
    queryKey: ['situations'],
    queryFn: () => getJson<SituationsResponse>('/api/situations'),
    refetchInterval: opts?.refetchInterval ?? 60_000,
    enabled: opts?.enabled ?? true,
  });
}

export type BriefingData = {
  text?: string;
  agentic?: unknown;
  fusion_hotspots?: unknown[];
  insights?: unknown[];
  [key: string]: unknown;
};

export function useBriefingQuery(opts?: SharedOpts) {
  return useQuery({
    queryKey: ['briefing'],
    queryFn: () => getJson<BriefingData>('/api/briefing'),
    refetchInterval: opts?.refetchInterval ?? 60_000,
    enabled: opts?.enabled ?? true,
  });
}

export type InsightsResponse = {
  insights?: unknown[];
  [key: string]: unknown;
};

export function useInsightsQuery(top = 10, opts?: SharedOpts) {
  return useQuery({
    queryKey: ['insights', top],
    queryFn: () => getJson<InsightsResponse>(`/api/insights?top=${top}`),
    refetchInterval: opts?.refetchInterval ?? 60_000,
    enabled: opts?.enabled ?? true,
  });
}

export function useHealthPingQuery(opts?: SharedOpts) {
  return useQuery({
    queryKey: ['health-ping'],
    queryFn: async () => {
      const r = await fetchApi('/api/health/ping');
      if (!r.ok) throw new Error('backend offline');
      return true;
    },
    refetchInterval: opts?.refetchInterval ?? 60_000,
    enabled: opts?.enabled ?? true,
  });
}

export type ModelsResponse = {
  error?: string;
  [key: string]: unknown;
};

export function useModelsQuery(opts?: SharedOpts) {
  return useQuery({
    queryKey: ['models'],
    queryFn: () => getJson<ModelsResponse>('/api/models'),
    refetchInterval: opts?.refetchInterval ?? 60_000,
    enabled: opts?.enabled ?? true,
  });
}

// V4-45: Bootstrap hydration hooks — fetch aggregated data on page load.
// When bootstrap is disabled on the backend, these return null and
// components fall back to individual endpoint polling.

export function useBootstrapFast(opts?: SharedOpts) {
  return useQuery({
    queryKey: ['bootstrap-fast'],
    queryFn: async () => {
      const data = await fetchBootstrapFast();
      if (!data) throw new Error('bootstrap disabled');
      return data;
    },
    refetchInterval: opts?.refetchInterval ?? 1200_000, // 20 min matching s-maxage
    enabled: opts?.enabled ?? true,
    retry: false, // Don't retry when disabled
  });
}

export function useBootstrapSlow(opts?: SharedOpts) {
  return useQuery({
    queryKey: ['bootstrap-slow'],
    queryFn: async () => {
      const data = await fetchBootstrapSlow();
      if (!data) throw new Error('bootstrap disabled');
      return data;
    },
    refetchInterval: opts?.refetchInterval ?? 7200_000, // 2h matching s-maxage
    enabled: opts?.enabled ?? true,
    retry: false,
  });
}
