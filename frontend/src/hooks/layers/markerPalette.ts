/**
 * T3 / Phase 4 — Marker discipline for MSS theme.
 *
 * Reduces ~20 per-feed rainbow colors to ≤5 functional categories.
 * When theme === 'mss', all feed markers use this palette.
 * Cyber theme is unaffected (hooks fall through to original colors).
 */

import { Color } from 'cesium';

/** Functional marker categories — map by meaning, not by feed. */
export type MarkerCategory = 'critical' | 'warning' | 'info' | 'intel' | 'own';

/** MSS palette: 5 colors, each carries semantic meaning. */
const MSS_PALETTE: Record<MarkerCategory, Color> = {
  critical: Color.fromCssColorString('#EF4444'), // red — quakes, wildfires, geopolitics
  warning: Color.fromCssColorString('#F59E0B'), // amber — events, gdacs, volcanoes, hazards
  info: Color.fromCssColorString('#60A5FA'), // blue — aircraft, satellites, maritime, transit
  intel: Color.fromCssColorString('#A78BFA'), // purple — intelFt, darkweb, outages
  own: Color.fromCssColorString('#8BC34A'), // green/accent — nodes, osint
};

/** Dim context color — single muted hue for non-selected markers. */
const MSS_CONTEXT_GREY = Color.fromCssColorString('#6B7280');

/** Feed name → category mapping. */
const FEED_CATEGORY: Record<string, MarkerCategory> = {
  // Critical
  quakes: 'critical',
  wildfires: 'critical',
  geopolitics: 'critical',
  // Warning
  events: 'warning',
  gdacs: 'warning',
  volcanoes: 'warning',
  hazards: 'warning',
  lightning: 'warning',
  // Info
  aircraft: 'info',
  satellites: 'info',
  maritime: 'info',
  transit: 'info',
  piAis: 'info',
  trafficCams: 'info',
  weather: 'info',
  pegel: 'info',
  energy: 'info',
  airquality: 'info',
  // Intel
  intelFt: 'intel',
  darkweb: 'intel',
  outages: 'intel',
  // Own
  nodes: 'own',
  osint: 'own',
};

/** Schema → category for FtM intel entities. */
const SCHEMA_CATEGORY: Record<string, MarkerCategory> = {
  Person: 'intel',
  Organization: 'intel',
  Company: 'intel',
  Vessel: 'info',
  Event: 'warning',
  Airplane: 'info',
};

/**
 * Check if the MSS theme is currently active by reading the DOM.
 * Safe to call from useEffect hooks (runs after DOM mutation).
 */
export function isMssTheme(): boolean {
  return document.documentElement.dataset.theme === 'mss';
}

/**
 * Get the marker color for a feed in the current theme.
 * Returns MSS palette color when MSS is active, otherwise returns
 * the fallback (caller's original cyber-theme color).
 */
export function feedMarkerColor(feed: string, fallback: Color): Color {
  if (!isMssTheme()) return fallback;
  const cat = FEED_CATEGORY[feed];
  if (!cat) return MSS_PALETTE.info; // unknown feeds default to info blue
  return MSS_PALETTE[cat];
}

/**
 * Get the marker color for an FtM schema in the current theme.
 */
export function schemaMarkerColor(schema: string | undefined, fallback: Color): Color {
  if (!isMssTheme()) return fallback;
  const cat = SCHEMA_CATEGORY[schema || ''] ?? 'intel';
  return MSS_PALETTE[cat];
}

/**
 * T3 focus+context: returns the alpha for a marker given whether
 * an entity is selected and whether this marker is the selected one.
 *
 * - No selection: full opacity (1.0)
 * - Selection exists, this is selected: full opacity (1.0)
 * - Selection exists, this is NOT selected: dimmed (0.18)
 */
export function focusContextAlpha(isSelected: boolean, hasSelection: boolean): number {
  if (!hasSelection) return 1.0;
  return isSelected ? 1.0 : 0.18;
}

/**
 * T3 focus+context: returns the color for a marker, dimming to
 * context grey when another entity is selected.
 */
export function focusContextColor(
  baseColor: Color,
  isSelected: boolean,
  hasSelection: boolean,
): Color {
  if (!hasSelection || isSelected) return baseColor;
  return MSS_CONTEXT_GREY;
}

/**
 * Zoom-gating: returns a DistanceDisplayCondition for MSS theme.
 * At or above the threshold height, markers are hidden (clustered/heatmap phase).
 * Below the threshold, individual markers show.
 *
 * @param maxHeight Maximum camera height (meters) at which markers are visible.
 *                  Default: 8e6 (~viewing continent level).
 */
export function mssZoomGate(maxHeight = 8e6): {
  distanceDisplayCondition?: { near: number; far: number };
} {
  if (!isMssTheme()) return {};
  return { distanceDisplayCondition: { near: 0, far: maxHeight } };
}
