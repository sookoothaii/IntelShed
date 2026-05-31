import { useState, useEffect } from 'react'
import Globe from './components/Globe'
import type { FocusTarget } from './lib/focus'

const NAV_ITEMS: { id: 'globe' | 'data' | 'chat'; label: string; glyph: string }[] = [
  { id: 'globe', label: 'GLOBE', glyph: '◎' },
  { id: 'data', label: 'DATA', glyph: '▤' },
  { id: 'chat', label: 'AI', glyph: '✦' },
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
  const [view, setView] = useState<'globe' | 'data' | 'chat'>('globe')
  const [booting, setBooting] = useState(true)
  const [focus, setFocus] = useState<FocusTarget | null>(null)
  const now = useClock()

  const focusOnMap = (f: Omit<FocusTarget, 'ts'>) => {
    setFocus({ ...f, ts: Date.now() })
    setView('globe')
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
          <SystemStatus />
          <div className="hud-clock">
            <span className="clock-time">{utc}</span>
            <span className="clock-zone">UTC</span>
          </div>
        </div>
      </header>

      <main className="hud-main">
        <div key={view} className="view-fade">
          {view === 'globe' && <Globe focus={focus} />}
          {view === 'data' && <DataPanel onFocus={focusOnMap} />}
          {view === 'chat' && <ChatPanel />}
        </div>
      </main>
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

const DATA_TABS = ['aircraft', 'satellites', 'seismic', 'events', 'iss', 'health'] as const
type DataTab = typeof DATA_TABS[number]

const SAT_GROUPS = ['starlink', 'stations', 'gps-ops', 'weather']

function DataPanel({ onFocus }: { onFocus: (f: Omit<FocusTarget, 'ts'>) => void }) {
  const [tab, setTab] = useState<DataTab>('aircraft')
  const [aircraft, setAircraft] = useState<(string | number | null)[][]>([])
  const [satellites, setSatellites] = useState<Sat[]>([])
  const [satGroup, setSatGroup] = useState('starlink')
  const [quakes, setQuakes] = useState<Quake[]>([])
  const [events, setEvents] = useState<WEvent[]>([])
  const [iss, setIss] = useState<any>(null)
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
  const loadHealth = () => fetchFeed('health', '/api/health', (d: any) => setHealth(d))

  // Auto-load on tab switch
  useEffect(() => {
    setQuery('')
    if (tab === 'aircraft') loadAircraft()
    else if (tab === 'satellites') loadSatellites()
    else if (tab === 'seismic') loadQuakes()
    else if (tab === 'events') loadEvents()
    else if (tab === 'iss') loadIss()
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

function ChatPanel() {
  const [msg, setMsg] = useState('')
  const [history, setHistory] = useState<{ role: string; content: string }[]>([
    { role: 'system', content: 'Select a model and start chatting.' },
  ])
  const [models, setModels] = useState<{ name: string; parameter_size?: string }[]>([])
  const [model, setModel] = useState('')
  const [busy, setBusy] = useState(false)
  const [modelErr, setModelErr] = useState<string | null>(null)

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

  async function send() {
    if (!msg.trim() || busy || !model) return
    const userMsg = msg.trim()
    setMsg('')
    setHistory((h) => [...h, { role: 'user', content: userMsg }])
    setBusy(true)

    try {
      const r = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: model,
          messages: [{ role: 'user', content: userMsg }],
        }),
      })
      const d = await r.json()
      if (d.error) {
        setHistory((h) => [...h, { role: 'assistant', content: 'Error: ' + d.error }])
      } else {
        const text = d.message?.content || d.response || JSON.stringify(d)
        setHistory((h) => [...h, { role: 'assistant', content: text }])
      }
    } catch (e) {
      setHistory((h) => [...h, { role: 'assistant', content: 'Error: ' + (e as Error).message }])
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
          onKeyDown={(e) => e.key === 'Enter' && send()}
          placeholder={model ? `Ask ${model}…` : 'Select a model first…'}
          disabled={!model}
        />
        <button onClick={send} disabled={busy || !model}>
          Send
        </button>
      </div>
    </div>
  )
}
