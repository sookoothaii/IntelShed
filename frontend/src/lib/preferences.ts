/**
 * localStorage preferences hydration (I10).
 *
 * Persists user preferences across sessions: active tab, layer presets,
 * dark mode, split view state, map zoom level.
 * sessionStorage remains for session-specific state (active filters, selected entities).
 */

const STORAGE_KEY = "worldbase.preferences";

export interface Preferences {
  activeTab: string;
  splitView: boolean;
  splitTab: string | null;
  darkMode: boolean;
  layerVisibility: Record<string, boolean>;
  mapZoom: number | null;
  mapCenter: [number, number] | null; // [lon, lat]
}

const DEFAULTS: Preferences = {
  activeTab: "globe",
  splitView: false,
  splitTab: null,
  darkMode: true,
  layerVisibility: {},
  mapZoom: null,
  mapCenter: null,
};

export function loadPreferences(): Preferences {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULTS };
    const parsed = JSON.parse(raw);
    return { ...DEFAULTS, ...parsed };
  } catch {
    return { ...DEFAULTS };
  }
}

export function savePreferences(prefs: Partial<Preferences>): void {
  try {
    const current = loadPreferences();
    const merged = { ...current, ...prefs };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
  } catch {
    // localStorage might be full or disabled — non-fatal
  }
}

export function clearPreferences(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // non-fatal
  }
}

/**
 * Hydrate the HUD store from localStorage on app boot.
 * Call before first render.
 */
export function hydrateFromStorage(): Preferences {
  return loadPreferences();
}

/**
 * Debounced save — call on state changes.
 */
let saveTimer: ReturnType<typeof setTimeout> | null = null;

export function debouncedSavePreferences(prefs: Partial<Preferences>, delay = 500): void {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => savePreferences(prefs), delay);
}
