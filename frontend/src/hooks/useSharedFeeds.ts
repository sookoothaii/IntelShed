import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../lib/networkFetch'

/**
 * Shared React-Query hooks for endpoints that several components poll.
 * Components subscribing to the same query key share one cache entry, so the
 * duplicate /api/situations and /api/briefing polling (badge + board + overlay)
 * collapses into a single in-flight request per interval.
 */

async function getJson<T = any>(url: string): Promise<T> {
  const r = await fetchApi(url)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

type SharedOpts = {
  enabled?: boolean
  refetchInterval?: number | false
}

export function useSituationsQuery(opts?: SharedOpts) {
  return useQuery({
    queryKey: ['situations'],
    queryFn: () => getJson('/api/situations'),
    refetchInterval: opts?.refetchInterval ?? 60_000,
    enabled: opts?.enabled ?? true,
  })
}

export function useBriefingQuery(opts?: SharedOpts) {
  return useQuery({
    queryKey: ['briefing'],
    queryFn: () => getJson('/api/briefing'),
    refetchInterval: opts?.refetchInterval ?? 60_000,
    enabled: opts?.enabled ?? true,
  })
}

export function useInsightsQuery(top = 10, opts?: SharedOpts) {
  return useQuery({
    queryKey: ['insights', top],
    queryFn: () => getJson(`/api/insights?top=${top}`),
    refetchInterval: opts?.refetchInterval ?? 60_000,
    enabled: opts?.enabled ?? true,
  })
}

export function useHealthPingQuery(opts?: SharedOpts) {
  return useQuery({
    queryKey: ['health-ping'],
    queryFn: async () => {
      const r = await fetchApi('/api/health/ping')
      if (!r.ok) throw new Error('backend offline')
      return true
    },
    refetchInterval: opts?.refetchInterval ?? 60_000,
    enabled: opts?.enabled ?? true,
  })
}

export function useModelsQuery(opts?: SharedOpts) {
  return useQuery({
    queryKey: ['models'],
    queryFn: () => getJson('/api/models'),
    refetchInterval: opts?.refetchInterval ?? 60_000,
    enabled: opts?.enabled ?? true,
  })
}
