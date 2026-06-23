import { QueryClient } from '@tanstack/react-query'

/** Shared HUD poll interval — deduped via React Query. */
export const HUD_POLL_MS = 60_000

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
})
