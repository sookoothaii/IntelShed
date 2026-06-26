import { useState, useEffect, useCallback } from 'react'
import {
  getTelegramChannels,
  getTelegramPosts,
  refreshTelegram,
  ingestTelegram,
  type TelegramChannel,
  type TelegramPost,
} from '../lib/telegramApi'

export default function TelegramPanel() {
  const [channels, setChannels] = useState<TelegramChannel[]>([])
  const [posts, setPosts] = useState<TelegramPost[]>([])
  const [enabled, setEnabled] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedChannel, setSelectedChannel] = useState<string>('')
  const [minScore, setMinScore] = useState<number | ''>('')
  const [selectedPosts, setSelectedPosts] = useState<Set<string>>(new Set())
  const [lastScan, setLastScan] = useState<string | null>(null)
  const [totalCached, setTotalCached] = useState(0)

  const loadChannels = useCallback(async () => {
    try {
      const data = await getTelegramChannels()
      setEnabled(data.enabled)
      setChannels(data.channels || [])
    } catch {
      setEnabled(false)
      setChannels([])
    }
  }, [])

  const loadPosts = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getTelegramPosts(
        selectedChannel || undefined,
        100,
        minScore === '' ? undefined : Number(minScore)
      )
      setEnabled(data.enabled)
      setPosts(data.posts || [])
      setLastScan(data.last_scan || null)
      setTotalCached(data.total_cached || 0)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [selectedChannel, minScore])

  useEffect(() => {
    loadChannels()
  }, [loadChannels])

  useEffect(() => {
    loadPosts()
  }, [loadPosts])

  const handleRefresh = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await refreshTelegram()
      setEnabled(data.enabled)
      if (data.error) {
        setError(data.error)
      } else {
        await loadChannels()
        await loadPosts()
      }
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const handleIngest = async (all = false) => {
    setLoading(true)
    setError(null)
    try {
      const ids = all ? undefined : Array.from(selectedPosts)
      await ingestTelegram(ids, all)
      setSelectedPosts(new Set())
      await loadPosts()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const togglePost = (id: string) => {
    setSelectedPosts((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const tagStyle = (color: string) => ({
    padding: '2px 6px',
    borderRadius: 4,
    fontSize: 11,
    background: color + '22',
    color,
    marginRight: 4,
    marginBottom: 4,
    display: 'inline-block',
  })

  return (
    <div style={{ padding: 12, height: '100%', overflow: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <h2 style={{ margin: 0, fontSize: 16, color: '#00e5a0' }}>TELEGRAM SOCMINT</h2>
        <span
          style={{
            padding: '2px 6px',
            borderRadius: 4,
            fontSize: 11,
            background: enabled ? '#00e5a022' : '#ff4d5e22',
            color: enabled ? '#00e5a0' : '#ff4d5e',
          }}
        >
          {enabled ? 'enabled' : 'disabled'}
        </span>
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
        <select
          value={selectedChannel}
          onChange={(e) => setSelectedChannel(e.target.value)}
          style={{ padding: 4, background: '#0b1d1d', color: '#b0c4bf', border: '1px solid #1e3a3a' }}
        >
          <option value="">All channels</option>
          {channels.map((c) => (
            <option key={c.channel} value={c.channel}>
              @{c.channel} ({c.cached_posts})
            </option>
          ))}
        </select>
        <input
          type="number"
          min={0}
          max={1}
          step={0.1}
          value={minScore}
          onChange={(e) => setMinScore(e.target.value === '' ? '' : Number(e.target.value))}
          placeholder="min score"
          style={{ padding: 4, width: 80, background: '#0b1d1d', color: '#b0c4bf', border: '1px solid #1e3a3a' }}
        />
        <button onClick={handleRefresh} disabled={loading} style={{ padding: '4px 10px' }}>
          Refresh
        </button>
        <button
          onClick={() => handleIngest(false)}
          disabled={loading || selectedPosts.size === 0}
          style={{ padding: '4px 10px' }}
        >
          Ingest selected ({selectedPosts.size})
        </button>
        <button onClick={() => handleIngest(true)} disabled={loading} style={{ padding: '4px 10px' }}>
          Ingest all cached
        </button>
      </div>

      <div style={{ fontSize: 12, color: '#6f8c84', marginBottom: 8 }}>
        {lastScan && <span>Last scan: {new Date(lastScan).toLocaleString()} · </span>}
        <span>Total cached: {totalCached}</span>
      </div>

      {error && (
        <div style={{ padding: 8, marginBottom: 12, border: '1px solid #ff4d5e', color: '#ff4d5e', borderRadius: 4 }}>
          {error}
        </div>
      )}

      {loading && <div style={{ color: '#6f8c84' }}>Loading Telegram posts…</div>}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {posts.map((p) => (
          <div
            key={p.id}
            style={{
              border: '1px solid #1e3a3a',
              borderRadius: 6,
              padding: 10,
              background: selectedPosts.has(p.id) ? '#00e5a011' : '#0b1d1d',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <input
                type="checkbox"
                checked={selectedPosts.has(p.id)}
                onChange={() => togglePost(p.id)}
              />
              <a
                href={p.url}
                target="_blank"
                rel="noreferrer"
                style={{ color: '#00e5a0', fontSize: 13, fontWeight: 600 }}
              >
                @{p.channel}
              </a>
              <span style={{ color: '#6f8c84', fontSize: 11 }}>
                {new Date(p.date).toLocaleString()}
              </span>
              <span style={tagStyle('#00e5a0')}>score {p.score}</span>
              {p.ingested && <span style={tagStyle('#6f8c84')}>ingested</span>}
            </div>
            <div style={{ color: '#b0c4bf', fontSize: 13, whiteSpace: 'pre-wrap', marginBottom: 6 }}>
              {p.text}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
              {p.countries.map((c) => (
                <span key={c} style={tagStyle('#ffd23f')}>{c}</span>
              ))}
              {p.cities.map((c) => (
                <span key={c} style={tagStyle('#22d3ee')}>{c}</span>
              ))}
              {p.keywords.map((k) => (
                <span key={k} style={tagStyle('#ff8c42')}>{k}</span>
              ))}
              {p.hashtags.slice(0, 5).map((h) => (
                <span key={h} style={tagStyle('#7ed957')}>{h}</span>
              ))}
            </div>
            <div style={{ fontSize: 11, color: '#6f8c84', marginTop: 4 }}>
              views {p.views.toLocaleString()} · forwards {p.forwards} · replies {p.replies}
              {p.media_type && ` · media ${p.media_type}`}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
