import { Ion } from 'cesium'
import { fetchApi } from './networkFetch'

let _resolved = false
let _resolving: Promise<void> | null = null

/**
 * Fetch the Cesium Ion token from the backend at runtime.
 * The token is NOT baked into the Vite bundle — it comes from
 * GET /api/config/cesium and is set on Ion.defaultAccessToken.
 *
 * Falls back to import.meta.env.VITE_CESIUM_ION_TOKEN (dev convenience)
 * if the backend is unreachable or returns an empty token.
 *
 * Safe to call multiple times — resolves once per page load.
 */
export async function initCesiumToken(): Promise<void> {
  if (_resolved) return
  if (_resolving) return _resolving
  _resolving = (async () => {
    // 1. Try backend endpoint
    try {
      const r = await fetchApi('/api/config/cesium')
      if (r.ok) {
        const data = await r.json()
        const token = data?.token ?? ''
        if (token && token !== 'your_cesium_ion_token_here') {
          Ion.defaultAccessToken = token
          _resolved = true
          return
        }
      }
    } catch {
      // Backend unreachable — fall through to env fallback
    }

    // 2. Fallback: Vite env (dev convenience, keeps old workflow alive)
    const envToken = import.meta.env.VITE_CESIUM_ION_TOKEN ?? ''
    if (envToken && envToken !== 'your_cesium_ion_token_here') {
      Ion.defaultAccessToken = envToken
    } else {
      console.warn(
        '[WorldBase] Cesium Ion token not available — ellipsoid terrain only. ' +
          'Set CESIUM_ION_TOKEN in backend/.env or VITE_CESIUM_ION_TOKEN in frontend/.env.',
      )
    }
    _resolved = true
  })()
  return _resolving
}

/** True if a Cesium Ion token has been loaded (from backend or env). */
export function hasCesiumIonToken(): boolean {
  return Boolean(Ion.defaultAccessToken)
}
