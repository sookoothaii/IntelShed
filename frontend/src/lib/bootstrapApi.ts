/**
 * V4-45 Bootstrap Hydration API client.
 *
 * Fetches aggregated data in 2 parallel requests (fast + slow) to reduce
 * Time-to-Interactive on page load. Falls back to individual endpoints
 * when bootstrap is disabled (WORLDBASE_BOOTSTRAP=0).
 */

import { fetchApi } from './networkFetch';

export interface BootstrapFast {
  tier: 'fast';
  generated_at: string;
  ttl_sec: number;
  briefing: {
    created_at?: string;
    style?: string;
    alert_count?: number;
    fusion_hotspot_count?: number;
    digest?: Record<string, unknown>;
    insights?: unknown[];
    watch_items?: unknown[];
    quality?: number;
    text_preview?: string;
    error?: string;
  };
  fusion_hotspots: {
    hotspots?: unknown[];
    summary?: Record<string, unknown>;
    error?: string;
  };
  feed_status: {
    feed_count?: number;
    feeds_fresh?: number;
    feeds_stale?: number;
    feeds_error?: number;
    error?: string;
  };
  situations: {
    count?: number;
    returned?: number;
    items?: unknown[];
    error?: string;
  };
  ais: {
    count?: number;
    positions?: unknown[];
    error?: string;
  };
  anomalies: string | { anomalies?: unknown[]; count?: number; error?: string };
}

export interface BootstrapSlow {
  tier: 'slow';
  generated_at: string;
  ttl_sec: number;
  ftm_stats: Record<string, unknown> | { error?: string };
  gdelt_pulse: {
    count?: number;
    articles?: unknown[];
    region?: string;
    error?: string;
  };
  cams: {
    count?: number;
    stations?: unknown[];
    error?: string;
  };
  earthquakes: {
    count?: number;
    earthquakes?: unknown[];
    error?: string;
  };
  darkweb_digest: string | Record<string, unknown>;
  ransomware_digest: string | Record<string, unknown>;
  prediction: string | Record<string, unknown>;
}

export async function fetchBootstrapFast(): Promise<BootstrapFast | null> {
  const r = await fetchApi('/api/bootstrap?tier=fast');
  if (!r.ok) return null;
  return r.json();
}

export async function fetchBootstrapSlow(): Promise<BootstrapSlow | null> {
  const r = await fetchApi('/api/bootstrap?tier=slow');
  if (!r.ok) return null;
  return r.json();
}

export async function fetchBootstrapBoth(): Promise<{
  fast: BootstrapFast | null;
  slow: BootstrapSlow | null;
}> {
  const [fast, slow] = await Promise.all([fetchBootstrapFast(), fetchBootstrapSlow()]);
  return { fast, slow };
}
