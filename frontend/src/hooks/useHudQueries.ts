import { useQuery } from '@tanstack/react-query'
import { fetchApi } from '../lib/networkFetch'
import { HUD_POLL_MS } from '../lib/queryClient'

export const hudQueryKeys = {
  situations: ['hud', 'situations'] as const,
  briefing: ['hud', 'briefing'] as const,
  insights: (top: number) => ['hud', 'insights', top] as const,
  healthPing: ['hud', 'health', 'ping'] as const,
  models: ['hud', 'models'] as const,
  analysis: (key: string) => ['hud', 'analysis', key] as const,
}

async function fetchJson(url: string) {
  const r = await fetchApi(url)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

export function useSituationsQuery(enabled = true) {
  return useQuery({
    queryKey: hudQueryKeys.situations,
    queryFn: () => fetchJson('/api/situations'),
    refetchInterval: HUD_POLL_MS,
    enabled,
  })
}

export function useBriefingQuery(enabled = true) {
  return useQuery({
    queryKey: hudQueryKeys.briefing,
    queryFn: () => fetchJson('/api/briefing'),
    refetchInterval: HUD_POLL_MS,
    enabled,
  })
}

export function useInsightsQuery(top = 10, enabled = true) {
  return useQuery({
    queryKey: hudQueryKeys.insights(top),
    queryFn: () => fetchJson(`/api/insights?top=${top}`),
    refetchInterval: HUD_POLL_MS,
    enabled,
  })
}

export function useHealthPingQuery(enabled = true) {
  return useQuery({
    queryKey: hudQueryKeys.healthPing,
    queryFn: async () => {
      const r = await fetchApi('/api/health/ping')
      return { ok: r.ok }
    },
    refetchInterval: HUD_POLL_MS,
    enabled,
  })
}

export function useModelsQuery(enabled = true) {
  return useQuery({
    queryKey: hudQueryKeys.models,
    queryFn: async () => {
      const r = await fetchApi('/api/models')
      const d = await r.json()
      return { online: !d.error }
    },
    refetchInterval: HUD_POLL_MS,
    enabled,
  })
}
