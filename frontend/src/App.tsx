import { useState, useEffect } from 'react'
import Globe from './components/Globe'
import type { FocusTarget } from './lib/focus'

const NAV_ITEMS: { id: 'globe' | 'data' | 'chat' | 'osint'; label: string; glyph: string }[] = [
  { id: 'globe', label: 'GLOBE', glyph: '◎' },
  { id: 'data', label: 'DATA', glyph: '▤' },
  { id: 'chat', label: 'AI', glyph: '✦' },
  { id: 'osint', label: 'OSINT', glyph: '⌖' },
]


function useAlertNotifications() {
  const [lastNotified, setLastNotified] = useState<number>(0)

  useEffect(() => {
    if (!('Notification' in window)) return
    if (Notification.permission === 'default') {
      Notification.requestPermission()
    }

    const check = async () => {
      if (Notification.permission !== 'granted') return
      try {
        const [corrRes, anomRes] = await Promise.all([
          fetch('/api/correlations').then(r => r.ok ? r.json() : null),
          fetch('/api/anomalies').then(r => r.ok ? r.json() : null),
        ])
        const now = Date.now()
        if (now - lastNotified < 300000) return // 5 min cooldown
        const situations = corrRes?.situations || []
        const anomalies = anomRes?.anomalies || []
        if (situations.length > 0 || anomalies.length > 0) {
          const titles = [
            ...situations.map((s: any) => s.title),
            ...anomalies.slice(0, 3).map((a: any) => `Anomaly ${a.callsign || a.icao24}`),
          ]
          new Notification('WorldBase Alert', {
            body: titles.join(' | '),
            icon: '/favicon.ico',
            tag: 'worldbase-alert',
          })
          setLastNotified(now)
        }
      } catch {
        // ignore
      }
    }

    check()
    const t = setInterval(check, 60000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
}
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
  useAlertNotifications()
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
          {view === 'osint' && <OsintPanel onFocus={focusOnMap} />}
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

const DATA_TABS = ['aircraft', 'satellites', 'seismic', 'events', 'iss', 'spaceweather', 'geopolitics', 'markets', 'nodes', 'military', 'situations', 'health', 'airquality', 'gdacs', 'weather', 'wildfires', 'lightning', 'energy', 'eu-energy', 'stocks', 'transit', 'maritime'] as const
type DataTab = typeof DATA_TABS[number]

type NodeInfo = { node_id: string; name: string; lat: number; lon: number; updated_at: string; payload?: any }
type MilitaryAircraft = { hex: string; flight: string | null; type: string | null; lat: number | null; lon: number | null; alt: number | null; speed: number | null; squawk: string | null }
type Disaster = { id: string; name: string; status: string; url?: string }
type Situation = { severity: string; type: string; title: string; location: any; details: any }
type AirQualityCity = { city: string; lat: number; lon: number; pm25: number | null; pm10: number | null; time: string | null }
type GDACSAlert = { title: string; link: string; description: string; published: string; lat: number | null; lon: number | null }
type WeatherPoint = { lat: number; lon: number; current: any; units: any; timezone: string }

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
  const [airquality, setAirquality] = useState<{ cities: AirQualityCity[]; updated: string; error?: string } | null>(null)
  const [gdacs, setGdacs] = useState<{ count: number; alerts: GDACSAlert[]; error?: string } | null>(null)
  const [weather, setWeather] = useState<WeatherPoint | null>(null)
  const [wildfires, setWildfires] = useState<{ count: number; fires: any[]; updated: string } | null>(null)
  const [lightning, setLightning] = useState<{ count: number; strikes: any[]; updated: string } | null>(null)
  const [energy, setEnergy] = useState<any>(null)
  const [stocks, setStocks] = useState<{ count: number; quotes: any[]; updated: string } | null>(null)
  const [transit, setTransit] = useState<{ city: string; count: number; vehicles: any[]; cached_at: string; error?: string } | null>(null)
  const [transitCity, setTransitCity] = useState('helsinki')
  const [maritime, setMaritime] = useState<{ count: number; vessels: any[]; demo_mode?: boolean; cached_at: string; error?: string } | null>(null)
  const [euEnergy, setEuEnergy] = useState<{ country: string; prices: any[]; generation_by_source?: Record<string, number>; total_mw?: number; demo_mode?: boolean; error?: string } | null>(null)
  const [euCountry, setEuCountry] = useState('de')
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
  const loadAirquality = () => fetchFeed('airquality', '/api/airquality', (d: any) => setAirquality(d))
  const loadGdacs = () => fetchFeed('gdacs', '/api/gdacs', (d: any) => setGdacs(d))
  const loadWeather = () => fetchFeed('weather', '/api/weather?lat=13.75&lon=100.5', (d: any) => setWeather(d))
  const loadWildfires = () => fetchFeed('wildfires', '/api/wildfires', (d: any) => setWildfires(d))
  const loadLightning = () => fetchFeed('lightning', '/api/lightning', (d: any) => setLightning(d))
  const loadEnergy = () => fetchFeed('energy', '/api/energy/de', (d: any) => setEnergy(d))
  const loadStocks = () => fetchFeed('stocks', '/api/stocks', (d: any) => setStocks(d))
  const loadTransit = () => fetchFeed('transit', `/api/transit/${transitCity}`, (d: any) => setTransit(d))
  const loadMaritime = () => fetchFeed('maritime', '/api/maritime', (d: any) => setMaritime(d))
  const loadEuEnergy = async () => {
    setLoading((l) => ({ ...l, 'eu-energy': true }))
    setError(null)
    try {
      const [r1, r2] = await Promise.all([
        fetch(`/api/eu-energy/price/${euCountry}`),
        fetch(`/api/eu-energy/generation/${euCountry}`),
      ])
      if (!r1.ok) throw new Error(`${r1.status} ${r1.statusText}`)
      if (!r2.ok) throw new Error(`${r2.status} ${r2.statusText}`)
      const priceData = await r1.json()
      const genData = await r2.json()
      setEuEnergy({ ...priceData, generation_by_source: genData.generation_by_source, total_mw: genData.total_mw })
    } catch (e) {
      setError(`eu-energy: ${(e as Error).message}`)
    } finally {
      setLoading((l) => ({ ...l, 'eu-energy': false }))
    }
  }

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
    else if (tab === 'airquality') loadAirquality()
    else if (tab === 'gdacs') loadGdacs()
    else if (tab === 'weather') loadWeather()
    else if (tab === 'wildfires') loadWildfires()
    else if (tab === 'lightning') loadLightning()
    else if (tab === 'energy') loadEnergy()
    else if (tab === 'stocks') loadStocks()
    else if (tab === 'transit') loadTransit()
    else if (tab === 'maritime') loadMaritime()
    else if (tab === 'eu-energy') loadEuEnergy()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, transitCity, euCountry])

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
      {tab === 'airquality' && (
        <section>
          <button onClick={loadAirquality} disabled={loading['airquality']}>{loading['airquality'] ? 'Loading…' : '↻ Refresh'}</button>
          <span className="data-count">{airquality?.cities?.length || 0} cities monitored</span>
          {!airquality?.cities?.length && <div className="health-status pending">No air quality data</div>}
          <table className="data-table">
            <thead><tr><th>City</th><th>PM2.5</th><th>PM10</th><th>Status</th></tr></thead>
            <tbody>
              {(airquality?.cities || []).map((c: AirQualityCity, i: number) => {
                const pm25 = c.pm25 ?? null
                const color = pm25 == null ? '#6f8c84' : pm25 <= 12 ? '#00e5a0' : pm25 <= 35 ? '#ffd23f' : pm25 <= 55 ? '#ff6b35' : '#ff2d00'
                const label = pm25 == null ? '—' : pm25 <= 12 ? 'Good' : pm25 <= 35 ? 'Moderate' : pm25 <= 55 ? 'Unhealthy' : 'Hazardous'
                return (
                  <tr key={i}>
                    <td>{c.city}</td>
                    <td style={{ color }}>{pm25 ?? '—'} µg/m³</td>
                    <td>{c.pm10 ?? '—'} µg/m³</td>
                    <td style={{ color, fontWeight: 'bold' }}>{label}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'gdacs' && (
        <section>
          <button onClick={loadGdacs} disabled={loading['gdacs']}>{loading['gdacs'] ? 'Loading…' : '↻ Refresh'}</button>
          <span className="data-count">{gdacs?.alerts?.length || 0} alerts</span>
          {!gdacs?.alerts?.length && <div className="health-status pending">No GDACS alerts</div>}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {(gdacs?.alerts || []).map((a: GDACSAlert, i: number) => {
              const t = (a.title || '').toLowerCase()
              const type = t.includes('earthquake') ? { label: 'EQ', color: '#ff6b35' } : t.includes('flood') ? { label: 'FLD', color: '#22d3ee' } : t.includes('cyclone') || t.includes('typhoon') || t.includes('hurricane') ? { label: 'CY', color: '#ffd23f' } : t.includes('tsunami') ? { label: 'TSU', color: '#ff2d00' } : t.includes('drought') ? { label: 'DR', color: '#6f8c84' } : t.includes('volcano') ? { label: 'VOL', color: '#ff4d5e' } : { label: 'ALR', color: '#ff6b35' }
              return (
                <div key={i} className="iss-card" style={{ cursor: 'pointer', borderLeft: `3px solid ${type.color}` }} onClick={() => a.lon != null && a.lat != null && onFocus({ kind: 'gdacs', lon: a.lon, lat: a.lat, height: 400000, title: a.title, lines: [a.description?.slice(0, 120) || ''] })}>
                  <span style={{ color: type.color, fontWeight: 'bold' }}>{type.label}</span>
                  <strong>{a.title}</strong>
                  <small style={{ color: '#6f8c84' }}>{a.published?.slice(0, 16) || ''}</small>
                  {a.link && <a className="tp-link" href={a.link} target="_blank" rel="noreferrer">OPEN SOURCE ↗</a>}
                </div>
              )
            })}
          </div>
        </section>
      )}

      {tab === 'weather' && (
        <section>
          <button onClick={loadWeather} disabled={loading['weather']}>{loading['weather'] ? 'Loading…' : '↻ Refresh'}</button>
          {!weather && <div className="health-status pending">No weather data</div>}
          {weather && (
            <div className="iss-card">
              <strong>Point Weather ({weather.lat?.toFixed(2)}, {weather.lon?.toFixed(2)})</strong>
              <div>Timezone: {weather.timezone || '—'}</div>
              {weather.current && (
                <>
                  <div>Temperature: {weather.current.temperature_2m}{weather.units?.temperature_2m || '°C'}</div>
                  <div>Humidity: {weather.current.relative_humidity_2m}{weather.units?.relative_humidity_2m || '%'}</div>
                  <div>Wind: {weather.current.wind_speed_10m}{weather.units?.wind_speed_10m || 'km/h'} {weather.current.wind_direction_10m}°</div>
                  <div>Pressure: {weather.current.pressure_msl}{weather.units?.pressure_msl || 'hPa'}</div>
                </>
              )}
            </div>
          )}
        </section>
      )}

      {tab === 'wildfires' && (
        <section>
          <button onClick={loadWildfires} disabled={loading['wildfires']}>{loading['wildfires'] ? 'Loading…' : '↻ Refresh'}</button>
          <span className="data-count">{wildfires?.count || 0} thermal anomalies</span>
          {wildfires?.fires?.length === 0 && <div className="health-status pending">No active fires detected</div>}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {(wildfires?.fires || []).slice(0, 50).map((f: any, i: number) => {
              const color = f.confidence >= 80 ? '#ff2d00' : f.confidence >= 50 ? '#ff6b35' : '#ffd23f'
              return (
                <div key={i} className="iss-card" style={{ cursor: 'pointer', borderLeft: `3px solid ${color}` }} onClick={() => f.lon != null && f.lat != null && onFocus({ kind: 'wildfire', lon: f.lon, lat: f.lat, height: 400000, title: `Wildfire (${f.confidence_label})`, lines: [`Confidence: ${f.confidence}%`, `Brightness: ${f.brightness}K`, `FRP: ${f.frp} MW`, `Satellite: ${f.satellite}`, `Date: ${f.acq_date}`] })}>
                  <span style={{ color, fontWeight: 'bold' }}>{f.confidence_label?.toUpperCase()}</span>
                  <strong>Fire #{i + 1}</strong>
                  <small style={{ color: '#6f8c84' }}>{f.lat?.toFixed(2)}, {f.lon?.toFixed(2)} | {f.acq_date}</small>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {tab === 'lightning' && (
        <section>
          <button onClick={loadLightning} disabled={loading['lightning']}>{loading['lightning'] ? 'Loading…' : '↻ Refresh'}</button>
          <span className="data-count">{lightning?.count || 0} strikes (last ~10min)</span>
          {lightning?.strikes?.length === 0 && <div className="health-status pending">No recent lightning</div>}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {(lightning?.strikes || []).slice(0, 30).map((s: any, i: number) => (
              <div key={i} className="iss-card" style={{ borderLeft: '3px solid #22d3ee' }} onClick={() => s.lon != null && s.lat != null && onFocus({ kind: 'lightning', lon: s.lon, lat: s.lat, height: 400000, title: 'Lightning Strike', lines: [`Time: ${s.time}`, `Stations: ${s.stations}`, `Participants: ${s.participants}`] })}>
                <span style={{ color: '#22d3ee', fontWeight: 'bold' }}>⚡</span>
                <strong>{s.lat?.toFixed(2)}, {s.lon?.toFixed(2)}</strong>
                <small style={{ color: '#6f8c84' }}>{s.time}</small>
              </div>
            ))}
          </div>
        </section>
      )}

      {tab === 'energy' && (
        <section>
          <button onClick={loadEnergy} disabled={loading['energy']}>{loading['energy'] ? 'Loading…' : '↻ Refresh'}</button>
          {!energy && <div className="health-status pending">No energy data</div>}
          {energy && (
            <>
              <div className="iss-card">
                <strong>Germany — Live Generation</strong>
                <div>Total: {energy.total_generation_mw?.toLocaleString()} MW</div>
                <div>CO₂: {energy.co2_g_per_kwh} g/kWh</div>
                <div>Load: {energy.load?.latest_mw?.toLocaleString()} MW</div>
                <div>Price: {energy.day_ahead_price?.latest_eur_mwh} EUR/MWh</div>
              </div>
              <table className="data-table">
                <thead><tr><th>Source</th><th>MW</th><th>Share</th></tr></thead>
                <tbody>
                  {Object.entries(energy.generation || {}).map(([key, val]: [string, any]) => {
                    const share = energy.total_generation_mw ? ((val.latest_mw / energy.total_generation_mw) * 100).toFixed(1) : '—'
                    const color = ['solar', 'wind_onshore', 'wind_offshore', 'hydro', 'biomass'].includes(key) ? '#00e5a0' : ['natural_gas'].includes(key) ? '#ffd23f' : '#ff6b35'
                    return (
                      <tr key={key}>
                        <td style={{ textTransform: 'capitalize', color }}>{key.replace(/_/g, ' ')}</td>
                        <td>{val.latest_mw?.toLocaleString()}</td>
                        <td>{share}%</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </>
          )}
        </section>
      )}

      {tab === 'stocks' && (
        <section>
          <button onClick={loadStocks} disabled={loading['stocks']}>{loading['stocks'] ? 'Loading…' : '↻ Refresh'}</button>
          <span className="data-count">{stocks?.count || 0} quotes</span>
          {!stocks?.quotes?.length && <div className="health-status pending">No market data</div>}
          <table className="data-table">
            <thead><tr><th>Asset</th><th>Price</th><th>Change</th><th>%</th></tr></thead>
            <tbody>
              {(stocks?.quotes || []).map((q: any, i: number) => (
                <tr key={i}>
                  <td><strong>{q.label}</strong><br/><small>{q.name}</small></td>
                  <td>{q.price} {q.currency}</td>
                  <td style={{ color: q.change >= 0 ? '#00e5a0' : '#ff2d00' }}>{q.change >= 0 ? '+' : ''}{q.change}</td>
                  <td style={{ color: q.change_pct >= 0 ? '#00e5a0' : '#ff2d00' }}>{q.change_pct >= 0 ? '+' : ''}{q.change_pct}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'transit' && (
        <section>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
            <select className="poi-select" value={transitCity} onChange={(e) => setTransitCity(e.target.value)}>
              <option value="helsinki">Helsinki (HSL)</option>
              <option value="boston">Boston (MBTA)</option>
              <option value="berlin">Berlin (VBB)</option>
              <option value="hamburg">Hamburg (HVV)</option>
              <option value="munich">Munich (MVV)</option>
            </select>
            <button onClick={loadTransit} disabled={loading['transit']}>{loading['transit'] ? 'Loading…' : '↻ Refresh'}</button>
          </div>
          {transit?.error && <div className="data-error">{transit.error}</div>}
          <span className="data-count">{transit?.count ?? 0} vehicles · {transitCity.toUpperCase()}</span>
          {!transit?.vehicles?.length && !transit?.error && <div className="health-status pending">No transit data — select a city with configured GTFS-Realtime endpoint</div>}
          <table className="data-table clickable">
            <thead><tr><th>Route</th><th>ID</th><th>Lat</th><th>Lon</th><th>Bearing</th><th>Speed</th><th></th></tr></thead>
            <tbody>
              {(transit?.vehicles || []).slice(0, 100).map((v: any, i: number) => (
                <tr key={i} onClick={() => v.lon != null && v.lat != null && onFocus({ kind: 'transit', lon: v.lon, lat: v.lat, height: 200000, title: `Transit ${v.route_id || '—'}`, lines: [`ID: ${v.id || '—'}`, `Route: ${v.route_id || '—'}`, `Bearing: ${v.bearing ?? '—'}°`, `Speed: ${v.speed != null ? v.speed + ' m/s' : '—'}`, `Label: ${v.label || '—'}`] })}>
                  <td><strong>{v.route_id || '—'}</strong></td>
                  <td>{v.id?.slice(0, 20) || '—'}</td>
                  <td>{v.lat?.toFixed(4) ?? '—'}</td>
                  <td>{v.lon?.toFixed(4) ?? '—'}</td>
                  <td>{v.bearing != null ? v.bearing + '°' : '—'}</td>
                  <td>{v.speed != null ? v.speed + ' m/s' : '—'}</td>
                  <td className="locate-cell">◎ LOCATE</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'maritime' && (
        <section>
          <button onClick={loadMaritime} disabled={loading['maritime']}>{loading['maritime'] ? 'Loading…' : '↻ Refresh'}</button>
          {maritime?.demo_mode && <div className="health-status pending" style={{ marginTop: 8 }}>⚠ DEMO MODE — live AIS sources unavailable</div>}
          {maritime?.error && !maritime.demo_mode && <div className="data-error">{maritime.error}</div>}
          <span className="data-count">{maritime?.count ?? 0} vessels</span>
          {!maritime?.vessels?.length && <div className="health-status pending">No vessel data</div>}
          <table className="data-table clickable">
            <thead><tr><th>Name</th><th>Type</th><th>Lat</th><th>Lon</th><th>Course</th><th>Speed</th><th>Destination</th><th></th></tr></thead>
            <tbody>
              {(maritime?.vessels || []).slice(0, 100).map((v: any, i: number) => (
                <tr key={i} onClick={() => v.lon != null && v.lat != null && onFocus({ kind: 'maritime', lon: v.lon, lat: v.lat, height: 200000, title: v.name || 'Vessel', lines: [`MMSI: ${v.mmsi || '—'}`, `Type: ${v.type || '—'}`, `Course: ${v.course ?? '—'}°`, `Speed: ${v.speed != null ? v.speed + ' kn' : '—'}`, `Destination: ${v.destination || '—'}`, `Flag: ${v.flag || '—'}`, `Length: ${v.length != null ? v.length + ' m' : '—'}`] })}>
                  <td><strong>{v.name || '—'}</strong></td>
                  <td>{v.type || '—'}</td>
                  <td>{v.lat?.toFixed(4) ?? '—'}</td>
                  <td>{v.lon?.toFixed(4) ?? '—'}</td>
                  <td>{v.course != null ? v.course + '°' : '—'}</td>
                  <td>{v.speed != null ? v.speed + ' kn' : '—'}</td>
                  <td>{v.destination || '—'}</td>
                  <td className="locate-cell">◎ LOCATE</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === 'eu-energy' && (
        <section>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
            <select className="poi-select" value={euCountry} onChange={(e) => setEuCountry(e.target.value)}>
              <option value="de">Germany</option>
              <option value="fr">France</option>
              <option value="nl">Netherlands</option>
              <option value="at">Austria</option>
              <option value="pl">Poland</option>
              <option value="es">Spain</option>
              <option value="it">Italy</option>
              <option value="se">Sweden</option>
              <option value="dk">Denmark</option>
              <option value="no">Norway</option>
              <option value="be">Belgium</option>
              <option value="ch">Switzerland</option>
              <option value="cz">Czechia</option>
              <option value="fi">Finland</option>
            </select>
            <button onClick={loadEuEnergy} disabled={loading['eu-energy']}>{loading['eu-energy'] ? 'Loading…' : '↻ Refresh'}</button>
          </div>
          {euEnergy?.demo_mode && <div className="health-status pending">⚠ DEMO MODE — set ENTSOE_SECURITY_TOKEN for live data</div>}
          {euEnergy?.error && !euEnergy.demo_mode && <div className="data-error">{euEnergy.error}</div>}
          {euEnergy?.prices && (
            <>
              <div className="iss-card" style={{ marginBottom: 8 }}>
                <strong>{euCountry.toUpperCase()} — Day Ahead Prices (EUR/MWh)</strong>
                <div style={{ marginTop: 4, fontSize: 12, color: '#6f8c84' }}>
                  {euEnergy.prices.length} hourly slots
                </div>
              </div>
              <table className="data-table">
                <thead><tr><th>Hour</th><th>Price</th><th>Status</th></tr></thead>
                <tbody>
                  {euEnergy.prices.slice(0, 24).map((p: any, i: number) => {
                    const price = p.price_eur_mwh ?? 0
                    const color = price < 0 ? '#22d3ee' : price < 50 ? '#00e5a0' : price < 100 ? '#ffd23f' : price < 200 ? '#ff6b35' : '#ff2d00'
                    const label = price < 0 ? 'NEGATIVE' : price < 50 ? 'Low' : price < 100 ? 'Normal' : price < 200 ? 'High' : 'Extreme'
                    return (
                      <tr key={i}>
                        <td>{p.position}</td>
                        <td style={{ color, fontWeight: 'bold' }}>{price.toFixed(2)}</td>
                        <td style={{ color }}>{label}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </>
          )}
          {euEnergy?.generation_by_source && (
            <div style={{ marginTop: 12 }}>
              <div className="iss-card"><strong>Generation Mix — Latest Hour</strong></div>
              <table className="data-table">
                <thead><tr><th>Source</th><th>MW</th><th>Share</th></tr></thead>
                <tbody>
                  {Object.entries(euEnergy.generation_by_source).map(([key, val]: [string, any]) => {
                    const share = euEnergy.total_mw ? ((val / euEnergy.total_mw) * 100).toFixed(1) : '—'
                    const color = ['Solar', 'Wind Offshore', 'Wind Onshore', 'Hydro Run-of-river', 'Hydro Water Reservoir', 'Biomass', 'Geothermal'].includes(key) ? '#00e5a0' : ['Nuclear'].includes(key) ? '#ffd23f' : '#ff6b35'
                    return (
                      <tr key={key}>
                        <td style={{ color }}>{key}</td>
                        <td>{val.toLocaleString()}</td>
                        <td>{share}%</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          {!euEnergy?.prices?.length && !euEnergy?.error && <div className="health-status pending">No EU energy data</div>}
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
  const [providers, setProviders] = useState<{ id: string; name: string; models: string[]; requires_key: boolean }[]>([])
  const [provider, setProvider] = useState('ollama')
  const [models, setModels] = useState<{ name: string; parameter_size?: string }[]>([])
  const [model, setModel] = useState('')
  const [busy, setBusy] = useState(false)
  const [modelErr, setModelErr] = useState<string | null>(null)
  const [webSearch, setWebSearch] = useState(false)
  const [firewall, setFirewall] = useState(false)

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

    fetch('/api/providers')
      .then((r) => r.json())
      .then((d) => {
        const list = d.providers || []
        setProviders(list)
      })
      .catch(() => {})
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
          provider,
          search_results: combinedSearchResults,
          firewall,
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
            if (data.firewall_blocked) {
              setHistory((h) => {
                const copy = [...h]
                copy[copy.length - 1] = { role: 'assistant', content: data.message?.content || 'Blocked by firewall.' }
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

  const isOllama = provider === 'ollama'
  const providerModels = providers.find((p) => p.id === provider)?.models || []

  return (
    <div className="panel chat">
      <h2>WorldBase AI</h2>

      {modelErr && <div className="data-error">{modelErr}</div>}

      <div className="model-select">
        <select
          value={provider}
          onChange={(e) => {
            const pid = e.target.value
            setProvider(pid)
            const p = providers.find((x) => x.id === pid)
            if (p && p.models.length > 0) {
              setModel(p.models[0])
            } else if (pid === 'ollama' && models.length > 0) {
              setModel(models[0].name)
            }
          }}
          style={{ marginRight: 6 }}
        >
          {providers.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>

        {isOllama ? (
          <select value={model} onChange={(e) => setModel(e.target.value)} disabled={models.length === 0}>
            {models.length === 0 && <option value="">No models found</option>}
            {models.map((m) => (
              <option key={m.name} value={m.name}>
                {m.name} {m.parameter_size ? `(${m.parameter_size})` : ''}
              </option>
            ))}
          </select>
        ) : (
          <>
            <input
              list={`models-${provider}`}
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="model name"
              style={{ width: 180, fontSize: 12 }}
            />
            <datalist id={`models-${provider}`}>
              {providerModels.map((m) => (
                <option key={m} value={m} />
              ))}
            </datalist>
          </>
        )}

        <button
          className={webSearch ? 'web-search on' : 'web-search'}
          onClick={() => setWebSearch((v) => !v)}
          title="Toggle web search (injects DuckDuckGo results as context)"
        >
          {webSearch ? '🔍 ON' : '🔍 OFF'}
        </button>
        <button
          className={firewall ? 'web-search on' : 'web-search'}
          onClick={() => setFirewall((v) => !v)}
          title="Toggle LLM-Security-Firewall (scans prompts via external HAK_GAL service)"
          style={{ marginLeft: 6, color: firewall ? '#ff2d00' : '#6f8c84' }}
        >
          {firewall ? '🛡️ ON' : '🛡️ OFF'}
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
          placeholder={model ? `Ask ${model} (${provider})…` : 'Select a model first…'}
          disabled={!model}
        />
        <button onClick={() => sendWithMessage(msg.trim())} disabled={busy || !model}>
          Send
        </button>
      </div>
    </div>
  )
}

function OsintPanel({ onFocus }: { onFocus: (f: Omit<FocusTarget, 'ts'>) => void }) {
  const [tool, setTool] = useState<'ip' | 'domain' | 'username' | 'email' | 'reverse'>('ip')
  const [query, setQuery] = useState('')
  const [latInput, setLatInput] = useState('')
  const [lonInput, setLonInput] = useState('')
  const [result, setResult] = useState<any>(null)
  const [busy, setBusy] = useState(false)

  async function runLookup() {
    setBusy(true)
    setResult(null)
    try {
      let url = ''
      if (tool === 'ip') url = `/api/osint/ip/${encodeURIComponent(query)}`
      else if (tool === 'domain') url = `/api/osint/domain/${encodeURIComponent(query)}`
      else if (tool === 'username') url = `/api/osint/username/${encodeURIComponent(query)}`
      else if (tool === 'email') url = `/api/osint/email/${encodeURIComponent(query)}`
      else if (tool === 'reverse') url = `/api/osint/reverse-geocode?lat=${latInput}&lon=${lonInput}`
      const r = await fetch(url)
      const d = await r.json()
      setResult(d)
    } catch (e) {
      setResult({ error: String(e) })
    } finally {
      setBusy(false)
    }
  }

  const showOnGlobe = (lat: number, lon: number, title: string, lines: string[]) => {
    onFocus({ kind: 'osint', lat, lon, height: 400000, title, lines })
  }

  const tools = [
    { id: 'ip' as const, label: 'IP' },
    { id: 'domain' as const, label: 'DOMAIN' },
    { id: 'username' as const, label: 'USERNAME' },
    { id: 'email' as const, label: 'EMAIL' },
    { id: 'reverse' as const, label: 'REVERSE GEO' },
  ]

  return (
    <div className="panel osint" style={{ padding: '0 18px' }}>
      <h2>OSINT Reconnaissance</h2>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
        {tools.map(t => (
          <button
            key={t.id}
            className={tool === t.id ? 'active' : ''}
            style={{
              padding: '6px 14px',
              fontSize: 11,
              fontFamily: 'monospace',
              background: tool === t.id ? 'rgba(0,229,160,0.2)' : 'rgba(0,229,160,0.05)',
              border: tool === t.id ? '1px solid #00e5a0' : '1px solid rgba(0,229,160,0.2)',
              color: tool === t.id ? '#00e5a0' : '#6f8c84',
              cursor: 'pointer',
            }}
            onClick={() => { setTool(t.id); setResult(null) }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tool === 'reverse' ? (
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <input
            style={{ flex: 1 }}
            placeholder="lat"
            value={latInput}
            onChange={e => setLatInput(e.target.value)}
          />
          <input
            style={{ flex: 1 }}
            placeholder="lon"
            value={lonInput}
            onChange={e => setLonInput(e.target.value)}
          />
          <button onClick={runLookup} disabled={busy}>{busy ? '…' : 'SEARCH'}</button>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
          <input
            style={{ flex: 1 }}
            placeholder={`Enter ${tool}…`}
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && runLookup()}
          />
          <button onClick={runLookup} disabled={busy}>{busy ? '…' : 'SEARCH'}</button>
        </div>
      )}

      {busy && <div style={{ color: '#6f8c84', fontSize: 12 }}>Querying…</div>}
      {result?.error && <div className="data-error">{result.error}</div>}

      {result && !result.error && (
        <div className="osint-result" style={{ marginTop: 10 }}>
          {tool === 'ip' && result.lat != null && result.lon != null && (
            <button
              className="locate-mini"
              onClick={() => showOnGlobe(result.lat, result.lon, `IP ${result.ip}`, [
                `Country: ${result.country || '—'}`,
                `Region: ${result.region || '—'}`,
                `City: ${result.city || '—'}`,
                `ISP: ${result.isp || '—'}`,
                `ASN: ${result.asn || '—'}`,
              ])}
            >
              ◎ SHOW ON GLOBE
            </button>
          )}
          {tool === 'reverse' && result.locality && (
            <button
              className="locate-mini"
              onClick={() => showOnGlobe(result.lat, result.lon, result.locality, [
                `City: ${result.city || '—'}`,
                `Region: ${result.region || '—'}`,
                `Country: ${result.country || '—'}`,
              ])}
            >
              ◎ SHOW ON GLOBE
            </button>
          )}

          <pre style={{ fontSize: 11, color: '#b0c4b1', background: 'rgba(0,0,0,0.3)', padding: 10, borderRadius: 6, overflowX: 'auto', maxHeight: 'calc(100vh - 300px)', overflowY: 'auto' }}>
            {JSON.stringify(result, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}
