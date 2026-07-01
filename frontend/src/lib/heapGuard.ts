/**
 * E-08: Heap Guard — LRU-based heap monitoring for long OSINT sessions.
 *
 * Checks `performance.memory.usedJSHeapSize` every 30s. When heap exceeds
 * threshold (800 MB default), unloads least-recently-used layers and flushes
 * Cesium tile cache. Notifies via callback (toast).
 *
 * Feature-flag: VITE_WORLDBASE_HEAP_GUARD=1 (default off, opt-in)
 */

const HEAP_CHECK_INTERVAL_MS = 30_000;
const DEFAULT_THRESHOLD_MB = 800;
const LRU_IDLE_THRESHOLD_MS = 10 * 60 * 1000; // 10 minutes

type LayerAccessTracker = Map<string, number>; // layerKey -> lastAccessedTimestamp

export interface HeapGuardOptions {
  /** Callback when heap threshold is exceeded, with current heap size in MB */
  onThresholdExceeded?: (heapMB: number) => void;
  /** Callback to get currently active layers */
  getActiveLayers?: () => string[];
  /** Callback to deactivate a layer by key */
  deactivateLayer?: (key: string) => void;
  /** Callback to flush Cesium tile cache (reduce tileCacheSize) */
  flushTileCache?: () => void;
  /** Custom threshold in MB (default 800) */
  thresholdMB?: number;
}

export interface HeapGuardHandle {
  /** Stop the heap guard interval */
  stop: () => void;
  /** Manually trigger a heap check */
  check: () => void;
  /** Record that a layer was accessed (for LRU tracking) */
  touchLayer: (key: string) => void;
  /** Get current heap usage in MB, or null if unavailable */
  getHeapMB: () => number | null;
}

function getUsedHeapMB(): number | null {
  const perf = performance as Performance & {
    memory?: { usedJSHeapSize: number; totalJSHeapSize: number; jsHeapSizeLimit: number };
  };
  if (!perf.memory) return null;
  return perf.memory.usedJSHeapSize / (1024 * 1024);
}

export function isHeapGuardEnabled(): boolean {
  return import.meta.env.VITE_WORLDBASE_HEAP_GUARD === '1';
}

export function createHeapGuard(options: HeapGuardOptions): HeapGuardHandle {
  const threshold = options.thresholdMB ?? DEFAULT_THRESHOLD_MB;
  const layerAccess: LayerAccessTracker = new Map();
  let intervalId: ReturnType<typeof setInterval> | null = null;

  function touchLayer(key: string) {
    layerAccess.set(key, Date.now());
  }

  function check() {
    const heapMB = getUsedHeapMB();
    if (heapMB == null) return;

    if (heapMB < threshold) return;

    options.onThresholdExceeded?.(heapMB);

    // LRU: find layers idle for > LRU_IDLE_THRESHOLD_MS and deactivate them
    const now = Date.now();
    const activeLayers = options.getActiveLayers?.() ?? [];

    // Sort by last access time ascending (oldest first)
    const candidates = activeLayers
      .filter((key) => {
        const lastAccess = layerAccess.get(key);
        if (lastAccess == null) return true; // never tracked = candidate
        return now - lastAccess > LRU_IDLE_THRESHOLD_MS;
      })
      .sort((a, b) => {
        const aTime = layerAccess.get(a) ?? 0;
        const bTime = layerAccess.get(b) ?? 0;
        return aTime - bTime;
      });

    // Deactivate up to 3 oldest idle layers
    let deactivated = 0;
    for (const key of candidates) {
      if (deactivated >= 3) break;
      try {
        options.deactivateLayer?.(key);
        layerAccess.delete(key);
        deactivated++;
      } catch {
        // ignore
      }
    }

    // Flush Cesium tile cache
    if (deactivated > 0) {
      try {
        options.flushTileCache?.();
      } catch {
        // ignore
      }
    }
  }

  function start() {
    if (intervalId != null) return;
    intervalId = setInterval(check, HEAP_CHECK_INTERVAL_MS);
  }

  function stop() {
    if (intervalId != null) {
      clearInterval(intervalId);
      intervalId = null;
    }
  }

  start();

  return {
    stop,
    check,
    touchLayer,
    getHeapMB: () => getUsedHeapMB(),
  };
}
