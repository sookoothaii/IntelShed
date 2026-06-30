import { fetchApi } from './networkFetch';

export interface DarkwebResult {
  title: string;
  url: string;
  snippet: string;
  engine: string;
  first_seen: string;
  query?: string;
  extracted_entities?: Record<string, string[]>;
}

export interface DarkwebSearchResponse {
  query: string;
  engines: string[];
  results: DarkwebResult[];
  count: number;
  sources: string[];
  tor_proxy: boolean;
  error?: string;
}

export interface DarkwebStatusResponse {
  enabled: boolean;
  engines: string[];
  modes: string[];
  max_results: number;
  cache_sec: number;
  timeout_sec: number;
  tor_proxy: string | null;
  engine_registry: Record<string, { tor_required: boolean; type: string }>;
}

export interface DarkwebEngineInfo {
  name: string;
  tor_required: boolean;
  type: string;
  url: string;
}

export interface DarkwebEntitiesResponse {
  query: string;
  engines: string[];
  sources: string[];
  count: number;
  matches: Array<{
    result: DarkwebResult;
    entity_ids: string[];
    matched_names: string[];
  }>;
  error?: string;
}

export interface DarkwebMention {
  id: string;
  schema: string;
  datasets: string[];
  properties: Record<string, string[]>;
}

export async function searchDarkweb(
  q: string,
  engines?: string,
  limit = 50,
  refresh = false,
  mode: 'auto' | 'clear' | 'tor' = 'auto',
): Promise<DarkwebSearchResponse> {
  const params = new URLSearchParams({ q, limit: String(limit), mode });
  if (engines) params.set('engines', engines);
  if (refresh) params.set('refresh', 'true');
  const r = await fetchApi(`/api/darkweb?${params.toString()}`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function getDarkwebStatus(): Promise<DarkwebStatusResponse> {
  const r = await fetchApi('/api/darkweb/status');
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function getDarkwebEngines(): Promise<{
  engines: DarkwebEngineInfo[];
  configured: string[];
  tor_proxy: string | null;
}> {
  const r = await fetchApi('/api/darkweb/engines');
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function searchDarkwebEntities(
  q: string,
  engines?: string,
  limit = 50,
  mode: 'auto' | 'clear' | 'tor' = 'auto',
): Promise<DarkwebEntitiesResponse> {
  const params = new URLSearchParams({ q, limit: String(limit), mode });
  if (engines) params.set('engines', engines);
  const r = await fetchApi(`/api/darkweb/entities?${params.toString()}`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function ingestDarkweb(
  q: string,
  engines?: string,
  limit = 50,
  mode: 'auto' | 'clear' | 'tor' = 'auto',
): Promise<{
  count: number;
  ids: string[];
  error?: string;
  query?: string;
  engines?: string[];
  sources?: string[];
  matched_count?: number;
  mode?: string;
}> {
  const r = await fetchApi('/api/darkweb/ingest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ q, engines: engines || '', limit, match_entities: true, mode }),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function getDarkwebMentions(limit = 50): Promise<{
  count: number;
  mentions: DarkwebMention[];
  error?: string;
}> {
  const r = await fetchApi(`/api/darkweb/mentions?limit=${limit}`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function getRansomwareGroups(): Promise<{
  count: number;
  groups: Array<{
    name: string;
    url: string;
    tor_url: string;
    description: string;
    source: string;
    active: boolean;
  }>;
  sources: string[];
  error?: string;
}> {
  const r = await fetchApi('/api/darkweb/ransomware/groups');
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function getRansomwareVictims(
  group?: string,
  limit = 50,
  refresh = false,
): Promise<{
  count: number;
  victims: Array<{
    victim: string;
    group: string;
    discovered?: string;
    published?: string;
    country?: string;
    activity?: string;
    description?: string;
    post_url?: string;
    website?: string;
    screenshot?: string;
    source: string;
  }>;
  sources: string[];
  error?: string;
}> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (group) params.set('group', group);
  if (refresh) params.set('refresh', 'true');
  const r = await fetchApi(`/api/darkweb/ransomware/victims?${params.toString()}`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function refreshRansomware(): Promise<{
  groups_count: number;
  victims_count: number;
  sources: string[];
  error?: string;
}> {
  const r = await fetchApi('/api/darkweb/ransomware/refresh', { method: 'POST' });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function ingestRansomwareVictims(
  group?: string,
  limit = 50,
): Promise<{
  count: number;
  ids: string[];
  error?: string;
  victims_fetched?: number;
  sources?: string[];
}> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (group) params.set('group', group);
  const r = await fetchApi(`/api/darkweb/ransomware/ingest?${params.toString()}`, {
    method: 'POST',
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function scrapeDarkwebUrl(
  url: string,
  extract = true,
): Promise<{
  url: string;
  ok: boolean;
  error?: string;
  text: string;
  entities: Record<string, string[]>;
}> {
  const r = await fetchApi('/api/darkweb/scrape', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url, extract }),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function deepSearchDarkweb(
  q: string,
  engines?: string,
  limit = 20,
  scrapeLimit = 3,
  mode: 'auto' | 'clear' | 'tor' = 'auto',
): Promise<{
  query: string;
  engines: string[];
  sources: string[];
  count: number;
  matches: Array<{
    result: DarkwebResult;
    scrape: {
      ok: boolean;
      error?: string;
      text: string;
      entities: Record<string, string[]>;
    };
    entity_ids: string[];
    matched_names: string[];
  }>;
  mode?: string;
  error?: string;
}> {
  const r = await fetchApi('/api/darkweb/deep_search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ q, engines: engines || '', limit, scrape_limit: scrapeLimit, mode }),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

// ---------------------------------------------------------------------------
// Breach / credential-leak intelligence (P8.8)
// ---------------------------------------------------------------------------

export interface BreachInfo {
  name: string;
  title: string;
  domain: string;
  breach_date: string;
  added_date: string;
  pwn_count: number;
  data_classes: string[];
  is_verified: boolean;
  is_fabricated: boolean;
  is_sensitive: boolean;
  is_retired: boolean;
  is_spam_list: boolean;
}

export interface BreachCheckResponse {
  email: string;
  breached: boolean;
  breaches: BreachInfo[];
  count: number;
  error?: string;
}

export interface BreachMonitor {
  id: number;
  email_hash: string;
  email_label: string;
  added_at: string;
  last_checked: string | null;
  last_breach_count: number;
  last_breach_names: string;
}

export interface BreachStatusResponse {
  enabled: boolean;
  briefing_enabled: boolean;
  hibp_key_configured: boolean;
  cache_sec: number;
  monitor_count: number;
  monitors: BreachMonitor[];
}

export async function getBreachStatus(): Promise<BreachStatusResponse> {
  const r = await fetchApi('/api/darkweb/breach/status');
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function checkEmailBreach(
  email: string,
  monitor = false,
  label?: string,
): Promise<BreachCheckResponse> {
  const r = await fetchApi('/api/darkweb/breach/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, monitor, label }),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function checkPasswordBreach(password: string): Promise<{
  compromised: boolean;
  count: number;
  error?: string;
}> {
  const r = await fetchApi('/api/darkweb/breach/password', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function addBreachMonitor(
  email: string,
  label?: string,
): Promise<{ ok: boolean; email_hash?: string; label?: string; error?: string }> {
  const r = await fetchApi('/api/darkweb/breach/monitor', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, label }),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function getBreachMonitors(): Promise<{
  monitors: BreachMonitor[];
  count: number;
}> {
  const r = await fetchApi('/api/darkweb/breach/monitors');
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function removeBreachMonitor(
  monitorId: number,
): Promise<{ ok: boolean; deleted?: number; error?: string }> {
  const r = await fetchApi(`/api/darkweb/breach/monitor/${monitorId}`, {
    method: 'DELETE',
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function refreshBreachMonitors(): Promise<{
  checked: number;
  new_breaches: number;
  results: Array<{
    email_hash: string;
    label: string;
    breach_count?: number;
    new_breaches?: string[];
    is_new?: boolean;
    skipped?: boolean;
    error?: string;
  }>;
}> {
  const r = await fetchApi('/api/darkweb/breach/refresh', { method: 'POST' });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}
