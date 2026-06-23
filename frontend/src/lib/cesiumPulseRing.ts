import { Color, type Entity, type Viewer } from 'cesium'

/** ~2 Hz pulse updates — avoids per-frame CallbackProperty evaluation. */
export const PULSE_INTERVAL_MS = 500

export type PulseRingSpec = {
  entity: Entity
  t0: number
  periodMs: number
  baseRadius: number
  ampRadius: number
  color: Color
  alphaPeak: number
}

export function pulsePhase(t0: number, periodMs: number): number {
  return ((Date.now() - t0) % periodMs) / periodMs
}

export function applyPulseRing(spec: PulseRingSpec): void {
  const ph = pulsePhase(spec.t0, spec.periodMs)
  const major = spec.baseRadius + ph * spec.ampRadius
  spec.entity.ellipse = {
    semiMajorAxis: major,
    semiMinorAxis: major * 0.97,
    material: spec.color.withAlpha(spec.alphaPeak * (1 - ph)),
    height: 0,
  } as any
}

/** Drive pulse rings at PULSE_INTERVAL_MS instead of every render frame. */
export function startPulseAnimator(
  viewer: Viewer,
  getSpecs: () => PulseRingSpec[],
): () => void {
  const id = window.setInterval(() => {
    if ((viewer as any).isDestroyed?.()) return
    const specs = getSpecs()
    if (!specs.length) return
    for (const spec of specs) applyPulseRing(spec)
    try {
      viewer.scene.requestRender()
    } catch {
      /* teardown */
    }
  }, PULSE_INTERVAL_MS)
  return () => clearInterval(id)
}
