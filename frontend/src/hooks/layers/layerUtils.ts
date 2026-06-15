import { Cartesian3, Color, NearFarScalar, type CustomDataSource, type Viewer } from 'cesium';

export function viewerAlive(viewer: Viewer | null | undefined): viewer is Viewer {
  if (!viewer) return false;
  return !(viewer as { isDestroyed?: () => boolean }).isDestroyed?.();
}

export function attachDataSource(viewer: Viewer | null, src: CustomDataSource): boolean {
  if (!viewerAlive(viewer)) return false;
  try {
    viewer.dataSources.add(src);
    return true;
  } catch {
    return false;
  }
}

export function detachDataSource(viewer: Viewer | null, src: CustomDataSource | null | undefined): void {
  if (!src || !viewerAlive(viewer)) return;
  try {
    viewer.dataSources.remove(src);
  } catch {
    /* viewer already destroyed */
  }
}

export function parseEventMs(date: string | undefined): number {
  if (!date) return 0;
  const t = Date.parse(date);
  return Number.isFinite(t) ? t : 0;
}

export function timelineCutoffMs(scrubT: number, hours: number): number {
  const now = Date.now();
  const windowMs = hours * 3600 * 1000;
  return now - windowMs + scrubT * windowMs;
}

export function feedPos(lon: number, lat: number) {
  return Cartesian3.fromDegrees(lon, lat, 0);
}

export function feedPoint(
  pixelSize: number,
  color: Color,
  opts?: { outline?: Color; outlineWidth?: number; scaleByDistance?: NearFarScalar }
) {
  return {
    pixelSize,
    color,
    outlineColor: opts?.outline ?? Color.WHITE,
    outlineWidth: opts?.outlineWidth ?? 2,
    ...(opts?.scaleByDistance ? { scaleByDistance: opts.scaleByDistance } : {}),
  };
}
