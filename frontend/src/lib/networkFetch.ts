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

export type FetchApiInit = RequestInit & { timeoutMs?: number }

/**
 * Centralized fetch wrapper for WorldBase API.
 * Automatically injects API key if present in localStorage.
 */
export async function fetchApi(input: RequestInfo | URL, init?: FetchApiInit): Promise<Response> {
  if (!canFetch()) {
    throw new Error('Browser is offline')
  }

  const apiKey =
    localStorage.getItem('WORLDBASE_API_KEY') ||
    import.meta.env.VITE_WORLDBASE_API_KEY ||
    ''
  const headers = new Headers(init?.headers)

  if (apiKey) {
    headers.set('X-API-Key', apiKey)
  }

  const { timeoutMs, signal: outerSignal, ...restInit } = init || {}
  let signal = outerSignal
  let timeoutId: ReturnType<typeof setTimeout> | undefined

  if (timeoutMs && timeoutMs > 0) {
    const controller = new AbortController()
    timeoutId = setTimeout(() => controller.abort(), timeoutMs)
    if (outerSignal) {
      outerSignal.addEventListener('abort', () => controller.abort(), { once: true })
    }
    signal = controller.signal
  }

  try {
    return await fetch(input, { ...restInit, headers, signal })
  } finally {
    if (timeoutId) clearTimeout(timeoutId)
  }
}
