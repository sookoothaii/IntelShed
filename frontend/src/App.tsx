import { useState, useEffect } from 'react'
import Globe from './components/Globe'
import type { FocusTarget } from './lib/focus'

const NAV_ITEMS: { id: 'globe' | 'data' | 'chat' | 'osint'; label: string; glyph: string }[] = [
  { id: 'globe', label: 'GLOBE', glyph: '◎' },
  { id: 'data', label: 'DATA', glyph: '▤' },
  { id: 'chat', label: 'AI', glyph: '✦' },
  { id: 'osint', label: 'OSINT', glyph: '⌖' },
]

function useClock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  return now
}

function SystemStatus() {
  const [backend, setBackend] = useState<'online' | 'offline' | 'check'>('check')
  const [ollama, setOllama] = useState<'online' | 'offline' | 'check'>('check')

  useEffect(() => {
    const ping = async () => {
      try {
        const r = await fetch('/api/health')
        setBackend(r.ok ? 'online' : 'offline')
      } catch { setBackend('offline') }
      try {
        const r = await fetch('/api/models')
        const d = await r.json()
        setOllama(d.error ? 'offline' : 'online')
      } catch { setOllama('offline') }
    }
    ping()
    const t = setInterval(ping, 15000)
    return () => clearInterval(t)
  }, [])

  return (
    <div className="sys-status">
      <span className={`sys-pip ${backend}`} />BACKEND
      <span className={`sys-pip ${ollama}`} />OLLAMA
    </div>
  )
}

export default function App() {
  const [view, setView] = useState<'globe' | 'data' | 'chat' | 'osint'>('globe')
  const [booting, setBooting] = useState(true)
  const [focus, setFocus] = useState<FocusTarget | null>(null)
  const [askAI, setAskAI] = useState<{ question: string; context: string } | null>(null)
  const [analysisOpen, setAnalysisOpen] = useState(false)
  const now = useClock()

  const focusOnMap = (f: Omit<FocusTarget, 'ts'>) => {
    setFocus({ ...f, ts: Date.now() })
    setView('globe')
  }

  const handleAskAI = (title: string, lines: string[]) => {
    const context = `Entity: ${title}\n${lines.join('\n')}`
    const question = `Analyze this target and tell me what it means for the current world situation:\n${context}`
    setAskAI({ question, context })
    setView('chat')
  }

  useEffect(() => {
    const t = setTimeout(() => setBooting(false), 2200)
    return () => clearTimeout(t)
  }, [])

  const utc = now.toISOString().slice(11, 19)

  return (
    <div className="app">
      <div className="bg-grid" />
      <div className="bg-glow" />

      {booting && <BootOverlay />}

      <header className="hud-header">
        <div className="brand">
          <div className="brand-mark"><span className="brand-ring" />◉</div>
          <div className="brand-text">
            <div className="logo">WORLDBASE</div>
            <div className="brand-sub">SPATIAL INTELLIGENCE</div>
          </div>
        </div>

        <nav className="hud-nav">
          {NAV_ITEMS.map((n) => (
            <button
              key={n.id}
              className={view === n.id ? 'active' : ''}
              onClick={() => setView(n.id)}
            >
              <span className="nav-glyph">{n.glyph}</span>
              {n.label}
            </button>
          ))}
        </nav>

        <div className="hud-meta">
          <button className="mega-analysis-btn" onClick={() => setAnalysisOpen(true)}>FULL SITUATION</button>
          <SystemStatus />
          <div className="hud-clock">
            <span className="clock-time">{utc}</span>
            <span className="clock-zone">UTC</span>
          </div>
        </div>
      </header>

      {analysisOpen && <FullAnalysisOverlay onClose={() => setAnalysisOpen(false)} onFocus={focusOnMap} />}

      <main className="hud-main">
        <div key={view} className="view-fade">
          {view === 'globe' && <Globe focus={focus} onAskAI={handleAskAI} />}
          {view === 'data' && <DataPanel onFocus={focusOnMap} />}
          {view === 'chat' && <ChatPanel askAI={askAI} onClearAsk={() => setAskAI(null)} />}
          {view === 'osint' && <OsintPanel />}
        </div>
      </main>
    </div>
  )
}

function FullAnalysisOverlay({ onClose, onFocus }: { onClose: () => void; onFocus: (f: Omit<FocusTarget, 'ts'>) => void }) {
  const [loading, setLoading] = useState(true)
  const [results, setResults] = useState<any>({})
  const [autoRefresh, setAutoRefresh] = useState(false)

  useEffect(() => {
    let interval: any
    const fetchAll = async () => {
      setLoading(true)
      const endpoints = [
        { key: 'health', url: '/api/health' },
        { key: 'nodes', url: '/api/nodes' },
        { key: 'spaceweather', url: '/api/spaceweather' },
        { key: 'earthquakes', url: '/api/earthquakes?period=day&magnitude=2.5' },
        { key: 'events', url: '/api/events?limit=80' },
        { key: 'military', url: '/api/military' },
        { key: 'geopolitics', url: '/api/geopolitics?limit=20' },
        { key: 'markets', url: '/api/markets' },
        { key: 'correlations', url: '/api/correlations' },
        { key: 'anomalies', url: '/api/anomalies' },
        { key: 'airquality', url: '/api/airquality' },
        { key: 'gdacs', url: '/api/gdacs' },
        { key: 'briefing', url: '/api/briefing' },
      ]
      const out: any = {}
      await Promise.all(endpoints.map(async (ep) => {
        try {
          const r = await fetch(ep.url)
          if (r.ok) out[ep.key] = await r.json()
        } catch (e) {
          out[ep.key] = { error: 'unavailable' }
        }
      }))
      setResults(out)
      setLoading(false)
    }
    fetchAll()
    if (autoRefresh) interval = setInterval(fetchAll, 30000)
    return () => { if (interval) clearInterval(interval) }
  }, [autoRefresh])

  const health = results.health
  const correlations = results.correlations
  const briefing = results.briefing
  const quakes = (results.earthquakes?.earthquakes || []).slice(0, 15)
  const wildfires = (results.events?.events || []).filter((e: any) => (e.category || '').toLowerCase().includes('fire') || (e.title || '').toLowerCase().includes('fire')).slice(0, 8)
  const allEvents = (results.events?.events || []).filter((e: any) => !((e.category || '').toLowerCase().includes('fire') || (e.title || '').toLowerCase().includes('fire'))).slice(0, 10)
  const military = results.military
  const gdacs = (results.gdacs?.alerts || []).slice(0, 15)
  const anomalies = results.anomalies
  const air = results.airquality
  const nodes = results.nodes

  const severityColor = (s: string) => {
    if (!s) return '#00e5a0'
    if (s === 'critical' || s === 'high') return '#ff2d00'
    if (s === 'warning' || s === 'medium') return '#ff6b35'
    return '#00e5a0'
  }
  const aqColor = (pm25: number | null) => {
    if (pm25 == null) return '#6f8c84'
    if (pm25 <= 12) return '#00e5a0'
    if (pm25 <= 35) return '#ffd23f'
    if (pm25 <= 55) return '#ff6b35'
    return '#ff2d00'
  }
  const gdacsType = (title: string) => {
    const t = (title || '').toLowerCase()
    if (t.includes('earthquake')) return { label: 'EQ', color: '#ff6b35' }
    if (t.includes('flood')) return { label: 'FLD', color: '#22d3ee' }
    if (t.includes('cyclone') || t.includes('typhoon') || t.includes('hurricane')) return { label: 'CY', color: '#ffd23f' }
    if (t.includes('tsunami')) return { label: 'TSU', color: '#ff2d00' }
    if (t.includes('drought')) return { label: 'DR', color: '#6f8c84' }
    if (t.includes('volcano')) return { label: 'VOL', color: '#ff4d5e' }
    return { label: 'ALR', color: '#ff6b35' }
  }

  return (
    <div className="analysis-overlay" onClick={onClose}>
      <div className="analysis-panel" onClick={(e) => e.stopPropagation()}>
        <div className="analysis-head">
          <h2>🌍 FULL SITUATION ANALYSIS</h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#6f8c84', cursor: 'pointer' }}>
              <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
              AUTO-REFRESH 30s
            </label>
            <button onClick={onClose}>✕</button>
          </div>
        </div>

        {loading ? (
          <div className="analysis-loading">
            <div className="analysis-spinner" />
            <p>Scanning all feeds…</p>
          </div>
        ) : (
          <div className="analysis-body">
            <div className="analysis-col">

              {/* CRITICAL ALERTS */}
              {(correlations?.situations?.length > 0 || anomalies?.count > 0) && (
                <div className="analysis-section critical">
                  <h3>🚨 CRITICAL ALERTS ({(correlations?.situations?.length || 0) + (anomalies?.count || 0)})</h3>
                  {correlations?.situations?.map((s: any, i: number) => (
                    <div key={i} className="analysis-row" style={{ borderLeft: `3px solid ${severityColor(s.severity)}` }}>
                      <span style={{ color: severityColor(s.severity), fontWeight: 'bold', minWidth: 70 }}>{s.severity?.toUpperCase()}</span>
                      <span>{s.title}</span>
                      {s.location?.lon != null && (
                        <button className="locate-mini" onClick={() => { onClose(); onFocus({ kind: 'situation', lon: s.location.lon, lat: s.location.lat, height: 400000, title: s.title, lines: [`TYPE: ${s.type}`, `SEVERITY: ${s.severity}`] }) }}>◎</button>
                      )}
                    </div>
                  ))}
                  {anomalies?.anomalies?.slice(0, 8).map((a: any, i: number) => (
                    <div key={i} className="analysis-row" style={{ borderLeft: '3px solid #ff2d00' }}>
                      <span style={{ color: '#ff2d00', fontWeight: 'bold', minWidth: 70 }}>ANOMALY</span>
                      <span>{a.callsign || a.icao24} — {a.reasons?.join(', ')}</span>
                      <button className="locate-mini" onClick={() => { onClose(); onFocus({ kind: 'anomaly', lon: a.lon, lat: a.lat, height: 400000, title: `Anomaly ${a.icao24}`, lines: a.reasons || [] }) }}>◎</button>
                    </div>
                  ))}
                </div>
              )}

              {briefing?.text && (
                <div className="analysis-section">
                  <h3>📋 SITUATION BRIEFING</h3>
                  <div className="analysis-briefing">{briefing.text}</div>
                </div>
              )}

              {quakes.length > 0 && (
                <div className="analysis-section">
                  <h3>🌋 SEISMIC ({quakes.length} today)</h3>
                  {quakes.map((q: any, i: number) => (
                    <div key={i} className="analysis-row" style={{ borderLeft: `3px solid ${q.mag >= 5 ? '#ff2d00' : q.mag >= 3.5 ? '#ff6b35' : '#00e5a0'}` }}>
                      <span style={{ fontWeight: 'bold', minWidth: 50 }}>M{q.mag?.toFixed(1) ?? '—'}</span>
                      <span style={{ flex: 1 }}>{q.place || '—'}</span>
                      <span style={{ color: '#6f8c84', minWidth: 70 }}>{q.depth != null ? q.depth.toFixed(1) + ' km' : '—'}</span>
                      <span style={{ color: '#6f8c84', minWidth: 50 }}>{q.tsunami ? 'TSU' : ''}</span>
                      <button className="locate-mini" onClick={() => { onClose(); onFocus({ kind: 'quake', lon: q.lon, lat: q.lat, height: 400000, title: `M${q.mag} ${q.place}`, lines: [`Depth: ${q.depth} km`, `Time: ${new Date(q.time).toLocaleString()}`, `Tsunami: ${q.tsunami ? 'YES' : 'no'}`] }) }}>◎</button>
                    </div>
                  ))}
                </div>
              )}

              {results.spaceweather && (
                <div className="analysis-section">
                  <h3>☀️ SPACE WEATHER</h3>
                  <div className="analysis-row">
                    <span>Kp: <strong>{results.spaceweather.kp_index ?? '—'}</strong></span>
                    <span>Scale: {results.spaceweather.scale ?? '—'}</span>
                    <span style={{ color: results.spaceweather.aurora_visible_midlat ? '#ff6b35' : '#6f8c84' }}>Aurora: {results.spaceweather.aurora_visible_midlat ? 'VISIBLE' : 'none'}</span>
                    <span style={{ color: results.spaceweather.hf_radio_impact ? '#ff6b35' : '#6f8c84' }}>HF: {results.spaceweather.hf_radio_impact ? 'IMPACTED' : 'OK'}</span>
                    <span style={{ color: '#6f8c84' }}>History: {results.spaceweather.history?.length ?? 0} pts</span>
                  </div>
                </div>
              )}

              {allEvents.length > 0 && (
                <div className="analysis-section">
                  <h3>🔔 EVENTS ({allEvents.length})</h3>
                  {allEvents.map((e: any, i: number) => (
                    <div key={i} className="analysis-row" style={{ borderLeft: `3px solid ${(e.magnitude || 0) > 6 ? '#ff2d00' : '#ff6b35'}` }}>
                      <span style={{ minWidth: 90, fontWeight: 'bold' }}>{e.category || 'EVENT'}</span>
                      <span style={{ flex: 1 }}>{e.title || '—'}</span>
                      <span style={{ color: '#6f8c84' }}>{e.date ? new Date(e.date).toLocaleDateString() : '—'}</span>
                      {e.lon != null && (
                        <button className="locate-mini" onClick={() => { onClose(); onFocus({ kind: 'event', lon: e.lon, lat: e.lat, height: 400000, title: e.title, lines: [`Category: ${e.category}`, `Date: ${e.date}`] }) }}>◎</button>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {wildfires.length > 0 && (
                <div className="analysis-section">
                  <h3>🔥 WILDFIRES ({wildfires.length})</h3>
                  {wildfires.map((e: any, i: number) => (
                    <div key={i} className="analysis-row" style={{ borderLeft: '3px solid #ff2d00' }}>
                      <span style={{ flex: 1 }}>{e.title || '—'}</span>
                      <span style={{ color: '#6f8c84' }}>{e.date ? new Date(e.date).toLocaleDateString() : '—'}</span>
                      {e.lon != null && (
                        <button className="locate-mini" onClick={() => { onClose(); onFocus({ kind: 'wildfire', lon: e.lon, lat: e.lat, height: 400000, title: e.title, lines: [`Category: ${e.category}`, `Date: ${e.date}`] }) }}>◎</button>
                      )}
                    </div>
                  ))}
                </div>
              )}

            </div>
            <div className="analysis-col">

              {military?.count > 0 && (
                <div className="analysis-section">
                  <h3>✈️ MILITARY AIRCRAFT ({military.count})</h3>
                  {military.aircraft?.slice(0, 12).map((a: any, i: number) => (
                    <div key={i} className="analysis-row" style={{ borderLeft: ['7500', '7600', '7700'].includes(a.squawk) ? '3px solid #ff2d00' : '3px solid #ff6b35' }}>
                      <span style={{ fontWeight: 'bold', minWidth: 80 }}>{a.flight || a.hex}</span>
                      <span style={{ minWidth: 50 }}>{a.type || '—'}</span>
                      <span style={{ color: '#6f8c84', minWidth: 90 }}>Alt: {a.alt != null && !isNaN(Number(a.alt)) ? Number(a.alt).toFixed(0) + ' m' : '—'}</span>
                      <span style={{ color: '#6f8c84', minWidth: 90 }}>Spd: {a.speed != null && !isNaN(Number(a.speed)) ? Number(a.speed).toFixed(0) + ' m/s' : '—'}</span>
                      {a.squawk && <span style={{ color: '#ff2d00', fontWeight: 'bold', minWidth: 80 }}>SQ {a.squawk}</span>}
                      <button className="locate-mini" onClick={() => { onClose(); onFocus({ kind: 'military', lon: a.lon, lat: a.lat, height: 400000, title: a.flight || a.hex, lines: [`Type: ${a.type || '—'}`, `Alt: ${a.alt} m`, `Speed: ${a.speed} m/s`, `Squawk: ${a.squawk || '—'}`] }) }}>◎</button>
                    </div>
                  ))}
                </div>
              )}

              {gdacs.length > 0 && (
                <div className="analysis-section">
                  <h3>🌊 HUMANITARIAN ALERTS ({gdacs.length})</h3>
                  {gdacs.map((a: any, i: number) => {
                    const gt = gdacsType(a.title)
                    return (
                      <div key={i} className="analysis-row" style={{ borderLeft: `3px solid ${gt.color}` }}>
                        <span style={{ color: gt.color, fontWeight: 'bold', minWidth: 40 }}>{gt.label}</span>
                        <span style={{ flex: 1 }}>{a.title || '—'}</span>
                        <span style={{ color: '#6f8c84', fontSize: 10 }}>{a.published ? new Date(a.published).toLocaleDateString() : '—'}</span>
                        {a.lat != null && (
                          <button className="locate-mini" onClick={() => { onClose(); onFocus({ kind: 'gdacs', lon: a.lon, lat: a.lat, height: 400000, title: a.title, lines: [a.description?.substring(0, 100) || ''] }) }}>◎</button>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}

              {air?.cities?.length > 0 && (
                <div className="analysis-section">
                  <h3>💨 AIR QUALITY ({air.cities.length} cities)</h3>
                  <div className="analysis-grid">
                    {air.cities.map((c: any, i: number) => (
                      <div key={i} className="analysis-card" style={{ borderLeft: `3px solid ${aqColor(c.pm25)}` }}>
                        <strong>{c.city}</strong>
                        <span style={{ color: aqColor(c.pm25) }}>PM2.5: {c.pm25 != null ? c.pm25.toFixed(1) : '—'}</span>
                        <span>PM10: {c.pm10 != null ? c.pm10.toFixed(1) : '—'}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {results.markets?.crypto && (
                <div className="analysis-section">
                  <h3>📈 CRYPTO MARKETS</h3>
                  <div className="analysis-grid">
                    {Object.entries(results.markets.crypto).map(([k, v]: [string, any]) => {
                      const price = v.usd ?? v.price ?? null
                      const change = v.usd_24h_change ?? v.change_24h ?? null
                      return (
                        <div key={k} className="analysis-card">
                          <strong>{k.toUpperCase()}</strong>
                          <span>${price != null ? price.toLocaleString('en-US') : '—'}</span>
                          <span style={{ color: (change ?? 0) >= 0 ? '#00e5a0' : '#ff2d00' }}>{change != null ? change.toFixed(2) : '—'}%</span>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {nodes?.nodes?.length > 0 && (
                <div className="analysis-section">
                  <h3>📡 NODES ({nodes.count})</h3>
                  {nodes.nodes.map((n: any, i: number) => (
                    <div key={i} className="analysis-row" style={{ borderLeft: n.online ? '3px solid #00e5a0' : '3px solid #ff2d00' }}>
                      <span style={{ fontWeight: 'bold' }}>{n.name}</span>
                      <span style={{ color: n.online ? '#00e5a0' : '#ff2d00' }}>{n.online ? 'ONLINE' : 'OFFLINE'}</span>
                      <span style={{ color: '#6f8c84' }}>{Math.round(n.age_seconds || 0)}s ago</span>
                      <span style={{ color: '#6f8c84' }}>CPU: {n.health?.cpu_temp_c != null ? n.health.cpu_temp_c + '°C' : '—'}</span>
                      <span style={{ color: '#6f8c84' }}>Load: {n.health?.load_1m != null ? n.health.load_1m : '—'}</span>
                      <span style={{ color: '#6f8c84' }}>RAM: {n.health?.ram_pct != null ? n.health.ram_pct + '%' : '—'}</span>
                      <span style={{ color: '#6f8c84' }}>Disk: {n.health?.disk_pct != null ? n.health.disk_pct + '%' : '—'}</span>
                      {n.lat && (
                        <button className="locate-mini" onClick={() => { onClose(); onFocus({ kind: 'node', lon: n.lon, lat: n.lat, height: 400000, title: n.name, lines: [`Node: ${n.node_id}`, `CPU: ${n.health?.cpu_temp_c ?? '—'}°C`, `RAM: ${n.health?.ram_pct ?? '—'}%`] }) }}>◎</button>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {health?.feeds && (
                <div className="analysis-section">
                  <h3>🔌 FEED HEALTH</h3>
                  <div className="analysis-grid">
                    {Object.entries(health.feeds).map(([k, v]: [string, any]) => (
                      <div key={k} className="analysis-card" style={{ borderLeft: v.fresh ? '3px solid #00e5a0' : '3px solid #ff6b35' }}>
                        <strong>{k}</strong>
                        <span style={{ color: v.fresh ? '#00e5a0' : '#ff6b35' }}>{v.fresh ? 'FRESH' : `${Math.round(v.age_sec || 0)}s old`}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function BootOverlay() {
  const lines = [
    '> INITIALIZING WORLDBASE CORE',
    '> LOADING CESIUM TERRAIN ENGINE',
    '> LINKING OPENSKY / CELESTRAK FEEDS',
    '> SYNCING USGS SEISMIC GRID',
    '> ESTABLISHING NEURAL LINK [OLLAMA]',
    '> SYSTEM ONLINE',
  ]
  return (
    <div className="boot-overlay">
      <div className="boot-core">
        <div className="boot-logo">WORLDBASE</div>
        <div className="boot-sub">SPATIAL INTELLIGENCE WORKSTATION</div>
        <div className="boot-lines">
          {lines.map((l, i) => (
            <div key={i} className="boot-line" style={{ animationDelay: `${i * 0.3}s` }}>{l}</div>
          ))}
        </div>
        <div className="boot-bar"><span /></div>
      </div>
    </div>
  )
}

type Quake = { id: string; place: string; mag: number; depth: number; time: number; lon: number; lat: number; tsunami: number; url: string }
type WEvent = { id: string; title: string; category: string; categories?: string[]; date: string; lon: number; lat: number; magnitude?: number | null; unit?: string | null; closed?: string | null; link?: string; sources?: string[]; points?: number }
type Sat = { name: string; tle1: string; tle2: string }

const DATA_TABS = ['aircraft', 'satellites', 'seismic', 'events', 'iss', 'spaceweather', 'geopolitics', 'markets', 'nodes', 'military', 'situations', 'health'] as const
type DataTab = typeof DATA_TABS[number]

type NodeInfo = { node_id: string; name: string; lat: number; lon: number; updated_at: string; payload?: any }
type MilitaryAircraft = { hex: string; flight: string | null; type: string | null; lat: number | null; lon: number | null; alt: number | null; speed: number | null; squawk: string | null }
type Disaster = { id: string; name: string; status: string; url?: string }
type Situation = { severity: string; type: string; title: string; location: any; details: any }

const SAT_GROUPS = ['starlink', 'stations', 'gps-ops', 'weather']

function DataPanel({ onFocus }: { onFocus: (f: Omit<FocusTarget, 'ts'>) => void }) {
  const [tab, setTab] = useState<DataTab>('aircraft')
  const [aircraft, setAircraft] = useState<(string | number | null)[][]>([])
  const [satellites, setSatellites] = useState<Sat[]>([])
  const [satGroup, setSatGroup] = useState('starlink')
  const [quakes, setQuakes] = useState<Quake[]>([])
  const [events, setEvents] = useState<WEvent[]>([])
  const [iss, setIss] = useState<any>(null)
  const [spaceweather, setSpaceweather] = useState<any>(null)
  const [geopolitics, setGeopolitics] = useState<{ count: number; disasters: Disaster[]; error?: string } | null>(null)
  const [markets, setMarkets] = useState<any>(null)
  const [nodes, setNodes] = useState<NodeInfo[]>([])
  const [military, setMilitary] = useState<MilitaryAircraft[]>([])
  const [situations, setSituations] = useState<Situation[]>([])
  const [health, setHealth] = useState<{ status: string; time: string } | null>(null)
  const [loading, setLoading] = useState<Record<string, boolean>>({})
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')

  const fetchFeed = async <T,>(key: string, url: string, setter: (d: T) => void) => {
    setLoading((l) => ({ ...l, [key]: true }))
    setError(null)
    try {
      const r = await fetch(url)
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
      setter(await r.json())
    } catch (e) {
      setError(`${key}: ${(e as Error).message}`)
    } finally {
      setLoading((l) => ({ ...l, [key]: false }))
    }
  }

  const loadAircraft = () => fetchFeed('aircraft', '/api/aircraft', (d: any) => setAircraft(d.states || []))
  const loadSatellites = (g = satGroup) => fetchFeed('satellites', `/api/satellites?group=${g}&limit=500`, (d: any) => setSatellites(d.satellites || []))
  const loadQuakes = () => fetchFeed('seismic', '/api/earthquakes?period=day&magnitude=2.5', (d: any) => setQuakes(d.earthquakes || []))
  const loadEvents = () => fetchFeed('events', '/api/events?limit=120', (d: any) => setEvents(d.events || []))
  const loadIss = () => fetchFeed('iss', '/api/iss', (d: any) => setIss(d))
  const loadSpaceweather = () => fetchFeed('spaceweather', '/api/spaceweather', (d: any) => setSpaceweather(d))
  const loadGeopolitics = () => fetchFeed('geopolitics', '/api/geopolitics', (d: any) => setGeopolitics(d))
  const loadMarkets = () => fetchFeed('markets', '/api/markets', (d: any) => setMarkets(d))
  const loadNodes = () => fetchFeed('nodes', '/api/nodes', (d: any) => setNodes(d.nodes || []))
  const loadMilitary = () => fetchFeed('military', '/api/military', (d: any) => setMilitary(d.aircraft || []))
  const loadSituations = () => fetchFeed('situations', '/api/correlations', (d: any) => setSituations(d.situations || []))
  const loadHealth = () => fetchFeed('health', '/api/health', (d: any) => setHealth(d))

  // Auto-load on tab switch
  useEffect(() => {
    setQuery('')
    if (tab === 'aircraft') loadAircraft()
    else if (tab === 'satellites') loadSatellites()
    else if (tab === 'seismic') loadQuakes()
    else if (tab === 'events') loadEvents()
    else if (tab === 'iss') loadIss()
    else if (tab === 'spaceweather') loadSpaceweather()
    else if (tab === 'geopolitics') loadGeopolitics()
    else if (tab === 'markets') loadMarkets()
    else if (tab === 'nodes') loadNodes()
    else if (tab === 'military') loadMilitary()
    else if (tab === 'situations') loadSituations()
    else if (tab === 'health') loadHealth()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  const q = query.toLowerCase()
  const fAircraft = aircraft.filter((a) => !q || `${a[0]} ${a[1]} ${a[2]}`.toLowerCase().includes(q))
  const fSats = satellites.filter((s) => !q || s.name.toLowerCase().includes(q))
  const fQuakes = quakes.filter((x) => !q || (x.place || '').toLowerCase().includes(q))
  const fEvents = events.filter((x) => !q || `${x.title} ${x.category}`.toLowerCase().includes(q))

  const magColor = (m: number) => (m >= 6 ? '#ff2d00' : m >= 4.5 ? '#ff6b35' : m >= 3 ? '#ffd23f' : '#8fb7a9')

  const eventFocus = (x: WEvent): Omit<FocusTarget, 'ts'> => {
    const lines = [
      x.category + (x.categories && x.categories.length > 1 ? ` · ${x.categories.slice(1).join(', ')}` : ''),
      `COORD: ${x.lat?.toFixed(3)}, ${x.lon?.toFixed(3)}`,
    ]
    if (x.magnitude != null) lines.push(`MAGNITUDE: ${x.magnitude} ${x.unit || ''}`.trim())
    if (x.date) lines.push(`UPDATED: ${new Date(x.date).toLocaleString()}`)
    if (x.points && x.points > 1) lines.push(`TRACK POINTS: ${x.points}`)
    lines.push(`STATUS: ${x.closed ? 'CLOSED' : 'ACTIVE'}`)
    return {
      kind: 'event', lon: x.lon, lat: x.lat, height: 450000,
      title: x.title, lines,
      link: x.sources?.[0] || x.link,
    }
  }

  const quakeFocus = (x: Quake): Omit<FocusTarget, 'ts'> => ({
    kind: 'quake', lon: x.lon, lat: x.lat, height: 300000,
    title: `M${x.mag?.toFixed(1)} · ${x.place}`,
    lines: [
      `MAGNITUDE: ${x.mag?.toFixed(1)}`,
      `DEPTH: ${x.depth?.toFixed(1)} km`,
      `COORD: ${x.lat?.toFixed(3)}, ${x.lon?.toFixed(3)}`,
      `TIME: ${new Date(x.time).toLocaleString()}`,
      x.tsunami ? 'TSUNAMI: ⚠ POTENTIAL' : 'TSUNAMI: none',
    ],
    link: x.url,
  })

  return (
    <div className="panel">
      <h2>Live Feeds</h2>

      <div className="data-tabs">
        {DATA_TABS.map((t) => (
          <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>{t.toUpperCase()}</button>
        ))}
      </div>

      {error && <div className="data-error">{error}</div>}

      {(tab === 'aircraft' || tab === 'satellites' || tab === 'seismic' || tab === 'events') && (
        <div className="data-toolbar">
          <input className="data-search" placeholder="Filter…" value={query} onChange={(e) => setQuery(e.target.value)} />
          {tab === 'satellites' && (
            <div className="data-groups">
              {SAT_GROUPS.map((g) => (
                <button key={g} className={satGroup === g ? 'on' : ''} onClick={() => { setSatGroup(g); loadSatellites(g) }}>{g.toUpperCase()}</button>
              ))}
            </div>
          )}
          <button className="data-refresh" onClick={() => {
            if (tab === 'aircraft') loadAircraft()
            else if (tab === 'satellites') loadSatellites()
            else if (tab === 'seismic') loadQuakes()
            else loadEvents()
          }}>↻ REFRESH</button>
        </div>
      )}

      {tab === 'aircraft' && (
        <section>
          <span className="data-count">{fAircraft.length} / {aircraft.length} aircraft</span>
          <table className="data-table">
            <thead><tr><th>ICAO24</th><th>Callsign</th><th>Country</th><th>Lat</th><th>Lon</th><th>Alt (m)</th><th>Vel (m/s)</th><th>Hdg</th></tr></thead>
            <tbody>
              {fAircraft.slice(0, 100).map((a, i) => (
                <tr key={i}>
                  <td>{a[0]}</td><td>{a[1] || '—'}</td><td>{a[2]}</td>
                  <td>{a[6] != null ? Number(a[6]).toFixed(2) : '—'}</td>
                  <td>{a[5] != null ? Number(a[5]).toFixed(2) : '—'}</td>
                  <td>{a[7] != null ? Math.round(Number(a[7])) : '—'}</td>
                  <td>{a[9] != null ? Number(a[9]).toFixed(1) : '—'}</td>
                  <td>{a[10] != null ? Math.round(Number(a[10])) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'satellites' && (
        <section>
          <span className="data-count">{fSats.length} / {satellites.length} sats · {satGroup}</span>
          <table className="data-table">
            <thead><tr><th>Name</th><th>NORAD</th><th>Inclination</th><th>Period (min)</th></tr></thead>
            <tbody>
              {fSats.slice(0, 100).map((s, i) => {
                const t2 = s.tle2 || ''
                const norad = t2.substring(2, 7).trim()
                const inc = t2.substring(8, 16).trim()
                const mm = parseFloat(t2.substring(52, 63).trim())
                const period = mm ? (1440 / mm).toFixed(1) : '—'
                return <tr key={i}><td>{s.name}</td><td>{norad}</td><td>{inc}°</td><td>{period}</td></tr>
              })}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'seismic' && (
        <section>
          <span className="data-count">{fQuakes.length} / {quakes.length} earthquakes · 24h · click to locate</span>
          <table className="data-table clickable">
            <thead><tr><th>Mag</th><th>Place</th><th>Depth (km)</th><th>Time</th><th>Tsunami</th><th></th></tr></thead>
            <tbody>
              {fQuakes.slice(0, 100).map((x) => (
                <tr key={x.id} onClick={() => onFocus(quakeFocus(x))}>
                  <td style={{ color: magColor(x.mag), fontWeight: 'bold' }}>{x.mag?.toFixed(1)}</td>
                  <td>{x.place}</td>
                  <td>{x.depth != null ? x.depth.toFixed(1) : '—'}</td>
                  <td>{new Date(x.time).toLocaleString()}</td>
                  <td>{x.tsunami ? '⚠ YES' : '—'}</td>
                  <td className="locate-cell">◎ LOCATE</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'events' && (
        <section>
          <span className="data-count">{fEvents.length} / {events.length} natural events · click to locate</span>
          <table className="data-table clickable">
            <thead><tr><th>Category</th><th>Title</th><th>Lat</th><th>Lon</th><th>Date</th><th></th></tr></thead>
            <tbody>
              {fEvents.slice(0, 100).map((x) => (
                <tr key={x.id} onClick={() => onFocus(eventFocus(x))}>
                  <td>{x.category}</td><td>{x.title}</td>
                  <td>{x.lat?.toFixed(2)}</td><td>{x.lon?.toFixed(2)}</td>
                  <td>{x.date ? new Date(x.date).toLocaleDateString() : '—'}</td>
                  <td className="locate-cell">◎ LOCATE</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'iss' && (
        <section>
          <button onClick={loadIss} disabled={loading['iss']}>{loading['iss'] ? 'Loading…' : '↻ Update ISS'}</button>
          {iss ? (
            <div className="iss-grid">
              <div className="iss-card"><span>LATITUDE</span><strong>{Number(iss.latitude).toFixed(4)}°</strong></div>
              <div className="iss-card"><span>LONGITUDE</span><strong>{Number(iss.longitude).toFixed(4)}°</strong></div>
              <div className="iss-card"><span>ALTITUDE</span><strong>{Number(iss.altitude).toFixed(1)} km</strong></div>
              <div className="iss-card"><span>VELOCITY</span><strong>{Number(iss.velocity).toFixed(0)} km/h</strong></div>
              <div className="iss-card"><span>VISIBILITY</span><strong>{iss.visibility}</strong></div>
              <div className="iss-card"><span>FOOTPRINT</span><strong>{Number(iss.footprint).toFixed(0)} km</strong></div>
            </div>
          ) : <div className="health-status pending">NO DATA</div>}
        </section>
      )}

      {tab === 'spaceweather' && (
        <section>
          <button onClick={loadSpaceweather} disabled={loading['spaceweather']}>{loading['spaceweather'] ? 'Loading…' : '↻ Refresh'}</button>
          {spaceweather ? (
            <div className="iss-grid">
              <div className="iss-card"><span>KP INDEX</span><strong>{spaceweather.kp_index ?? '—'}</strong></div>
              <div className="iss-card"><span>SCALE</span><strong>{spaceweather.scale ?? '—'}</strong></div>
              <div className="iss-card"><span>SOLAR WIND</span><strong>{spaceweather.solar_wind_speed ? spaceweather.solar_wind_speed + ' km/s' : '—'}</strong></div>
              <div className="iss-card"><span>BT</span><strong>{spaceweather.bt ?? '—'} nT</strong></div>
              <div className="iss-card"><span>DST</span><strong>{spaceweather.dst ?? '—'} nT</strong></div>
              <div className="iss-card"><span>AURORA</span><strong>{spaceweather.aurora_probability ? Math.round(spaceweather.aurora_probability * 100) + '%' : '—'}</strong></div>
            </div>
          ) : <div className="health-status pending">NO DATA</div>}
        </section>
      )}

      {tab === 'geopolitics' && (
        <section>
          <button onClick={loadGeopolitics} disabled={loading['geopolitics']}>{loading['geopolitics'] ? 'Loading…' : '↻ Refresh'}</button>
          <span className="data-count">{geopolitics?.count ?? 0} disasters</span>
          {geopolitics?.error && <div className="data-error">{geopolitics.error}</div>}
          <table className="data-table">
            <thead><tr><th>Name</th><th>Status</th></tr></thead>
            <tbody>
              {(geopolitics?.disasters || []).map((d: Disaster) => (
                <tr key={d.id}>
                  <td>{d.name}</td>
                  <td>{d.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'markets' && (
        <section>
          <button onClick={loadMarkets} disabled={loading['markets']}>{loading['markets'] ? 'Loading…' : '↻ Refresh'}</button>
          {markets?.crypto ? (
            <div className="iss-grid">
              {Object.entries(markets.crypto).map(([k, v]: [string, any]) => (
                <div className="iss-card" key={k}>
                  <span>{k.toUpperCase()}</span>
                  <strong>${v.usd?.toLocaleString?.() ?? v.usd}</strong>
                  <small style={{ color: (v.change_24h ?? 0) >= 0 ? '#00e5a0' : '#ff6b35' }}>
                    {v.change_24h != null ? (v.change_24h >= 0 ? '+' : '') + v.change_24h.toFixed(2) + '%' : ''}
                  </small>
                </div>
              ))}
            </div>
          ) : <div className="health-status pending">NO DATA</div>}
          <div style={{ marginTop: 8, fontSize: 12, color: '#6f8c84' }}>Updated: {markets?.updated ?? '—'}</div>
        </section>
      )}

      {tab === 'nodes' && (
        <section>
          <button onClick={loadNodes} disabled={loading['nodes']}>{loading['nodes'] ? 'Loading…' : '↻ Refresh'}</button>
          <span className="data-count">{nodes.length} nodes</span>
          <table className="data-table clickable">
            <thead><tr><th>Name</th><th>ID</th><th>Lat</th><th>Lon</th><th>Updated</th><th></th></tr></thead>
            <tbody>
              {nodes.map((n: NodeInfo) => (
                <tr key={n.node_id} onClick={() => onFocus({ kind: 'node', lon: n.lon, lat: n.lat, height: 500000, title: n.name, lines: [`NODE: ${n.node_id}`, `UPDATED: ${n.updated_at}`] })}>
                  <td>{n.name}</td><td>{n.node_id}</td>
                  <td>{n.lat?.toFixed(4)}</td><td>{n.lon?.toFixed(4)}</td>
                  <td>{new Date(n.updated_at).toLocaleString()}</td>
                  <td className="locate-cell">◎ LOCATE</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'military' && (
        <section>
          <button onClick={loadMilitary} disabled={loading['military']}>{loading['military'] ? 'Loading…' : '↻ Refresh'}</button>
          <span className="data-count">{military.length} military aircraft</span>
          <table className="data-table clickable">
            <thead><tr><th>Hex</th><th>Flight</th><th>Type</th><th>Lat</th><th>Lon</th><th>Alt (m)</th><th>Speed</th><th>Squawk</th><th></th></tr></thead>
            <tbody>
              {military.map((a: MilitaryAircraft, i: number) => (
                <tr key={i} onClick={() => a.lat && a.lon && onFocus({ kind: 'aircraft', lon: a.lon, lat: a.lat, height: 300000, title: a.flight || a.hex, lines: [`TYPE: ${a.type || '—'}`, `ALT: ${a.alt ?? '—'} m`, `SPEED: ${a.speed ?? '—'} m/s`, `SQUAWK: ${a.squawk || '—'}`] })}>
                  <td>{a.hex}</td><td>{a.flight || '—'}</td><td>{a.type || '—'}</td>
                  <td>{a.lat != null ? a.lat.toFixed(2) : '—'}</td>
                  <td>{a.lon != null ? a.lon.toFixed(2) : '—'}</td>
                  <td>{a.alt != null ? Math.round(a.alt) : '—'}</td>
                  <td>{a.speed != null ? a.speed.toFixed(1) : '—'}</td>
                  <td style={{ color: ['7500', '7600', '7700'].includes(a.squawk || '') ? '#ff2d00' : 'inherit', fontWeight: ['7500', '7600', '7700'].includes(a.squawk || '') ? 'bold' : 'normal' }}>{a.squawk || '—'}</td>
                  <td className="locate-cell">◎ LOCATE</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'situations' && (
        <section>
          <button onClick={loadSituations} disabled={loading['situations']}>{loading['situations'] ? 'Loading…' : '↻ Refresh'}</button>
          <span className="data-count">{situations.length} developing situations</span>
          {situations.length === 0 && <div className="health-status pending">No active correlations detected</div>}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {situations.map((s: Situation, i: number) => (
              <div key={i} className="iss-card" style={{ cursor: 'pointer', borderLeft: `3px solid ${s.severity === 'high' ? '#ff2d00' : '#ff6b35'}` }} onClick={() => s.location?.lon && s.location?.lat && onFocus({ kind: 'situation', lon: s.location.lon, lat: s.location.lat, height: 400000, title: s.title, lines: [`TYPE: ${s.type}`, `SEVERITY: ${s.severity.toUpperCase()}`] })}>
                <span style={{ color: s.severity === 'high' ? '#ff2d00' : '#ff6b35', fontWeight: 'bold' }}>{s.severity.toUpperCase()}</span>
                <strong>{s.title}</strong>
                <small style={{ color: '#6f8c84' }}>{s.type}</small>
              </div>
            ))}
          </div>
        </section>
      )}

      {tab === 'health' && (
        <section>
          <button onClick={loadHealth} disabled={loading['health']}>{loading['health'] ? 'Loading…' : 'Ping Backend'}</button>
          <div className="data-health">
            {health ? (
              <><div className="health-status ok">{health.status.toUpperCase()}</div><div className="health-time">{health.time}</div></>
            ) : <div className="health-status pending">NOT CHECKED</div>}
          </div>
        </section>
      )}
    </div>
  )
}

function ChatPanel({ askAI, onClearAsk }: { askAI?: { question: string; context: string } | null; onClearAsk?: () => void }) {
  const [msg, setMsg] = useState('')
  const [history, setHistory] = useState<{ role: string; content: string }[]>([
    { role: 'system', content: 'Select a model and start chatting.' },
  ])
  const [models, setModels] = useState<{ name: string; parameter_size?: string }[]>([])
  const [model, setModel] = useState('')
  const [busy, setBusy] = useState(false)
  const [modelErr, setModelErr] = useState<string | null>(null)
  const [webSearch, setWebSearch] = useState(false)

  useEffect(() => {
    fetch('/api/models')
      .then((r) => r.json())
      .then((d) => {
        if (d.error) {
          setModelErr(d.error)
          return
        }
        const list = d.models || []
        setModels(list)
        if (list.length > 0 && !model) {
          setModel(list[0].name)
        }
      })
      .catch(() => setModelErr('Could not reach backend for model list'))
  }, [])

  // Auto-send when askAI is provided (from globe target click)
  useEffect(() => {
    if (askAI && !busy) {
      setMsg(askAI.question)
      // Small delay to let React render before sending
      const t = setTimeout(() => {
        sendWithMessage(askAI.question, askAI.context)
        onClearAsk?.()
      }, 100)
      return () => clearTimeout(t)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [askAI])

  async function sendWithMessage(userMsg: string, entityCtx?: string) {
    if (busy) return
    let activeModel = model
    if (!activeModel && models.length > 0) {
      activeModel = models[0].name
      setModel(activeModel)
    }
    if (!activeModel) return
    setMsg('')
    setHistory((h) => [...h, { role: 'user', content: userMsg }])
    setBusy(true)

    // Add placeholder assistant message that we will stream into
    setHistory((h) => [...h, { role: 'assistant', content: '' }])

    // Optional web search: fetch results and prepend as context
    let searchCtx = ''
    if (webSearch) {
      try {
        const sr = await fetch(`/api/search?q=${encodeURIComponent(userMsg)}&n=5`)
        const sd = await sr.json()
        if (sd.results && sd.results.length > 0) {
          searchCtx = sd.results.map((r: any, i: number) =>
            `[${i + 1}] ${r.title}\n${r.snippet}\nURL: ${r.url}`
          ).join('\n\n')
        }
      } catch {
        // search failed silently, continue without context
      }
    }

    // If entity context provided, prepend it to search results
    const combinedSearchResults = entityCtx
      ? (searchCtx ? entityCtx + '\n\n' + searchCtx : entityCtx)
      : (searchCtx || undefined)

    try {
      const r = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Accept': 'text/event-stream' },
        body: JSON.stringify({
          model: activeModel,
          messages: [{ role: 'user', content: userMsg }],
          stream: true,
          context: true,
          search_results: combinedSearchResults,
        }),
      })
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
      if (!r.body) throw new Error('No response body')

      const reader = r.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // Parse SSE lines: data: {...}
        const lines = buffer.split('\n\n')
        buffer = lines.pop() || ''  // keep incomplete chunk

        for (const chunk of lines) {
          const m = chunk.match(/^data: (.+)$/m)
          if (!m) continue
          try {
            const data = JSON.parse(m[1])
            if (data.error) {
              setHistory((h) => {
                const copy = [...h]
                copy[copy.length - 1] = { role: 'assistant', content: 'Error: ' + data.error }
                return copy
              })
              break
            }
            if (data.done) {
              break
            }
            if (data.token) {
              setHistory((h) => {
                const copy = [...h]
                copy[copy.length - 1] = {
                  role: 'assistant',
                  content: copy[copy.length - 1].content + data.token,
                }
                return copy
              })
            }
          } catch {
            // ignore malformed SSE
          }
        }
      }
    } catch (e) {
      setHistory((h) => {
        const copy = [...h]
        copy[copy.length - 1] = { role: 'assistant', content: 'Error: ' + (e as Error).message }
        return copy
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel chat">
      <h2>Local AI (Ollama)</h2>

      {modelErr && <div className="data-error">{modelErr}</div>}

      <div className="model-select">
        <label>Model:</label>
        <select value={model} onChange={(e) => setModel(e.target.value)} disabled={models.length === 0}>
          {models.length === 0 && <option value="">No models found</option>}
          {models.map((m) => (
            <option key={m.name} value={m.name}>
              {m.name} {m.parameter_size ? `(${m.parameter_size})` : ''}
            </option>
          ))}
        </select>
        {models.length > 0 && (
          <span className="model-count">{models.length} available</span>
        )}
        <button
          className={webSearch ? 'web-search on' : 'web-search'}
          onClick={() => setWebSearch((v) => !v)}
          title="Toggle web search (injects DuckDuckGo results as context)"
        >
          {webSearch ? '🔍 ON' : '🔍 OFF'}
        </button>
      </div>

      <div className="chat-history">
        {history.map((m, i) => (
          <div key={i} className={`chat-msg ${m.role}`}>
            <strong>{m.role}:</strong> {m.content}
          </div>
        ))}
        {busy && <div className="chat-msg assistant">…</div>}
      </div>
      <div className="chat-input">
        <input
          value={msg}
          onChange={(e) => setMsg(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && sendWithMessage(msg.trim())}
          placeholder={model ? `Ask ${model}…` : models.length > 0 ? `Ask ${models[0].name}…` : 'Select a model first…'}
          disabled={models.length === 0 && !model}
        />
        <button onClick={() => sendWithMessage(msg.trim())} disabled={busy || (models.length === 0 && !model)}>
          Send
        </button>
      </div>
    </div>
  )
}

function OsintPanel() {
  const url = (import.meta as any).env?.VITE_OSINT_URL || 'http://localhost:15000'
  const [reloadKey, setReloadKey] = useState(0)

  return (
    <div className="panel osint" style={{ padding: '0 14px' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 12,
          padding: '10px 2px',
        }}
      >
        <h2 style={{ margin: 0 }}>OSINT Console</h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontFamily: 'monospace', fontSize: 12, color: '#6f8c84' }}>{url}</span>
          <button onClick={() => setReloadKey((k) => k + 1)}>↻ RELOAD</button>
          <a href={url} target="_blank" rel="noreferrer">
            <button>↗ OPEN</button>
          </a>
        </div>
      </div>
      <iframe
        key={reloadKey}
        src={url}
        title="OSINT Console"
        className="osint-frame"
        style={{
          width: '100%',
          height: 'calc(100vh - 170px)',
          border: '1px solid rgba(0,229,160,0.25)',
          borderRadius: 10,
          background: '#060a12',
        }}
      />
    </div>
  )
}
