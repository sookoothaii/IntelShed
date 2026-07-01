/**
 * V4-50 Dual Map Engine — switch between Cesium (3D globe) and deck.gl (2D high-perf).
 *
 * Provides a React hook that manages which map engine is active, with lazy
 * loading of deck.gl only when needed (code-splitting). Cesium remains the
 * default for 3D; deck.gl is used for high-performance 2D data visualization
 * with large point clouds (e.g. 10k+ AIS positions, ADS-B tracks).
 *
 * Usage:
 *   const { engine, setEngine, deckReady } = useMapEngine();
 *   // engine: 'cesium' | 'deck'
 *   // setEngine('deck') triggers lazy import of deck.gl
 */

import { useCallback, useEffect, useState } from 'react';

export type MapEngine = 'cesium' | 'deck';

const STORAGE_KEY = 'worldbase:map-engine';

function loadStoredEngine(): MapEngine {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === 'deck' || v === 'cesium') return v;
  } catch {
    // SSR or localStorage blocked
  }
  return 'cesium';
}

function saveEngine(engine: MapEngine): void {
  try {
    localStorage.setItem(STORAGE_KEY, engine);
  } catch {
    // ignore
  }
}

// Lazy-loaded deck.gl modules — only imported when engine === 'deck'
type DeckGLModules = {
  DeckGL: any;
  ScatterplotLayer: any;
  LineLayer: any;
  HeatmapLayer: any;
  GeoJsonLayer: any;
};

let _deckModules: DeckGLModules | null = null;
let _deckLoadPromise: Promise<DeckGLModules> | null = null;

/**
 * Lazy-load deck.gl modules. Only called when switching to deck engine.
 * Returns cached modules on subsequent calls.
 */
export async function loadDeckGL(): Promise<DeckGLModules> {
  if (_deckModules) return _deckModules;
  if (_deckLoadPromise) return _deckLoadPromise;

  _deckLoadPromise = (async () => {
    const [deck, layers, aggLayers] = await Promise.all([
      // @ts-expect-error — deck.gl is an optional peer dependency, installed on demand
      import('deck.gl'),
      // @ts-expect-error — deck.gl layers, installed on demand
      import('@deck.gl/layers'),
      // @ts-expect-error — deck.gl aggregation layers, installed on demand
      import('@deck.gl/aggregation-layers'),
    ]);

    _deckModules = {
      DeckGL: deck.DeckGL,
      ScatterplotLayer: layers.ScatterplotLayer,
      LineLayer: layers.LineLayer,
      HeatmapLayer: aggLayers.HeatmapLayer,
      GeoJsonLayer: layers.GeoJsonLayer,
    };
    return _deckModules;
  })();

  return _deckLoadPromise;
}

export interface UseMapEngineReturn {
  /** Current active engine */
  engine: MapEngine;
  /** Switch engine (triggers lazy load for deck.gl) */
  setEngine: (next: MapEngine) => void;
  /** Toggle between cesium and deck */
  toggleEngine: () => void;
  /** Whether deck.gl modules are loaded and ready */
  deckReady: boolean;
  /** Whether deck.gl is currently loading */
  deckLoading: boolean;
  /** Error if deck.gl failed to load */
  deckError: string | null;
  /** Loaded deck.gl modules (null until loaded) */
  deckModules: DeckGLModules | null;
}

export function useMapEngine(): UseMapEngineReturn {
  const [engine, setEngineState] = useState<MapEngine>(loadStoredEngine);
  const [deckReady, setDeckReady] = useState(false);
  const [deckLoading, setDeckLoading] = useState(false);
  const [deckError, setDeckError] = useState<string | null>(null);
  const [deckModules, setDeckModules] = useState<DeckGLModules | null>(null);

  const setEngine = useCallback((next: MapEngine) => {
    setEngineState(next);
    saveEngine(next);
  }, []);

  const toggleEngine = useCallback(() => {
    setEngineState((prev) => {
      const next = prev === 'cesium' ? 'deck' : 'cesium';
      saveEngine(next);
      return next;
    });
  }, []);

  // Auto-load deck.gl when engine switches to deck
  useEffect(() => {
    if (engine !== 'deck' || _deckModules || deckLoading) return;

    let cancelled = false;
    setDeckLoading(true);
    setDeckError(null);

    loadDeckGL()
      .then((mods) => {
        if (cancelled) return;
        setDeckModules(mods);
        setDeckReady(true);
        setDeckLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setDeckError(
          err instanceof Error ? err.message : 'Failed to load deck.gl'
        );
        setDeckLoading(false);
        // Fallback to cesium
        setEngineState('cesium');
        saveEngine('cesium');
      });

    return () => {
      cancelled = true;
    };
  }, [engine, deckLoading]);

  return {
    engine,
    setEngine,
    toggleEngine,
    deckReady,
    deckLoading,
    deckError,
    deckModules,
  };
}
