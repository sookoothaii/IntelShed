import {
  Color,
  ColorMaterialProperty,
  ConstantProperty,
  EllipseGraphics,
  type Entity,
} from 'cesium';

/** Full pulse ring cycle (ms). */
export const PULSE_CYCLE_MS = 2000;

/** Throttle pulse property updates (~15 fps) so non-constant CallbackProperty is avoided. */
export const PULSE_TICK_MS = 66;

type PulseUpdater = {
  cycleMs: number;
  update: (phase: number) => void;
};

const updaters = new Set<PulseUpdater>();
let lastTickAt = 0;

export function registerPulseUpdater(updater: PulseUpdater): () => void {
  updaters.add(updater);
  return () => updaters.delete(updater);
}

export function clearPulseUpdaters(): void {
  updaters.clear();
  lastTickAt = 0;
}

/** True when at least one throttled pulse ring is registered (quakes/nodes/military). */
export function hasPulseUpdaters(): boolean {
  return updaters.size > 0;
}

/** Returns true when a pulse frame was applied (caller may requestRender). */
export function tickPulseAnimations(now = Date.now()): boolean {
  if (updaters.size === 0) return false;
  if (now - lastTickAt < PULSE_TICK_MS) return false;
  lastTickAt = now;
  for (const u of updaters) {
    const phase = (now % u.cycleMs) / u.cycleMs;
    u.update(phase);
  }
  return true;
}

export type PulseEllipseConfig = {
  cycleMs?: number;
  baseRadius: number;
  pulseScale: number;
  color: Color;
  alphaScale: number;
  minorScale?: number;
};

/** Attach a throttled expanding ring; returns cleanup (call before entity remove). */
export function attachPulseEllipse(entity: Entity, config: PulseEllipseConfig): () => void {
  const cycleMs = config.cycleMs ?? PULSE_CYCLE_MS;
  const minorScale = config.minorScale ?? 0.97;
  const semiMajor = new ConstantProperty(config.baseRadius);
  const semiMinor = new ConstantProperty(config.baseRadius * minorScale);
  const colorProp = new ConstantProperty(config.color.withAlpha(config.alphaScale));
  const material = new ColorMaterialProperty(colorProp);

  entity.ellipse = new EllipseGraphics({
    semiMajorAxis: semiMajor,
    semiMinorAxis: semiMinor,
    material,
  });

  return registerPulseUpdater({
    cycleMs,
    update: (phase) => {
      const r = config.baseRadius + phase * config.pulseScale;
      semiMajor.setValue(r);
      semiMinor.setValue(r * minorScale);
      colorProp.setValue(config.color.withAlpha(config.alphaScale * (1 - phase)));
    },
  });
}

export function clearPulseCleanups(cleanups: Array<() => void>): void {
  for (const fn of cleanups) fn();
  cleanups.length = 0;
}
