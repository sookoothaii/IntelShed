const lastLog = new Map<string, number>()
const LOG_COOLDOWN_MS = 60_000

/** Skip fetch when browser reports offline (avoids ERR_NETWORK_CHANGED spam). */
export function canFetch(): boolean {
  return typeof navigator === 'undefined' || navigator.onLine
}

export function logFetchError(scope: string, label: string): void {
  const key = `${scope}:${label}`
  const now = Date.now()
  if (now - (lastLog.get(key) ?? 0) < LOG_COOLDOWN_MS) return
  lastLog.set(key, now)
  const hint = navigator.onLine
    ? 'API briefly unreachable (network change?) — reload the page if errors persist'
    : 'Browser offline'
  console.warn(`[WorldBase/${scope}] ${label}: ${hint}`)
}

export type FetchApiOptions = RequestInit & {
  /** Abort the request after this many milliseconds (client-side). */
  timeoutMs?: number
}

/**
 * Centralized fetch wrapper for WorldBase API.
 * Automatically injects API key if present in localStorage.
 */
export async function fetchApi(input: RequestInfo | URL, init?: FetchApiOptions): Promise<Response> {
  if (!canFetch()) {
    throw new Error('Browser is offline')
  }

  const { timeoutMs, ...requestInit } = init ?? {}
  const apiKey =
    localStorage.getItem('WORLDBASE_API_KEY') ||
    import.meta.env.VITE_WORLDBASE_API_KEY ||
    ''
  const headers = new Headers(requestInit.headers)

  if (apiKey) {
    headers.set('X-API-Key', apiKey)
  }

  const updatedInit: RequestInit = { ...requestInit, headers }

  if (timeoutMs != null && timeoutMs > 0) {
    const ac = new AbortController()
    const timer = setTimeout(() => ac.abort(), timeoutMs)
    if (requestInit.signal) {
      if (requestInit.signal.aborted) {
        ac.abort()
      } else {
        requestInit.signal.addEventListener('abort', () => ac.abort(), { once: true })
      }
    }
    try {
      return await fetch(input, { ...updatedInit, signal: ac.signal })
    } finally {
      clearTimeout(timer)
    }
  }

  return fetch(input, updatedInit)
}
