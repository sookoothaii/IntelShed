import { fetchApi } from './networkFetch';

export interface TelegramChannel {
  channel: string;
  allowlisted: boolean;
  cached_posts: number;
  last_post?: string;
}

export interface TelegramChannelsResponse {
  enabled: boolean;
  channels: TelegramChannel[];
  error?: string;
}

export interface TelegramPost {
  id: string;
  channel: string;
  channel_title: string;
  channel_url: string;
  message_id: number;
  url: string;
  text: string;
  date: string;
  views: number;
  forwards: number;
  replies: number;
  media_type?: string;
  urls: string[];
  hashtags: string[];
  mentions: string[];
  countries: string[];
  cities: string[];
  keywords: string[];
  score: number;
  ingested: boolean;
}

export interface TelegramPostsResponse {
  enabled: boolean;
  count: number;
  total_cached: number;
  last_scan?: string;
  posts: TelegramPost[];
  error?: string;
}

export interface TelegramRefreshResponse {
  enabled: boolean;
  count: number;
  channels: Array<{ channel: string; ok: boolean; count: number }>;
  error?: string;
}

export interface TelegramIngestResponse {
  enabled: boolean;
  count: number;
  ids: string[];
  error?: string;
}

export async function getTelegramChannels(): Promise<TelegramChannelsResponse> {
  const r = await fetchApi('/api/telegram/channels');
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function getTelegramPosts(
  channel?: string,
  limit = 100,
  minScore?: number,
): Promise<TelegramPostsResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (channel) params.set('channel', channel);
  if (minScore !== undefined) params.set('min_score', String(minScore));
  const r = await fetchApi(`/api/telegram/posts?${params.toString()}`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function refreshTelegram(): Promise<TelegramRefreshResponse> {
  const r = await fetchApi('/api/telegram/refresh', { method: 'POST' });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export async function ingestTelegram(
  postIds?: string[],
  allCached = false,
): Promise<TelegramIngestResponse> {
  const r = await fetchApi('/api/telegram/ingest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ post_ids: postIds || [], all_cached: allCached }),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}
