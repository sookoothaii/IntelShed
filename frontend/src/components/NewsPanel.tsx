import { useCallback, useEffect, useMemo, useState } from 'react'
import { fetchApi } from '../lib/networkFetch'

type NewsSource = 'newsdata' | 'gdelt-local' | 'gdelt-global'

type NewsItem = {
  id: string
  source: NewsSource
  title: string
  snippet: string
  url: string | null
  publishedAt: number | null
  meta: string
  stale: boolean
}

type SourceState = {
  configured: boolean
  count: number
  error: string | null
  stale: boolean
}

type Filter = 'all' | 'local' | 'global' | 'newsdata' | 'gdelt'

const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'ALL' },
  { id: 'local', label: 'LOCAL' },
  { id: 'global', label: 'GLOBAL' },
  { id: 'newsdata', label: 'NEWSDATA' },
  { id: 'gdelt', label: 'GDELT' },
]

const SOURCE_BADGE: Record<NewsSource, { label: string; cls: string }> = {
  newsdata: { label: 'NEWSDATA', cls: 'newsdata' },
  'gdelt-local': { label: 'GDELT LOCAL', cls: 'gdelt-local' },
  'gdelt-global': { label: 'GDELT GLOBAL', cls: 'gdelt-global' },
}

const REFRESH_MS = 60000

function parseDate(raw: unknown): number | null {
  if (!raw || typeof raw !== 'string') return null
  // GDELT seendate: YYYYMMDDTHHMMSSZ
  const gdelt = raw.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/)
  if (gdelt) {
    const [, y, mo, d, h, mi, s] = gdelt
    const t = Date.parse(`${y}-${mo}-${d}T${h}:${mi}:${s}Z`)
    return Number.isNaN(t) ? null : t
  }
  const t = Date.parse(raw)
  return Number.isNaN(t) ? null : t
}

function relTime(ts: number | null): string {
  if (ts == null) return '—'
  const diff = Date.now() - ts
  if (diff < 0) return 'just now'
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

function mapNewsData(d: any): { items: NewsItem[]; state: SourceState } {
  const configured = d?.configured !== false
  const articles: any[] = Array.isArray(d?.articles) ? d.articles : []
  const items = articles.map((a, i): NewsItem => {
    const country = Array.isArray(a.country) ? a.country.join(',').toUpperCase() : ''
    const cat = Array.isArray(a.category) ? a.category[0] : ''
    const meta = [country, cat].filter(Boolean).join(' · ') || (a.source_id ?? 'newsdata')
    return {
      id: `nd:${a.link ?? i}`,
      source: 'newsdata',
      title: (a.title ?? '').trim(),
      snippet: (a.description ?? '').trim(),
      url: a.link ?? null,
      publishedAt: parseDate(a.pubDate),
      meta,
      stale: Boolean(d?.stale),
    }
  })
  return {
    items,
    state: {
      configured,
      count: items.length,
      error: d?.error ?? null,
      stale: Boolean(d?.stale),
    },
  }
}

function mapGdelt(d: any, source: NewsSource): { items: NewsItem[]; state: SourceState } {
  const articles: any[] = Array.isArray(d?.articles) ? d.articles : []
  const region = d?.region ? String(d.region) : ''
  const items = articles.map((a, i): NewsItem => {
    const origin = a.domain || a.sourcecountry || region || 'gdelt'
    const meta = source === 'gdelt-local' && region ? `${region} · ${origin}` : String(origin)
    return {
      id: `${source}:${a.url ?? i}`,
      source,
      title: (a.title ?? '').trim(),
      snippet: '',
      url: a.url ?? null,
      publishedAt: parseDate(a.seendate),
      meta,
      stale: Boolean(d?.stale),
    }
  })
  return {
    items,
    state: {
      configured: true,
      count: items.length,
      error: d?.error ?? null,
      stale: Boolean(d?.stale),
    },
  }
}

export default function NewsPanel() {
  const [items, setItems] = useState<NewsItem[]>([])
  const [states, setStates] = useState<Record<NewsSource, SourceState | null>>({
    newsdata: null,
    'gdelt-local': null,
    'gdelt-global': null,
  })
  const [filter, setFilter] = useState<Filter>('all')
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    const grab = async (url: string) => {
      try {
        const r = await fetchApi(url)
        if (!r.ok) return { error: `HTTP ${r.status}` }
        return await r.json()
      } catch (e) {
        return { error: (e as Error).message }
      }
    }
    const [nd, gl, gg] = await Promise.all([
      grab('/api/newsdata?limit=30'),
      grab('/api/gdelt/pulse/local'),
      grab('/api/gdelt/pulse'),
    ])
    const ndRes = mapNewsData(nd)
    const glRes = mapGdelt(gl, 'gdelt-local')
    const ggRes = mapGdelt(gg, 'gdelt-global')

    const merged = [...ndRes.items, ...glRes.items, ...ggRes.items].filter((x) => x.title)
    merged.sort((a, b) => (b.publishedAt ?? 0) - (a.publishedAt ?? 0))

    setItems(merged)
    setStates({
      newsdata: ndRes.state,
      'gdelt-local': glRes.state,
      'gdelt-global': ggRes.state,
    })
    setLoading(false)
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, REFRESH_MS)
    return () => clearInterval(t)
  }, [load])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return items.filter((it) => {
      if (filter === 'local' && it.source !== 'gdelt-local') return false
      if (filter === 'global' && it.source !== 'gdelt-global') return false
      if (filter === 'newsdata' && it.source !== 'newsdata') return false
      if (filter === 'gdelt' && !it.source.startsWith('gdelt')) return false
      if (q && !it.title.toLowerCase().includes(q) && !it.snippet.toLowerCase().includes(q)) {
        return false
      }
      return true
    })
  }, [items, filter, query])

  const sourceCount = useMemo(
    () => Object.values(states).filter((s) => s && s.count > 0).length,
    [states],
  )

  const newsdataState = states.newsdata
  const showConfigBanner = newsdataState != null && !newsdataState.configured

  return (
    <div className="panel">
      <h2>NEWS <span className="news-sub">· GLOBAL HEADLINE FEED</span></h2>

      <div className="news-tabs data-tabs">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            className={filter === f.id ? 'active' : ''}
            onClick={() => setFilter(f.id)}
          >
            {f.label}
          </button>
        ))}
      </div>

      <div className="news-toolbar">
        <input
          className="data-search"
          placeholder="Filter headlines…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button className="data-refresh" onClick={load} disabled={loading}>
          {loading ? 'LOADING…' : '↻ REFRESH'}
        </button>
      </div>

      <div className="data-count">
        {visible.length} items · {sourceCount} sources · auto 60s
        <span className="news-plan"> · NewsData free plan ~12h delay</span>
      </div>

      {showConfigBanner && (
        <div className="news-config-banner">
          NEWSDATA_API_KEY not set — showing GDELT only. Add the key in backend/.env for NewsData headlines.
        </div>
      )}

      {newsdataState?.error && newsdataState.configured && (
        <div className="data-error">NewsData: {newsdataState.error}</div>
      )}

      {!visible.length && !loading && (
        <div className="health-status pending">No headlines available</div>
      )}

      <div className="news-list">
        {visible.map((it) => {
          const badge = SOURCE_BADGE[it.source]
          return (
            <article key={it.id} className={`news-card news-card--${badge.cls}`}>
              <div className="news-head">
                <span className={`news-badge news-badge--${badge.cls}`}>{badge.label}</span>
                <span className="news-meta">{it.meta}</span>
                <span className={`news-time${it.stale ? ' news-time--stale' : ''}`}>
                  {it.stale ? 'stale cache' : relTime(it.publishedAt)}
                </span>
              </div>
              <p className="news-title">{it.title}</p>
              {it.snippet && <p className="news-snippet">{it.snippet}</p>}
              {it.url && (
                <a className="tp-link" href={it.url} target="_blank" rel="noreferrer">
                  OPEN ARTICLE ↗
                </a>
              )}
            </article>
          )
        })}
      </div>
    </div>
  )
}
