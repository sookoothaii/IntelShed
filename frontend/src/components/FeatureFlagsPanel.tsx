import { useCallback, useEffect, useState } from 'react'
import { fetchApi } from '../lib/networkFetch'

type Flag = {
  key: string
  enabled: boolean
  source: 'env' | 'sqlite'
  updated_at: string | null
  updated_by: string | null
}

type LogEntry = {
  id?: number
  key: string
  old_value: number | null
  new_value: number
  updated_by: string
  at: string
}

export default function FeatureFlagsPanel() {
  const [flags, setFlags] = useState<Flag[]>([])
  const [log, setLog] = useState<LogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showLog, setShowLog] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)

  const loadFlags = useCallback(async () => {
    try {
      setError(null)
      const res = await fetchApi('/api/admin/flags')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setFlags(data.flags || [])
    } catch (e: any) {
      setError(e.message || 'Failed to load flags')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadLog = useCallback(async () => {
    try {
      const res = await fetchApi('/api/admin/flags/log?limit=50')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setLog(data.entries || [])
    } catch (e: any) {
      setError(e.message || 'Failed to load log')
    }
  }, [])

  useEffect(() => {
    loadFlags()
  }, [loadFlags])

  const toggleFlag = useCallback(
    async (key: string, enabled: boolean) => {
      setBusy(key)
      try {
        const res = await fetchApi(`/api/admin/flags/${key}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled, updated_by: 'hud' }),
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        await loadFlags()
      } catch (e: any) {
        setError(e.message || `Failed to toggle ${key}`)
      } finally {
        setBusy(null)
      }
    },
    [loadFlags],
  )

  if (loading) {
    return <div className="flags-panel"><p style={{ color: '#888' }}>Loading flags…</p></div>
  }

  return (
    <div className="flags-panel" style={{ padding: '12px 16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
        <h2 style={{ margin: 0, fontSize: '1.1rem' }}>Feature Flags</h2>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            className="hud-btn"
            onClick={() => { loadFlags(); if (showLog) loadLog() }}
            style={{ fontSize: '0.8rem', padding: '4px 10px' }}
          >
            ↻ Refresh
          </button>
          <button
            className="hud-btn"
            onClick={() => {
              if (!showLog) loadLog()
              setShowLog(!showLog)
            }}
            style={{ fontSize: '0.8rem', padding: '4px 10px' }}
          >
            {showLog ? 'Flags' : 'Audit Log'}
          </button>
        </div>
      </div>

      {error && (
        <div className="data-error" style={{ marginBottom: '8px' }}>{error}</div>
      )}

      {showLog ? (
        <div className="flags-log" style={{ maxHeight: '60vh', overflowY: 'auto' }}>
          {log.length === 0 ? (
            <p style={{ color: '#888' }}>No audit entries yet.</p>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
              <thead>
                <tr style={{ textAlign: 'left', color: '#888', borderBottom: '1px solid #333' }}>
                  <th style={{ padding: '4px 8px' }}>Flag</th>
                  <th style={{ padding: '4px 8px' }}>Old</th>
                  <th style={{ padding: '4px 8px' }}>New</th>
                  <th style={{ padding: '4px 8px' }}>By</th>
                  <th style={{ padding: '4px 8px' }}>Time</th>
                </tr>
              </thead>
              <tbody>
                {log.map((entry, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid #222' }}>
                    <td style={{ padding: '4px 8px', fontFamily: 'monospace' }}>{entry.key}</td>
                    <td style={{ padding: '4px 8px' }}>
                      {entry.old_value === null ? '—' : entry.old_value ? '✓' : '✗'}
                    </td>
                    <td style={{ padding: '4px 8px' }}>{entry.new_value ? '✓' : '✗'}</td>
                    <td style={{ padding: '4px 8px', color: '#888' }}>{entry.updated_by}</td>
                    <td style={{ padding: '4px 8px', color: '#888', fontSize: '0.75rem' }}>
                      {new Date(entry.at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : (
        <div className="flags-list" style={{ maxHeight: '60vh', overflowY: 'auto' }}>
          {flags.length === 0 ? (
            <p style={{ color: '#888' }}>No flags registered.</p>
          ) : (
            flags.map((flag) => (
              <div
                key={flag.key}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '8px 0',
                  borderBottom: '1px solid #222',
                }}
              >
                <div>
                  <span style={{ fontFamily: 'monospace', fontSize: '0.85rem' }}>
                    {flag.key}
                  </span>
                  <span
                    style={{
                      marginLeft: '8px',
                      fontSize: '0.7rem',
                      color: flag.source === 'sqlite' ? '#00e5a0' : '#888',
                      border: '1px solid #333',
                      borderRadius: '3px',
                      padding: '1px 4px',
                    }}
                  >
                    {flag.source}
                  </span>
                  {flag.updated_at && (
                    <span style={{ marginLeft: '8px', fontSize: '0.7rem', color: '#666' }}>
                      {new Date(flag.updated_at).toLocaleString()}
                    </span>
                  )}
                </div>
                <button
                  onClick={() => toggleFlag(flag.key, !flag.enabled)}
                  disabled={busy === flag.key}
                  style={{
                    minWidth: '48px',
                    padding: '4px 12px',
                    fontSize: '0.8rem',
                    cursor: busy === flag.key ? 'wait' : 'pointer',
                    background: flag.enabled ? '#0a3' : '#333',
                    color: flag.enabled ? '#fff' : '#888',
                    border: '1px solid ' + (flag.enabled ? '#0a3' : '#444'),
                    borderRadius: '4px',
                    opacity: busy === flag.key ? 0.5 : 1,
                  }}
                >
                  {busy === flag.key ? '…' : flag.enabled ? 'ON' : 'OFF'}
                </button>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
