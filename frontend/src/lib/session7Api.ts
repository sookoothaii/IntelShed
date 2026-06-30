/** Session 7 — API functions for Relationship Explorer, Entity Timeline, Credential Manager. */

import { fetchApi } from './networkFetch';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type TimelineEvent = {
  type: string;
  timestamp: string;
  detail?: string;
  prop?: string;
  value?: string;
  dataset?: string;
  lang?: string | null;
  kind?: string;
  direction?: string;
  other_id?: string;
  confidence?: number | null;
  source_ref?: string | null;
};

export type EntityTimelineData = {
  entity_id: string;
  found: boolean;
  schema?: string;
  caption?: string;
  first_seen?: string | null;
  last_seen?: string | null;
  event_count: number;
  events: TimelineEvent[];
  error?: string;
};

export type StoredCredential = {
  env_var: string;
  masked: string;
  has_value: boolean;
};

export type CredentialsListResponse = {
  credentials: StoredCredential[];
};

export type CredentialSetResult = {
  env_var: string;
  set: boolean;
  error?: string;
};

export type CredentialDeleteResult = {
  env_var: string;
  deleted: boolean;
};

// ---------------------------------------------------------------------------
// Entity Timeline
// ---------------------------------------------------------------------------

export async function getEntityTimeline(
  entityId: string,
): Promise<EntityTimelineData> {
  const r = await fetchApi(
    `/api/intel/entities/${encodeURIComponent(entityId)}/timeline`,
  );
  return r.json();
}

// ---------------------------------------------------------------------------
// Credential Manager
// ---------------------------------------------------------------------------

export async function listCredentials(): Promise<CredentialsListResponse> {
  const r = await fetchApi('/api/credentials');
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function setCredential(
  envVar: string,
  value: string,
): Promise<CredentialSetResult> {
  const r = await fetchApi('/api/credentials', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ env_var: envVar, value }),
  });
  return r.json();
}

export async function deleteCredential(
  envVar: string,
): Promise<CredentialDeleteResult> {
  const r = await fetchApi(
    `/api/credentials/${encodeURIComponent(envVar)}`,
    { method: 'DELETE' },
  );
  return r.json();
}
