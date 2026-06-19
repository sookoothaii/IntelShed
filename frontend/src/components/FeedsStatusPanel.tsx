import { useCallback, useEffect, useState } from 'react'
import { fetchApi } from '../lib/networkFetch'

type FeedRow = {
  key: string
  status?: string
  fresh?: boolean
  age_sec?: number
  count?: number | null
  source?: string | string[] | null
  error?: string | null
}

type ProviderRow = {
  id: string
  name: string
  category: string
  tier: string
  configured: boolean
  feeds?: string[]
}

type ConnectorRow = {
  id: string
  name: string
  category: string
  endpoints: string[]
  ttl_sec: number
  license: string
  region: string[]
  credential_ids: string[]
  globe_layer?: string | null
  tier?: string
  credentials_mode?: 'none' | 'ok' | 'fallback' | 'key'
  credentials_ready?: boolean
  cache?: { cache_key?: string; count?: number | null } | null
}

function statusColor(status?: string, fresh?: boolean): string {
  if (status === 'error') return '#ff4d5e'
  if (fresh === false || status === 'stale' || status === 'warn') return '#ffd23f'
  return '#00e5a0'
}

function credColor(mode?: string): string {
  if (!mode || mode === 'none') return '#8fb7a9'
  if (mode === 'ok') return '#00e5a0'
  if (mode === 'fallback') return '#ffd23f'
  return '#ff6b35'
}

function credLabel(mode?: string): string {
  if (!mode || mode === 'none') return '—'
  if (mode === 'ok') return 'OK'
  if (mode === 'fallback') return 'FB'
  return 'KEY'
}

export default function FeedsStatusPanel() {
  const [health, setHealth] = useState<any>(null)
  const [credentials, setCredentials] = useState<any>(null)
  const [connectors, setConnectors] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [hRes, cRes, connRes] = await Promise.all([
        fetchApi('/api/health'),
        fetchApi('/api/credentials/status'),
        fetchApi('/api/connectors?include_unlisted=0'),
      ])
      if (!hRes.ok) throw new Error(`health ${hRes.status}`)
      if (!cRes.ok) throw new Error(`credentials ${cRes.status}`)
      if (!connRes.ok) throw new Error(`connectors ${connRes.status}`)
      setHealth(await hRes.json())
      setCredentials(await cRes.json())
      setConnectors(await connRes.json())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const feeds: FeedRow[] = health?.feeds
    ? Object.entries(health.feeds).map(([key, val]: [string, any]) => ({ key, ...val }))
    : []
  feeds.sort((a, b) => {
    const rank = (f: FeedRow) => (f.fresh === false || f.status === 'stale' ? 0 : f.status === 'warn' ? 1 : 2)
    return rank(a) - rank(b) || a.key.localeCompare(b.key)
  })

  const providers: ProviderRow[] = credentials?.providers || []
  const connectorRows: ConnectorRow[] = connectors?.connectors || []

  return (
    <section>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
        <button onClick={load} disabled={loading}>{loading ? 'Loading…' : '↻ REFRESH'}</button>
        {health && (
          <span className="data-count">
            {health.feeds_fresh ?? 0} fresh · {health.feeds_stale ?? 0} stale · FTM {health.ftm?.ready ? 'ready' : 'off'}
            {connectors?.count != null && ` · ${connectors.count} connectors`}
          </span>
        )}
      </div>
      {error && <div className="data-error">{error}</div>}

      {health && (
        <div className="iss-grid" style={{ marginBottom: 12 }}>
          <div className="iss-card"><span>API</span><strong style={{ color: '#00e5a0' }}>{health.status?.toUpperCase()}</strong></div>
          <div className="iss-card"><span>FEEDS</span><strong>{health.feed_count ?? '—'}</strong></div>
          <div className="iss-card"><span>ENTITIES</span><strong>{health.ftm?.entities ?? '—'}</strong></div>
          <div className="iss-card"><span>KEYS</span><strong>{credentials?.configured ?? '—'}/{credentials?.count ?? '—'}</strong></div>
        </div>
      )}

      {connectorRows.length > 0 && (
        <>
          <h4 style={{ letterSpacing: 2, fontSize: 12, color: '#8fb7a9' }}>CONNECTOR REGISTRY</h4>
          <table className="data-table" style={{ marginBottom: 16 }}>
            <thead>
              <tr>
                <th>ID</th>
                <th>Category</th>
                <th>Region</th>
                <th>TTL (s)</th>
                <th>Globe</th>
                <th>Creds</th>
                <th>Cache</th>
              </tr>
            </thead>
            <tbody>
              {connectorRows.map((c) => (
                <tr key={c.id}>
                  <td>
                    <strong>{c.id}</strong>
                    <br />
                    <small style={{ color: '#6f8c84' }}>{c.name}</small>
                  </td>
                  <td>{c.category}</td>
                  <td style={{ fontSize: 10 }}>{(c.region || []).join(', ')}</td>
                  <td>{Math.round(c.ttl_sec)}</td>
                  <td>{c.globe_layer || '—'}</td>
                  <td style={{ color: credColor(c.credentials_mode), fontWeight: 'bold' }} title={c.credentials_mode === 'fallback' ? 'Optional key missing; bridge fallback active' : undefined}>
                    {credLabel(c.credentials_mode)}
                  </td>
                  <td>{c.cache?.count ?? (c.cache?.cache_key ? '·' : '—')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}

      <h4 style={{ letterSpacing: 2, fontSize: 12, color: '#8fb7a9' }}>FEED CACHE</h4>
      <table className="data-table">
        <thead><tr><th>Feed</th><th>Status</th><th>Age (s)</th><th>Count</th><th>Source</th></tr></thead>
        <tbody>
          {feeds.map((f) => (
            <tr key={f.key}>
              <td>{f.key}</td>
              <td style={{ color: statusColor(f.status, f.fresh), fontWeight: 'bold' }}>{f.status ?? (f.fresh ? 'fresh' : 'stale')}</td>
              <td>{f.age_sec != null ? Math.round(f.age_sec) : '—'}</td>
              <td>{f.count ?? '—'}</td>
              <td>{Array.isArray(f.source) ? f.source.join(', ') : (f.source || '—')}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h4 style={{ letterSpacing: 2, fontSize: 12, color: '#8fb7a9', marginTop: 16 }}>PROVIDER KEYS</h4>
      <table className="data-table">
        <thead><tr><th>Provider</th><th>Category</th><th>Tier</th><th>Configured</th><th>Feeds</th></tr></thead>
        <tbody>
          {providers.map((p) => (
            <tr key={p.id}>
              <td><strong>{p.name}</strong><br /><small style={{ color: '#6f8c84' }}>{p.id}</small></td>
              <td>{p.category}</td>
              <td>{p.tier}</td>
              <td style={{ color: p.configured ? '#00e5a0' : '#ff6b35', fontWeight: 'bold' }}>{p.configured ? 'YES' : 'NO'}</td>
              <td style={{ fontSize: 10, color: '#6f8c84' }}>{(p.feeds || []).slice(0, 3).join(', ')}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
