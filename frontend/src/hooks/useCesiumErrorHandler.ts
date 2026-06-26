import { useEffect, useRef, useState, type MutableRefObject } from 'react'
import type { Viewer, Globe } from 'cesium'
import type { CesiumRenderErrorEvent, CesiumTileLoadErrorEvent } from '../lib/types'

/** Cesium Globe has tileLoadErrorEvent at runtime but it's missing from type defs in some versions. */
type GlobeWithTileError = Globe & { tileLoadErrorEvent?: { addEventListener(fn: (e: CesiumTileLoadErrorEvent) => void): void; removeEventListener(fn: (e: CesiumTileLoadErrorEvent) => void): void } }

/**
 * Hook to attach Cesium crash handlers to a Viewer instance.
 *
 * - `scene.renderError` → throws a React error that the ErrorBoundary catches
 * - `globe.tileLoadErrorEvent` → log + suppress (don't crash on tile 404s)
 *
 * Usage inside Globe component:
 *   useCesiumErrorHandler(viewerRef, visible)
 */
export function useCesiumErrorHandler(
  viewerRef: MutableRefObject<Viewer | null>,
  visible: boolean,
): { cesiumError: Error | null; clearError: () => void } {
  const [cesiumError, setCesiumError] = useState<Error | null>(null)
  const renderErrorListenerRef = useRef<((e: CesiumRenderErrorEvent) => void) | null>(null)
  const tileLoadErrorListenerRef = useRef<((e: CesiumTileLoadErrorEvent) => void) | null>(null)

  const clearError = () => setCesiumError(null)

  useEffect(() => {
    if (!visible) return
    const v = viewerRef.current
    if (!v || v.isDestroyed?.()) return

    const scene = v.scene

    // renderError: Cesium's own crash event — rethrow into React tree
    const onRenderError = (e: CesiumRenderErrorEvent) => {
      const err = new Error(
        `Cesium renderError: ${e?.message ?? e?.error?.message ?? 'GPU context lost or malformed data'}`,
      )
      if (e?.error?.stack) err.stack = e.error.stack
      setCesiumError(err)
      // Rethrow so the ErrorBoundary catches it
      setTimeout(() => { throw err }, 0)
    }

    // tileLoadError: suppress tile 404s (don't crash)
    const onTileLoadError = (e: CesiumTileLoadErrorEvent) => {
      // Silently suppress — tile errors are expected (stale providers, CDN hiccups)
      // Only log to console at debug level to avoid spam
      if (typeof console !== 'undefined' && console.debug) {
        console.debug('[Cesium] tileLoadError suppressed:', e?.message ?? e)
      }
    }

    try {
      scene.renderError.addEventListener(onRenderError)
      renderErrorListenerRef.current = onRenderError
    } catch { /* older Cesium */ }

    try {
      ;(scene.globe as GlobeWithTileError).tileLoadErrorEvent?.addEventListener(onTileLoadError)
      tileLoadErrorListenerRef.current = onTileLoadError
    } catch { /* globe not ready */ }

    return () => {
      try {
        if (renderErrorListenerRef.current) {
          scene.renderError.removeEventListener(renderErrorListenerRef.current)
        }
      } catch { /* torn down */ }
      try {
        if (tileLoadErrorListenerRef.current && !v.isDestroyed?.()) {
          ;(scene.globe as GlobeWithTileError).tileLoadErrorEvent?.removeEventListener(tileLoadErrorListenerRef.current)
        }
      } catch { /* torn down */ }
      renderErrorListenerRef.current = null
      tileLoadErrorListenerRef.current = null
    }
  }, [viewerRef, visible])

  return { cesiumError, clearError }
}
