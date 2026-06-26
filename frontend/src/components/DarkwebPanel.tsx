import { useState, useEffect, useCallback } from 'react'
import {
  searchDarkweb,
  searchDarkwebEntities,
  ingestDarkweb,
  getDarkwebStatus,
  getDarkwebEngines,
  getDarkwebMentions,
  getRansomwareGroups,
  getRansomwareVictims,
  refreshRansomware,
  ingestRansomwareVictims,
  type DarkwebResult,
  type DarkwebEngineInfo,
  type DarkwebMention,
} from '../lib/darkwebApi'

export default function DarkwebPanel() {
  const [query, setQuery] = useState('')
  const [engines, setEngines] = useState('')
  const [mode, setMode] = useState<'auto' | 'clear' | 'tor'>('auto')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<DarkwebResult[]>([])
  const [matches, setMatches] = useState<Array<{
    result: DarkwebResult
    entity_ids: string[]
    matched_names: string[]
  }>>([])
  const [mentions, setMentions] = useState<DarkwebMention[]>([])
  const [status, setStatus] = useState<{ enabled: boolean; engines: string[]; modes?: string[]; tor_proxy: string | null } | null>(null)
  const [engineList, setEngineList] = useState<DarkwebEngineInfo[]>([])
  const [activeTab, setActiveTab] = useState<'search' | 'mentions' | 'ransomware'>('search')
  const [ransomwareGroups, setRansomwareGroups] = useState<Array<{ name: string; url: string; tor_url: string; description: string; source: string; active: boolean }>>([])
  const [selectedRansomwareGroup, setSelectedRansomwareGroup] = useState('')
  const [ransomwareVictims, setRansomwareVictims] = useState<Array<{ victim: string; group: string; discovered?: string; published?: string; country?: string; activity?: string; description?: string; post_url?: string; website?: string; screenshot?: string; source: string }>>([])
  const [ransomwareLoading, setRansomwareLoading] = useState(false)

  const loadStatus = useCallback(async () => {
    try {
      const [s, e] = await Promise.all([getDarkwebStatus(), getDarkwebEngines()])
      setStatus(s)
      setEngines(s.engines.join(','))
      setEngineList(e.engines)
    } catch {
      setStatus({ enabled: false, engines: [], tor_proxy: null })
    }
  }, [])

  useEffect(() => {
    loadStatus()
  }, [loadStatus])

  const loadMentions = useCallback(async () => {
    try {
      const data = await getDarkwebMentions(50)
      setMentions(data.mentions || [])
    } catch {
      // ignore
    }
  }, [])

  useEffect(() => {
    if (activeTab === 'mentions') loadMentions()
  }, [activeTab, loadMentions])

  const loadRansomwareGroups = useCallback(async () => {
    try {
      setRansomwareLoading(true)
      const data = await getRansomwareGroups()
      setRansomwareGroups(data.groups || [])
    } catch {
      setRansomwareGroups([])
    } finally {
      setRansomwareLoading(false)
    }
  }, [])

  const loadRansomwareVictims = async (groupId: string) => {
    if (!groupId) return
    setRansomwareLoading(true)
    setError(null)
    try {
      const data = await getRansomwareVictims(groupId, 50)
      setRansomwareVictims(data.victims || [])
    } catch (e) {
      setError((e as Error).message)
      setRansomwareVictims([])
    } finally {
      setRansomwareLoading(false)
    }
  }

  const handleRefreshRansomware = async () => {
    setRansomwareLoading(true)
    setError(null)
    try {
      await refreshRansomware()
      await loadRansomwareGroups()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRansomwareLoading(false)
    }
  }

  const handleIngestRansomware = async () => {
    if (!selectedRansomwareGroup) return
    setRansomwareLoading(true)
    setError(null)
    try {
      await ingestRansomwareVictims(selectedRansomwareGroup, 50)
      await loadMentions()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRansomwareLoading(false)
    }
  }

  useEffect(() => {
    if (activeTab === 'ransomware') loadRansomwareGroups()
  }, [activeTab, loadRansomwareGroups])

  useEffect(() => {
    if (selectedRansomwareGroup) {
      loadRansomwareVictims(selectedRansomwareGroup)
    }
  }, [selectedRansomwareGroup])

  const handleSearch = async () => {
    if (!query.trim()) return
    setLoading(true)
    setError(null)
    try {
      const [searchData, entityData] = await Promise.all([
        searchDarkweb(query.trim(), engines, 50, false, mode),
        searchDarkwebEntities(query.trim(), engines, 50, mode),
      ])
      setResults(searchData.results || [])
      setMatches(entityData.matches || [])
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const handleIngest = async (q?: string) => {
    const target = (q || query).trim()
    if (!target) return
    setLoading(true)
    setError(null)
    try {
      await ingestDarkweb(target, engines, 50, mode)
      await loadMentions()
      setActiveTab('mentions')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const renderEngineBadges = () => (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
      {engineList.map((e) => {
        const configured = status?.engines.includes(e.name)
        return (
          <span
            key={e.name}
            title={`${e.url} ${e.tor_required ? '(requires Tor proxy)' : ''}`}
            style={{
              padding: '2px 6px',
              borderRadius: 4,
              fontSize: 11,
              border: `1px solid ${configured ? '#00e5a0' : '#6f8c84'}`,
              color: configured ? '#00e5a0' : '#b0c4bf',
              opacity: e.tor_required ? 0.8 : 1,
            }}
          >
            {e.name}
            {e.tor_required && ' ⚡'}
          </span>
        )
      })}
    </div>
  )

  return (
    <div style={{ padding: 12, height: '100%', overflow: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <h2 style={{ margin: 0, fontSize: 16, color: '#00e5a0' }}>DARK WEB / DARKNET</h2>
        <span
          style={{
            padding: '2px 6px',
            borderRadius: 4,
            fontSize: 11,
            background: status?.enabled ? '#00e5a022' : '#ff4d5e22',
            color: status?.enabled ? '#00e5a0' : '#ff4d5e',
          }}
        >
          {status?.enabled ? 'ENABLED' : 'DISABLED'}
        </span>
        {status?.tor_proxy && (
          <span style={{ fontSize: 11, color: '#ffd23f' }}>Tor: {status.tor_proxy}</span>
        )}
      </div>

      {renderEngineBadges()}

      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <button
          className={activeTab === 'search' ? 'hud-button active' : 'hud-button'}
          onClick={() => setActiveTab('search')}
        >
          SEARCH
        </button>
        <button
          className={activeTab === 'mentions' ? 'hud-button active' : 'hud-button'}
          onClick={() => setActiveTab('mentions')}
        >
          MENTIONS ({mentions.length})
        </button>
        <button
          className={activeTab === 'ransomware' ? 'hud-button active' : 'hud-button'}
          onClick={() => setActiveTab('ransomware')}
        >
          RANSOMWARE
        </button>
      </div>

      {activeTab === 'search' && (
        <>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            <input
              className="hud-input"
              style={{ flex: 1 }}
              placeholder="Search query (entity, keyword, .onion)"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            />
            <input
              className="hud-input"
              style={{ width: 160 }}
              placeholder="ahmia,darksearch"
              value={engines}
              onChange={(e) => setEngines(e.target.value)}
              title="Comma-separated engines"
            />
            <select
              className="hud-input"
              style={{ width: 100 }}
              value={mode}
              onChange={(e) => setMode(e.target.value as 'auto' | 'clear' | 'tor')}
              title="Routing mode: auto (clearnet engines direct, Tor engines via proxy), clear (clearnet only), tor (all via Tor proxy)"
            >
              <option value="auto">AUTO</option>
              <option value="clear">CLEAR</option>
              <option value="tor">TOR</option>
            </select>
            <button className="hud-button" onClick={handleSearch} disabled={loading}>
              {loading ? '...' : 'SEARCH'}
            </button>
            <button className="hud-button" onClick={() => handleIngest()} disabled={loading || !query}>
              INGEST
            </button>
          </div>

          {error && <div style={{ color: '#ff4d5e', marginBottom: 12 }}>{error}</div>}

          {matches.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <h3 style={{ fontSize: 13, color: '#ffd23f', marginBottom: 6 }}>
                MATCHED ENTITIES ({matches.length})
              </h3>
              {matches.map((m, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: 8,
                    marginBottom: 6,
                    borderLeft: '2px solid #ffd23f',
                    background: '#ffffff08',
                  }}
                >
                  <div style={{ fontSize: 12, color: '#00e5a0' }}>
                    {m.matched_names.join(', ')}
                  </div>
                  <div style={{ fontSize: 11, color: '#b0c4bf' }}>
                    {m.result.title}
                  </div>
                  <div style={{ fontSize: 10, color: '#6f8c84', wordBreak: 'break-all' }}>
                    {m.result.url}
                  </div>
                </div>
              ))}
            </div>
          )}

          {results.length > 0 && (
            <div>
              <h3 style={{ fontSize: 13, color: '#00e5a0', marginBottom: 6 }}>
                RESULTS ({results.length})
              </h3>
              {results.map((r, idx) => (
                <div
                  key={idx}
                  style={{
                    padding: 8,
                    marginBottom: 6,
                    borderLeft: '2px solid #6f8c84',
                    background: '#ffffff08',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ fontSize: 12, color: '#e0f2f1' }}>{r.title}</span>
                    <span style={{ fontSize: 10, color: '#8fb7a9' }}>{r.engine}</span>
                  </div>
                  <div style={{ fontSize: 11, color: '#b0c4bf', marginTop: 4 }}>
                    {r.snippet}
                  </div>
                  <div style={{ fontSize: 10, color: '#6f8c84', wordBreak: 'break-all', marginTop: 4 }}>
                    {r.url}
                  </div>
                  {r.extracted_entities && Object.keys(r.extracted_entities).length > 0 && (
                    <div style={{ marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {Object.entries(r.extracted_entities).map(([k, vals]) => (
                        <span
                          key={k}
                          style={{
                            fontSize: 10,
                            padding: '1px 4px',
                            borderRadius: 3,
                            background: '#00000033',
                            color: '#ffd23f',
                          }}
                        >
                          {k}: {vals.slice(0, 3).join(', ')}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {activeTab === 'mentions' && (
        <div>
          {mentions.length === 0 && (
            <div style={{ color: '#6f8c84' }}>No dark web mentions ingested yet.</div>
          )}
          {mentions.map((m, idx) => {
            const p = m.properties || {}
            return (
              <div
                key={idx}
                style={{
                  padding: 8,
                  marginBottom: 6,
                  borderLeft: '2px solid #00e5a0',
                  background: '#ffffff08',
                }}
              >
                <div style={{ fontSize: 12, color: '#e0f2f1' }}>
                  {(p.name || ['Unknown'])[0]}
                </div>
                <div style={{ fontSize: 10, color: '#8fb7a9' }}>
                  source: {(p.source || ['darkweb'])[0]}
                </div>
                <div style={{ fontSize: 10, color: '#6f8c84', wordBreak: 'break-all' }}>
                  {(p.url || [''])[0]}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {activeTab === 'ransomware' && (
        <div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
            <select
              className="hud-input"
              style={{ flex: 1 }}
              value={selectedRansomwareGroup}
              onChange={(e) => setSelectedRansomwareGroup(e.target.value)}
            >
              <option value="">Select group...</option>
              {ransomwareGroups.map((g) => (
                <option key={g.name} value={g.name}>
                  {g.name} {g.url ? `· ${g.url}` : ''}
                </option>
              ))}
            </select>
            <button
              className="hud-button"
              onClick={handleRefreshRansomware}
              disabled={ransomwareLoading}
            >
              REFRESH
            </button>
            <button
              className="hud-button"
              onClick={handleIngestRansomware}
              disabled={ransomwareLoading || !selectedRansomwareGroup}
            >
              INGEST
            </button>
          </div>
          {ransomwareLoading && <div style={{ color: '#8fb7a9' }}>Loading...</div>}
          {ransomwareVictims.length === 0 && !ransomwareLoading && (
            <div style={{ color: '#6f8c84' }}>Select a group and fetch victims.</div>
          )}
          {ransomwareVictims.map((v, idx) => (
            <div
              key={idx}
              style={{
                padding: 8,
                marginBottom: 6,
                borderLeft: '2px solid #ff4d5e',
                background: '#ffffff08',
              }}
            >
              <div style={{ fontSize: 12, color: '#e0f2f1' }}>{v.victim}</div>
              <div style={{ fontSize: 10, color: '#8fb7a9' }}>
                group: {v.group} {v.discovered && `· ${v.discovered}`} {v.country && `· ${v.country}`}
              </div>
              {v.description && (
                <div style={{ fontSize: 10, color: '#6f8c84', marginTop: 4 }}>
                  {v.description}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
