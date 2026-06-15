import { useState, useEffect, useRef } from 'react'
import Globe from './components/Globe'
import MapPanel from './components/MapPanel'
import ChatPanel from './components/ChatPanel'
import OsintPanel from './components/OsintPanel'
import DataPanel from './components/DataPanel'
import FirewallPanel from './components/FirewallPanel'
import SituationBoard from './components/SituationBoard'
import type { FocusTarget } from './lib/focus'
import type { OsintPin } from './lib/osintPins'
import { loadOsintPins, saveOsintPins, mergeImportedPins } from './lib/osintPins'
import MapModeBar from './components/MapModeBar'
import { DEFAULT_MAP_VIEW, type MapViewMode } from './lib/mapView'
import { fetchApi } from './lib/networkFetch';

type ViewId = 'globe' | 'map' | 'data' | 'chat' | 'firewall' | 'osint'

const NAV_ITEMS: { id: ViewId; label: string; glyph: string }[] = [
  { id: 'globe', label: 'GLOBE', glyph: '◎' },
  { id: 'map', label: 'MAP', glyph: '▦' },
  { id: 'data', label: 'DATA', glyph: '▤' },
  { id: 'chat', label: 'AI', glyph: '✦' },
  { id: 'firewall', label: 'FIREWALL', glyph: '🛡️' },
  { id: 'osint', label: 'OSINT', glyph: '⌖' },
]


function useAlertNotifications() {
  const lastNotifiedRef = useRef<number>(0)

  useEffect(() => {
    if (!('Notification' in window)) return
    // Don't request permission on mount automatically. Let the user do it.
    // if (Notification.permission === 'default') {
    //   Notification.requestPermission()
    // }

    const check = async () => {
      if (Notification.permission !== 'granted') return
      try {
        const [corrRes, anomRes, energyRes] = await Promise.all([
          fetchApi('/api/correlations').then(r => r.ok ? r.json() : null),
          fetchApi('/api/anomalies').then(r => r.ok ? r.json() : null),
          fetchApi('/api/energy/de').then(r => r.ok ? r.json() : null),
        ])
        const now = Date.now()
        if (now - lastNotifiedRef.current < 300000) return // 5 min cooldown
        const situations = corrRes?.situations || []
        const anomalies = anomRes?.anomalies || []
        const price = energyRes?.day_ahead_price?.latest_eur_mwh
        const titles: string[] = [
          ...situations.map((s: any) => s.title),
          ...anomalies.slice(0, 3).map((a: any) => `Anomaly ${a.callsign || a.icao24}`),
        ]
        if (price != null && price < 0) {
          titles.unshift(`DE power price negative: ${price.toFixed(1)} €/MWh`)
        }
        if (titles.length > 0) {
          new Notification('WorldBase Alert', {
            body: titles.join(' | '),
            icon: '/favicon.ico',
            tag: price != null && price < 0 ? 'worldbase-energy' : 'worldbase-alert',
          })
          lastNotifiedRef.current = now
        }
      } catch {
        // ignore
      }
    }

    check()
    const t = setInterval(check, 60000)
    return () => clearInterval(t)
  }, [])
}
function HudClock() {
  const [now, setNow] = useState(new Date())
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])
  const utc = now.toISOString().slice(11, 19)
  return (
    <div className="hud-clock">
      <span className="clock-time">{utc}</span>
      <span className="clock-zone">UTC</span>
    </div>
  )
}

function SystemStatus() {
  const [backend, setBackend] = useState<'online' | 'offline' | 'check'>('check')
  const [ollama, setOllama] = useState<'online' | 'offline' | 'check'>('check')

  useEffect(() => {
    const ping = async () => {
      try {
        const r = await fetchApi('/api/health/ping')
        setBackend(r.ok ? 'online' : 'offline')
      } catch { setBackend('offline') }
      try {
        const r = await fetchApi('/api/models')
        const d = await r.json()
        setOllama(d.error ? 'offline' : 'online')
      } catch { setOllama('offline') }
    }
    ping()
    const onOnline = () => { ping() }
    window.addEventListener('online', onOnline)
    const t = setInterval(ping, 60000)
    return () => {
      clearInterval(t)
      window.removeEventListener('online', onOnline)
    }
  }, [])

  return (
    <div className="sys-status">
      <span className={`sys-pip ${backend}`} />BACKEND
      <span className={`sys-pip ${ollama}`} />OLLAMA
    </div>
  )
}

export default function App() {
  const [view, setView] = useState<ViewId>('globe')
  const [splitView, setSplitView] = useState(false)
  const [booting, setBooting] = useState(true)
  const [focus, setFocus] = useState<FocusTarget | null>(null)
  const askAIIdRef = useRef(0)
  const [askAI, setAskAI] = useState<{ id: number; question: string; context: string } | null>(null)
  const [analysisOpen, setAnalysisOpen] = useState(false)
  const [situationOpen, setSituationOpen] = useState(false)
  const [firewallHistory, setFirewallHistory] = useState<any[]>([])
  const [osintPins, setOsintPins] = useState<OsintPin[]>(() => loadOsintPins())
  const [syncCamera, setSyncCamera] = useState<{ lon: number; lat: number; height?: number; zoom?: number; pitch?: number; source: 'globe' | 'map'; ts: number } | null>(null)
  const [mapMode, setMapMode] = useState<MapViewMode>(DEFAULT_MAP_VIEW)
  useAlertNotifications()

  useEffect(() => {
    saveOsintPins(osintPins)
  }, [osintPins])

  const addOsintPin = (pin: Omit<OsintPin, 'ts'>) => {
    setOsintPins((prev) => {
      const next = [...prev.filter((p) => p.id !== pin.id), { ...pin, ts: Date.now() }]
      return next.slice(-24)
    })
  }

  const clearOsintPins = () => setOsintPins([])

  const focusOnMap = (f: Omit<FocusTarget, 'ts'>) => {
    setFocus({ ...f, ts: Date.now() })
    // Stay on map view if user already opened it; otherwise default to globe.
    setView((prev) => (prev === 'map' ? 'map' : 'globe'))
  }

  const handleGlobeMove = (cam: { lon: number; lat: number; height: number; pitch?: number }) => {
    if (view === 'map' || splitView) {
      setSyncCamera({ ...cam, source: 'globe', ts: Date.now() })
    }
  }

  const handleMapMove = (cam: { lon: number; lat: number; zoom: number; pitch?: number }) => {
    if (view === 'globe' || splitView) {
      setSyncCamera({ ...cam, source: 'map', ts: Date.now() })
    }
  }

  const showMapChrome = splitView || view === 'globe' || view === 'map'

  const handleAskAI = (title: string, lines: string[]) => {
    const context = [`Entity: ${title}`, ...lines.filter(Boolean)].join('\n')
    const question = 'Analyze this target and tell me what it means for the current world situation.'
    askAIIdRef.current += 1
    setAskAI({ id: askAIIdRef.current, question, context })
    setView('chat')
  }

  const globeVisible = splitView || view === 'globe'

  const mapVisible = splitView || view === 'map'

  const globeSharedProps = {
    focus,
    onAskAI: handleAskAI,
    osintPins,
    onClearOsintPins: clearOsintPins,
    onCameraMove: handleGlobeMove,
    syncCamera,
    mapMode,
    layoutSplit: splitView,
    visible: globeVisible,
  }

  const mapPanelProps = {
    focus: focus ? { lat: focus.lat, lon: focus.lon, ts: focus.ts } : null,
    onCameraMove: handleMapMove,
    syncCamera,
    mapMode,
    visible: mapVisible,
    layoutSplit: splitView,
  }

  const toggleSplitView = () => {
    setSplitView((on) => {
      const next = !on
      if (next && view !== 'globe' && view !== 'map') setView('globe')
      return next
    })
  }

  useEffect(() => {
    const t = setTimeout(() => setBooting(false), 800)
    return () => clearTimeout(t)
  }, [])

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
              className={view === n.id || (splitView && n.id === 'globe') ? 'active' : ''}
              onClick={() => {
                if (n.id === 'data' || n.id === 'firewall' || n.id === 'osint' || n.id === 'chat') {
                  setSplitView(false)
                }
                setView(n.id)
              }}
            >
              <span className="nav-glyph">{n.glyph}</span>
              {n.label}
            </button>
          ))}
          <button className={splitView ? 'active' : ''} onClick={toggleSplitView} style={{ marginLeft: 16 }}>
            ◫ SPLIT
          </button>
        </nav>

        <div className="hud-meta">
          <button className="mega-analysis-btn" onClick={() => setSituationOpen(true)}>SITUATIONS</button>
          <button className="mega-analysis-btn secondary" onClick={() => setAnalysisOpen(true)}>FULL SITUATION</button>
          <SystemStatus />
          <HudClock />
        </div>
      </header>

      {situationOpen && (
        <SituationBoard
          onClose={() => setSituationOpen(false)}
          onFocus={focusOnMap}
          osintPins={osintPins}
          onAddPin={addOsintPin}
          onAskAI={handleAskAI}
        />
      )}
      {analysisOpen && <FullAnalysisOverlay onClose={() => setAnalysisOpen(false)} onFocus={focusOnMap} />}

      <main className={splitView ? 'hud-main hud-main--split' : 'hud-main'}>
        <div
          className={[
            'view-layer',
            'globe-layer',
            globeVisible ? 'view-layer--active' : 'view-layer--hidden',
          ].join(' ')}
        >
          <Globe {...globeSharedProps} />
        </div>

        {splitView ? null : view !== 'globe' && view !== 'map' ? (
          <div key={view} className="view-fade">
            {view === 'data' && <DataPanel onFocus={focusOnMap} />}
            {view === 'chat' && (
              <ChatPanel
                askAI={askAI}
                onClearAsk={() => setAskAI(null)}
                onFirewallResult={(r) => setFirewallHistory((h) => [r, ...h].slice(0, 100))}
                onClientAction={(act) => {
                  if (act?.type === 'focus_globe' && act.lat != null && act.lon != null) {
                    focusOnMap({
                      kind: act.kind || 'ai_focus',
                      lat: act.lat,
                      lon: act.lon,
                      height: 400000,
                      title: act.title || 'AI focus',
                      lines: act.lines || [],
                    })
                  }
                }}
              />
            )}
            {view === 'firewall' && <FirewallPanel history={firewallHistory} />}
            {view === 'osint' && (
              <OsintPanel
                onFocus={focusOnMap}
                onAddPin={addOsintPin}
                onImportPins={(pins) => setOsintPins((prev) => mergeImportedPins(prev, pins))}
                pinCount={osintPins.length}
              />
            )}
          </div>
        ) : null}

        <div
          className={[
            'map-pane',
            splitView ? 'map-pane--split' : 'map-pane--overlay',
            mapVisible ? 'map-pane--visible' : 'map-pane--hidden',
          ].join(' ')}
        >
          <MapPanel {...mapPanelProps} />
        </div>

        {showMapChrome && (
          <MapModeBar
            mode={mapMode}
            onChange={setMapMode}
            compact={splitView}
            onRequestGlobe={() => {
              if (!splitView && view === 'map') setView('globe')
            }}
          />
        )}
      </main>
    </div>
  )
}

function fmtFeedAge(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec)) return '—'
  if (sec < 60) return `${Math.round(sec)}s`
  if (sec < 3600) return `${Math.round(sec / 60)}m`
  return `${(sec / 3600).toFixed(1)}h`
}

function feedHealthStyle(v: { status?: string; fresh?: boolean; age_sec?: number }) {
  const st = v.status || (v.fresh ? 'fresh' : 'stale')
  if (st === 'fresh') return { border: '#00e5a0', color: '#00e5a0', label: 'FRESH' }
  if (st === 'warn') return { border: '#ffd23f', color: '#ffd23f', label: 'WARN' }
  if (st === 'stale') return { border: '#ff6b35', color: '#ff6b35', label: 'STALE' }
  return { border: '#6f8c84', color: '#6f8c84', label: '—' }
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
        { key: 'cve', url: '/api/cve?limit=15' },
        { key: 'pegel', url: '/api/pegel' },
      ]
      const out: any = {}
      await Promise.all(endpoints.map(async (ep) => {
        try {
          const r = await fetchApi(ep.url)
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
  const cveFeed = results.cve
  const quakes = (results.earthquakes?.earthquakes || []).slice(0, 15)
  const wildfires = (results.events?.events || []).filter((e: any) => (e.category || '').toLowerCase().includes('fire') || (e.title || '').toLowerCase().includes('fire')).slice(0, 8)
  const allEvents = (results.events?.events || []).filter((e: any) => !((e.category || '').toLowerCase().includes('fire') || (e.title || '').toLowerCase().includes('fire'))).slice(0, 10)
  const military = results.military
  const gdacs = (results.gdacs?.alerts || []).slice(0, 15)
  const anomalies = results.anomalies
  const air = results.airquality
  const pegel = results.pegel
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

              {nodes?.nodes?.some((n: any) => (n.health?.disk_pct ?? 0) >= 85) && (
                <div className="analysis-section critical">
                  <h3>⚠ EDGE NODE DISK</h3>
                  {nodes.nodes.filter((n: any) => (n.health?.disk_pct ?? 0) >= 85).map((n: any, i: number) => (
                    <div key={i} className="analysis-row" style={{ borderLeft: '3px solid #ffd23f' }}>
                      <span style={{ color: '#ffd23f', fontWeight: 'bold' }}>DISK</span>
                      <span>{n.name}: {n.health?.disk_pct}% — run `sudo bash ~/pi-disk-maintenance.sh` on Pi</span>
                    </div>
                  ))}
                </div>
              )}

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

              {(cveFeed?.vulnerabilities?.length ?? 0) > 0 && (
                <div className="analysis-section">
                  <h3>🔐 CISA KEV ({cveFeed.vulnerabilities.length})</h3>
                  {cveFeed.vulnerabilities.slice(0, 8).map((v: any, i: number) => (
                    <div key={i} className="analysis-row" style={{ borderLeft: `3px solid ${v.ransomware === 'Known' ? '#ff2d00' : '#ff6b35'}` }}>
                      <span style={{ fontWeight: 'bold', minWidth: 120 }}>{v.cve_id}</span>
                      <span style={{ flex: 1 }}>{v.vendor} — {v.product}</span>
                      <span style={{ color: '#6f8c84', fontSize: 10 }}>due {v.due_date || '—'}</span>
                    </div>
                  ))}
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

              {(pegel?.gauges?.length ?? 0) > 0 && (
                <div className="analysis-section">
                  <h3>🌊 RIVER GAUGES DE ({pegel.gauges.length})</h3>
                  {pegel.gauges.filter((g: any) => g.severity === 'critical' || g.severity === 'high').map((g: any, i: number) => (
                    <div key={`a-${i}`} className="analysis-row" style={{ borderLeft: '3px solid #ff6b35' }}>
                      <span style={{ fontWeight: 'bold', minWidth: 100 }}>{g.name}</span>
                      <span style={{ minWidth: 60 }}>{g.water}</span>
                      <span>{g.value} {g.unit}</span>
                      <span style={{ color: '#ff6b35' }}>{g.severity}</span>
                      <button className="locate-mini" onClick={() => { onClose(); onFocus({ kind: 'pegel', lon: g.lon, lat: g.lat, height: 350000, title: `${g.name} (${g.water})`, lines: [`Level: ${g.value} ${g.unit}`, `State: ${g.state_mnw_mhw || '—'} / ${g.state_nsw_hsw || '—'}`] }) }}>◎</button>
                    </div>
                  ))}
                  {pegel.gauges.filter((g: any) => g.severity === 'normal' || g.severity === 'low').slice(0, 6).map((g: any, i: number) => (
                    <div key={`n-${i}`} className="analysis-row" style={{ borderLeft: '3px solid #4fc3f7' }}>
                      <span style={{ fontWeight: 'bold', minWidth: 100 }}>{g.name}</span>
                      <span style={{ minWidth: 60 }}>{g.water}</span>
                      <span>{g.value} {g.unit}</span>
                      <button className="locate-mini" onClick={() => { onClose(); onFocus({ kind: 'pegel', lon: g.lon, lat: g.lat, height: 350000, title: `${g.name} (${g.water})`, lines: [`Level: ${g.value} ${g.unit}`] }) }}>◎</button>
                    </div>
                  ))}
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
                  {nodes.nodes.map((n: any, i: number) => {
                    const disk = n.health?.disk_pct
                    const diskWarn = disk != null && disk >= 85
                    return (
                    <div key={i} className="analysis-row" style={{ borderLeft: n.online ? (diskWarn ? '3px solid #ffd23f' : '3px solid #00e5a0') : '3px solid #ff2d00' }}>
                      <span style={{ fontWeight: 'bold' }}>{n.name}</span>
                      <span style={{ color: n.online ? '#00e5a0' : '#ff2d00' }}>{n.online ? 'ONLINE' : 'OFFLINE'}</span>
                      <span style={{ color: '#6f8c84' }}>{Math.round(n.age_seconds || 0)}s ago</span>
                      <span style={{ color: '#6f8c84' }}>CPU: {n.health?.cpu_temp_c != null ? n.health.cpu_temp_c + '°C' : '—'}</span>
                      <span style={{ color: '#6f8c84' }}>Load: {n.health?.load_1m != null ? n.health.load_1m : '—'}</span>
                      <span style={{ color: '#6f8c84' }}>RAM: {n.health?.ram_pct != null ? n.health.ram_pct + '%' : '—'}</span>
                      <span style={{ color: diskWarn ? '#ffd23f' : '#6f8c84', fontWeight: diskWarn ? 'bold' : 'normal' }}>Disk: {disk != null ? disk + '%' : '—'}{diskWarn ? ' ⚠' : ''}</span>
                      {n.lat && (
                        <button className="locate-mini" onClick={() => { onClose(); onFocus({ kind: 'node', lon: n.lon, lat: n.lat, height: 400000, title: n.name, lines: [`Node: ${n.node_id}`, `CPU: ${n.health?.cpu_temp_c ?? '—'}°C`, `RAM: ${n.health?.ram_pct ?? '—'}%`, `Disk: ${disk ?? '—'}%`] }) }}>◎</button>
                      )}
                    </div>
                  )})}
                </div>
              )}

              {health?.feeds && (
                <div className="analysis-section">
                  <h3>🔌 FEED HEALTH</h3>
                  <div className="analysis-grid">
                    {Object.entries(health.feeds)
                      .sort(([, a]: [string, any], [, b]: [string, any]) => (b.age_sec || 0) - (a.age_sec || 0))
                      .map(([k, v]: [string, any]) => {
                        const st = feedHealthStyle(v)
                        return (
                      <div key={k} className="analysis-card" style={{ borderLeft: `3px solid ${st.border}` }}>
                        <strong>{k}</strong>
                        <span style={{ color: st.color }}>{st.label} · {fmtFeedAge(v.age_sec)}</span>
                      </div>
                        )
                      })}
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









