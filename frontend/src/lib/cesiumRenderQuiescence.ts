import type { Viewer } from 'cesium'

/** Layers that animate every frame (CallbackProperty pulse or live position updates). */
export type QuiescenceLayerFlags = {
  quakes: boolean
  nodes: boolean
  military: boolean
  aircraft: boolean
  satellites: boolean
  transit: boolean
  maritime: boolean
  lightning: boolean
}

export type RenderQuiescenceState = {
  visible: boolean
  layers: QuiescenceLayerFlags
  timelineLive: boolean
  hasFocusRing: boolean
  hasTrackedEntity: boolean
  cameraMoving: boolean
}

export type RenderQuiescenceOptions = {
  normalFps: number
  idleFps: number
  /** Stable-idle dwell before engaging low fps (ms). */
  settleMs?: number
  /** Poll interval while active (ms). */
  pollMs?: number
  getState: () => RenderQuiescenceState
}

/** High-priority (visible) globe tile load queue — Cesium internal, read-only. */
export function getGlobeVisibleTileLoadQueue(viewer: Viewer): number {
  try {
    const surface = (viewer.scene.globe as { _surface?: { _tileLoadQueueHigh?: unknown[] } })._surface
    const high = surface?._tileLoadQueueHigh
    if (Array.isArray(high)) return high.length
    return viewer.scene.globe.tilesLoaded ? 0 : 1
  } catch {
    return 1
  }
}

function hasMotionOrPulseLayers(layers: QuiescenceLayerFlags): boolean {
  return !!(
    layers.quakes ||
    layers.nodes ||
    layers.military ||
    layers.aircraft ||
    layers.satellites ||
    layers.transit ||
    layers.maritime ||
    layers.lightning
  )
}

function isSceneStatic(state: RenderQuiescenceState, visibleQueue: number): boolean {
  if (!state.visible || !state.timelineLive) return false
  if (state.cameraMoving || state.hasTrackedEntity || state.hasFocusRing) return false
  if (hasMotionOrPulseLayers(state.layers)) return false
  return visibleQueue === 0
}

/**
 * Drops viewer.targetFrameRate when the visible globe is fully loaded and nothing
 * animates, then restores full fps + requestRender on activity. Opt-in thermal lever
 * for stuck off-screen preload tiles that keep tilesLoaded=false at idle.
 */
export function attachRenderQuiescence(viewer: Viewer, options: RenderQuiescenceOptions): () => void {
  const settleMs = options.settleMs ?? 2000
  const pollMs = options.pollMs ?? 500
  const normalFps = options.normalFps > 0 ? options.normalFps : 30
  const idleFps = options.idleFps > 0 ? options.idleFps : 2

  let quiescent = false
  let idleSince = 0
  const cameraMovingRef = { current: false }

  const wake = () => {
    idleSince = 0
    if (!quiescent) return
    quiescent = false
    if ((viewer as { isDestroyed?: () => boolean }).isDestroyed?.()) return
    try {
      viewer.targetFrameRate = normalFps
      viewer.scene.requestRender()
    } catch {
      /* teardown */
    }
  }

  const onMoveStart = () => {
    cameraMovingRef.current = true
    wake()
  }
  const onMoveEnd = () => {
    cameraMovingRef.current = false
    wake()
  }

  viewer.camera.moveStart.addEventListener(onMoveStart)
  viewer.camera.moveEnd.addEventListener(onMoveEnd)

  const tick = () => {
    if ((viewer as { isDestroyed?: () => boolean }).isDestroyed?.()) return
    const state = options.getState()
    const merged = { ...state, cameraMoving: state.cameraMoving || cameraMovingRef.current }
    if (!merged.visible) {
      wake()
      return
    }

    const visibleQueue = getGlobeVisibleTileLoadQueue(viewer)
    if (!isSceneStatic(merged, visibleQueue)) {
      wake()
      return
    }

    const now = Date.now()
    if (!idleSince) idleSince = now
    if (now - idleSince < settleMs) return

    if (quiescent) return
    quiescent = true
    try {
      viewer.targetFrameRate = idleFps
    } catch {
      /* teardown */
    }
  }

  const pollTimer = setInterval(tick, pollMs)
  tick()

  return () => {
    clearInterval(pollTimer)
    try {
      viewer.camera.moveStart.removeEventListener(onMoveStart)
      viewer.camera.moveEnd.removeEventListener(onMoveEnd)
    } catch {
      /* ignore */
    }
    wake()
  }
}
