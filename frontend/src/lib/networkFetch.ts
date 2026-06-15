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
    ? 'API kurz nicht erreichbar (Netzwerkwechsel?) — bei anhaltenden Fehlern Seite neu laden'
    : 'Browser offline'
  console.warn(`[WorldBase/${scope}] ${label}: ${hint}`)
}
