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

/**
 * Centralized fetch wrapper for WorldBase API.
 * Automatically injects API key if present in localStorage.
 */
export async function fetchApi(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
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

  const updatedInit = { ...init, headers }
  return fetch(input, updatedInit)
}

/** fetchApi with per-request AbortController timeout (default 15s). */
export async function fetchApiWithTimeout(
  input: RequestInfo | URL,
  init?: RequestInit,
  timeoutMs = 15_000,
): Promise<Response> {
  const ac = new AbortController()
  const timer = setTimeout(() => ac.abort(), timeoutMs)
  const callerSignal = init?.signal
  if (callerSignal) {
    if (callerSignal.aborted) {
      clearTimeout(timer)
      throw new DOMException('The operation was aborted.', 'AbortError')
    }
    callerSignal.addEventListener('abort', () => ac.abort(), { once: true })
  }
  try {
    return await fetchApi(input, { ...init, signal: ac.signal })
  } finally {
    clearTimeout(timer)
  }
}
