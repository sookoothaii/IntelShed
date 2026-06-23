import { useState, useEffect, useRef, useCallback, type ReactNode } from 'react'
import Globe from './components/Globe'
import MapPanel from './components/MapPanel'
import ChatPanel from './components/ChatPanel'
import OsintPanel from './components/OsintPanel'
import DataPanel from './components/DataPanel'
import NewsPanel from './components/NewsPanel'
import SituationBoard from './components/SituationBoard'
import { NodeHealthBanner } from './components/NodeHealthBanner'
import type { FocusTarget } from './lib/focus'
import type { OsintPin } from './lib/osintPins'
import { loadOsintPins, saveOsintPins, mergeImportedPins } from './lib/osintPins'
import WindyMapOverlay from './components/WindyMapOverlay'
import MapModeBar from './components/MapModeBar'
import { DEFAULT_MAP_VIEW, type MapViewMode } from './lib/mapView'
import { fetchApi, fetchApiWithTimeout } from './lib/networkFetch'
import { agentBusEnabled } from './lib/agentBus'
import { useAgentBus } from './hooks/useAgentBus'
import { useHudSessionState } from './lib/hudSessionState'

type ViewId = 'globe' | 'map' | 'data' | 'chat' | 'news' | 'osint'

const VIEW_IDS: ViewId[] = ['globe', 'map', 'data', 'chat', 'news', 'osint']

function isViewId(v: unknown): v is ViewId {
  return typeof v === 'string' && (VIEW_IDS as readonly string[]).includes(v as ViewId)
}

const BASEMAP_MODES = ['streets', 'satellite', 'hybrid', 'terrain'] as const

function isMapViewMode(v: unknown): v is MapViewMode {
  if (!v || typeof v !== 'object') return false
  const m = v as Record<string, unknown>
  return (
    BASEMAP_MODES.includes(m.basemap as typeof BASEMAP_MODES[number]) &&
    typeof m.render3d === 'boolean' &&
    typeof m.buildings === 'boolean' &&
    typeof m.photorealistic === 'boolean'
  )
}

function isBool(v: unknown): v is boolean {
  return typeof v === 'boolean'
}

const NAV_ITEMS: { id: ViewId; label: string; glyph: string }[] = [
  { id: 'globe', label: 'GLOBE', glyph: '◎' },
  { id: 'map', label: 'MAP', glyph: '▦' },
  { id: 'data', label: 'DATA', glyph: '▤' },
  { id: 'chat', label: 'AI', glyph: '✦' },
  { id: 'news', label: 'NEWS', glyph: '📰' },
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

type AgenticTrace = {
  enabled?: boolean
  rounds?: number
  max_rounds?: number
  status?: string
  phases?: Array<Record<string, unknown>>
  final_counts?: Record<string, number>
}

function agenticBadgeMeta(agentic: AgenticTrace | null | undefined): {
  label: string
  tip: string
  tone: 'ok' | 'warn' | 'off'
} | null {
  if (!agentic) return null
  if (agentic.enabled === false) {
    return { label: 'OFF', tip: 'Agentic loop disabled (BRIEFING_AGENTIC_LOOP=0)', tone: 'off' }
  }
  const rounds = agentic.rounds ?? 0
  const maxR = agentic.max_rounds ?? 3
  const phases = (agentic.phases || []).map((p) => String(p.phase || '')).filter(Boolean)
  const coverage = agentic.phases?.find((p) => p.phase === 'coverage') as Record<string, unknown> | undefined
  const gaps = Array.isArray(coverage?.gaps) ? coverage!.gaps.length : 0
  const retrieve = phases.includes('retrieve')
  const tip = [
    `Agentic loop ${rounds}/${maxR} rounds`,
    phases.length ? `phases: ${phases.join(' → ')}` : '',
    gaps ? `${gaps} bucket gap(s) at start` : 'coverage OK',
    retrieve ? 'RAG retrieve ran' : 'no retrieve (coverage sufficient)',
    agentic.status ? `status: ${agentic.status}` : '',
  ].filter(Boolean).join(' · ')
  return {
    label: `A${rounds}`,
    tip,
    tone: gaps && !retrieve ? 'warn' : 'ok',
  }
}

function useSituationsBadge() {
  const [badge, setBadge] = useState<{ label: string; tip: string; tone: 'ok' | 'warn' } | null>(null)
  useEffect(() => {
    const load = async () => {
      try {
        const r = await fetchApi('/api/situations')
        if (!r.ok) return
        const d = await r.json()
        const items = d.items || []
        const count = d.count ?? items.length
        if (count <= 0) {
          setBadge(null)
          return
        }
        const high = items.filter((i: { severity?: string }) =>
          i.severity === 'critical' || i.severity === 'high',
        ).length
        setBadge({
          label: String(count),
          tip: `${count} situation(s)${high > 0 ? ` · ${high} high/critical` : ''}`,
          tone: high > 0 ? 'warn' : 'ok',
        })
      } catch {
        // ignore
      }
    }
    load()
    const t = setInterval(load, 60000)
    return () => clearInterval(t)
  }, [])
  return badge
}

function useBriefingAgenticBadge() {
  const [agentic, setAgentic] = useState<AgenticTrace | null>(null)
  useEffect(() => {
    const load = async () => {
      try {
        const r = await fetchApi('/api/briefing')
        if (r.ok) {
          const d = await r.json()
          setAgentic(d.agentic ?? null)
        }
      } catch {
        // ignore
      }
    }
    load()
    const t = setInterval(load, 60000)
    return () => clearInterval(t)
  }, [])
  return agenticBadgeMeta(agentic)
}

function AgenticLoopPanel({ agentic }: { agentic: AgenticTrace }) {
  if (agentic.enabled === false) {
    return (
      <div className="analysis-section analysis-agentic">
        <h3>⟳ AGENTIC LOOP</h3>
        <div className="analysis-row" style={{ fontSize: 11, color: '#6f8c84' }}>
          Disabled — set BRIEFING_AGENTIC_LOOP=1 to enable coverage → retrieve → corroboration.
        </div>
      </div>
    )
  }
  const rounds = agentic.rounds ?? 0
  const maxR = agentic.max_rounds ?? 3
  const final = agentic.final_counts || {}
  return (
    <div className="analysis-section analysis-agentic">
      <h3>
        ⟳ AGENTIC LOOP{' '}
        <span className="analysis-agentic-rounds">
          {rounds}/{maxR}
        </span>
      </h3>
      {(agentic.phases || []).map((phase, i) => {
        const name = String(phase.phase || 'phase')
        if (name === 'coverage') {
          const counts = (phase.counts || {}) as Record<string, number>
          const gaps = Array.isArray(phase.gaps) ? phase.gaps : []
          return (
            <div key={i} className="analysis-agentic-phase">
              <span className="analysis-agentic-phase-label">COVERAGE</span>
              <span>
                L{counts.local ?? '—'} · R{counts.regional ?? '—'} · G{counts.global ?? '—'}
              </span>
              {gaps.length > 0 ? (
                <span className="analysis-agentic-warn">gaps: {gaps.join(', ')}</span>
              ) : (
                <span className="analysis-agentic-ok">OK</span>
              )}
            </div>
          )
        }
        if (name === 'retrieve') {
          const perBucket = (phase.per_bucket || {}) as Record<string, number>
          const retrieved = Number(phase.retrieved ?? 0)
          const errors = Array.isArray(phase.errors) ? phase.errors : []
          return (
            <div key={i} className="analysis-agentic-phase">
              <span className="analysis-agentic-phase-label">RETRIEVE</span>
              <span>{retrieved} line(s)</span>
              {Object.keys(perBucket).length > 0 && (
                <span style={{ color: '#8fb7a9' }}>
                  {Object.entries(perBucket).map(([b, n]) => `${b}:${n}`).join(' · ')}
                </span>
              )}
              {errors.length > 0 && (
                <span className="analysis-agentic-warn" title={errors.join('; ')}>
                  {errors.length} error(s)
                </span>
              )}
            </div>
          )
        }
        if (name === 'corroboration') {
          const summary = (phase.corroboration || {}) as Record<string, unknown>
          const avg = summary.corroboration_avg_local
          const weak = Number(phase.weak_local_lines ?? 0)
          const ragN = Number(phase.rag_corroborated ?? 0)
          return (
            <div key={i} className="analysis-agentic-phase">
              <span className="analysis-agentic-phase-label">CORROBORATE</span>
              {avg != null && (
                <span style={{ color: Number(avg) >= 0.75 ? '#00e5a0' : Number(avg) >= 0.5 ? '#ffd23f' : '#ff6b35' }}>
                  LOCAL {Math.round(Number(avg) * 100)}%
                </span>
              )}
              <span style={{ color: '#8fb7a9' }}>weak {weak} · RAG +{ragN}</span>
            </div>
          )
        }
        return null
      })}
      {Object.keys(final).length > 0 && (
        <div className="analysis-agentic-final">
          FINAL L{final.local ?? '—'} · R{final.regional ?? '—'} · G{final.global ?? '—'}
          {agentic.status ? ` · ${String(agentic.status).toUpperCase()}` : ''}
        </div>
      )}
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
  const [view, setView] = useHudSessionState<ViewId>('view', 'globe', isViewId)
  const [splitView, setSplitView] = useHudSessionState('splitView', false, isBool)
  const [booting, setBooting] = useState(true)
  const [focus, setFocus] = useState<FocusTarget | null>(null)
  const askAIIdRef = useRef(0)
  const [askAI, setAskAI] = useState<{ id: number; question: string; context: string } | null>(null)
  const [analysisOpen, setAnalysisOpen] = useHudSessionState('analysisOpen', false, isBool)
  const [situationOpen, setSituationOpen] = useHudSessionState('situationOpen', false, isBool)
  const [osintPins, setOsintPins] = useState<OsintPin[]>(() => loadOsintPins())
  const [syncCamera, setSyncCamera] = useState<{ lon: number; lat: number; height?: number; zoom?: number; pitch?: number; source: 'globe' | 'map'; ts: number } | null>(null)
  const [mapMode, setMapMode] = useHudSessionState<MapViewMode>('mapMode', DEFAULT_MAP_VIEW, isMapViewMode)
  const [windyMapOpen, setWindyMapOpen] = useState(false)
  const [windyMapCoords, setWindyMapCoords] = useState({ lat: 9.55, lon: 100.05 })
  const [windyMapKey, setWindyMapKey] = useState<string | null>(null)
  useAlertNotifications()
  const agenticBadge = useBriefingAgenticBadge()
  const situationsBadge = useSituationsBadge()

  useEffect(() => {
    fetchApi('/api/windy/config')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (d?.map_key) setWindyMapKey(d.map_key)
        if (d?.default_lat != null && d?.default_lon != null) {
          setWindyMapCoords({ lat: d.default_lat, lon: d.default_lon })
        }
      })
      .catch(() => {})
  }, [])

  const openWindyMap = (lat: number, lon: number) => {
    setWindyMapCoords({ lat, lon })
    setWindyMapOpen(true)
    setView('globe')
    setSplitView(false)
  }

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

  useAgentBus(focusOnMap)

  const lastCamPostRef = useRef(0)
  const handleGlobeMove = useCallback((cam: { lon: number; lat: number; height: number; pitch?: number }) => {
    if (view === 'map' || splitView) {
      setSyncCamera({ ...cam, source: 'globe', ts: Date.now() })
    }
    if (agentBusEnabled() && Date.now() - lastCamPostRef.current > 3000) {
      lastCamPostRef.current = Date.now()
      fetchApi('/api/agent/camera', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(cam),
      }).catch(() => {})
    }
  }, [view, splitView])

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
    onOpenWindy: openWindyMap,
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
                if (n.id === 'data' || n.id === 'news' || n.id === 'osint' || n.id === 'chat') {
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
          <button
            className="mega-analysis-btn"
            onClick={() => setSituationOpen(true)}
            title={situationsBadge?.tip || 'Open unified situation board'}
          >
            SITUATIONS
            {situationsBadge && (
              <span className={`mega-analysis-badge mega-analysis-badge--${situationsBadge.tone}`}>
                {situationsBadge.label}
              </span>
            )}
          </button>
          <button
            className="mega-analysis-btn secondary"
            onClick={() => setAnalysisOpen(true)}
            title={agenticBadge?.tip || 'Open full situational overlay'}
          >
            FULL SITUATION
            {agenticBadge && (
              <span className={`mega-analysis-badge mega-analysis-badge--${agenticBadge.tone}`}>
                {agenticBadge.label}
              </span>
            )}
          </button>
          <SystemStatus />
          <HudClock />
        </div>
      </header>

      <NodeHealthBanner />

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
          {windyMapOpen && windyMapKey && (
            <WindyMapOverlay
              open={windyMapOpen}
              onClose={() => setWindyMapOpen(false)}
              lat={windyMapCoords.lat}
              lon={windyMapCoords.lon}
              mapKey={windyMapKey}
            />
          )}
        </div>

        {splitView ? null : view !== 'globe' && view !== 'map' ? (
          <div key={view} className="view-fade">
            {view === 'data' && <DataPanel onFocus={focusOnMap} onOpenWindyMap={openWindyMap} />}
            {view === 'chat' && (
              <ChatPanel
                askAI={askAI}
                onClearAsk={() => setAskAI(null)}
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
            {view === 'news' && <NewsPanel />}
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

type BriefLang = 'en' | 'de'
type AnalysisTab = 'operator' | 'alerts' | 'feeds'

const ANALYSIS_TABS: AnalysisTab[] = ['operator', 'alerts', 'feeds']

function isAnalysisTab(v: unknown): v is AnalysisTab {
  return typeof v === 'string' && (ANALYSIS_TABS as readonly string[]).includes(v as AnalysisTab)
}

function AnalysisCollapsible({
  title,
  count,
  defaultOpen = true,
  children,
}: {
  title: string
  count?: number
  defaultOpen?: boolean
  children: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className={`analysis-section analysis-collapsible${open ? '' : ' is-closed'}`}>
      <button type="button" className="analysis-section-toggle" onClick={() => setOpen((v) => !v)}>
        <span>{title}{count != null ? ` (${count})` : ''}</span>
        <span className="analysis-section-chevron" aria-hidden>{open ? '▾' : '▸'}</span>
      </button>
      {open ? <div className="analysis-collapsible-body">{children}</div> : null}
    </div>
  )
}

const FULL_SITUATION_FETCH_MS = 15_000

function FullAnalysisOverlay({ onClose, onFocus }: { onClose: () => void; onFocus: (f: Omit<FocusTarget, 'ts'>) => void }) {
  const [loading, setLoading] = useState(true)
  const [results, setResults] = useState<any>({})
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [analysisTab, setAnalysisTab] = useHudSessionState<AnalysisTab>('analysisTab', 'operator', isAnalysisTab)
  const [trustExpanded, setTrustExpanded] = useHudSessionState('analysisTrustExpanded', false, isBool)
  const [briefLang, setBriefLang] = useState<BriefLang>(() => {
    const saved = (typeof window !== 'undefined' && window.localStorage?.getItem('worldbase_briefing_lang')) as BriefLang | null
    return saved === 'de' || saved === 'en' ? saved : 'en'
  })
  const [briefBusy, setBriefBusy] = useState(false)
  const [briefError, setBriefError] = useState<string | null>(null)
  const reloadCounterRef = useRef(0)
  const [reloadTick, setReloadTick] = useState(0)

  const generateBriefing = async () => {
    setBriefBusy(true)
    setBriefError(null)
    try {
      const r = await fetchApi(`/api/briefing/generate?lang=${briefLang}`, { method: 'POST' })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      await r.json().catch(() => null)
      reloadCounterRef.current += 1
      setReloadTick(reloadCounterRef.current)
    } catch (e: any) {
      setBriefError(e?.message || 'briefing failed')
    } finally {
      setBriefBusy(false)
    }
  }


  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage?.setItem('worldbase_briefing_lang', briefLang)
  }, [briefLang])

  useEffect(() => {
    let cancelled = false
    let interval: ReturnType<typeof setInterval> | undefined
    let partialTimer: ReturnType<typeof setTimeout> | undefined

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
        { key: 'predictions', url: '/api/predictions' },
        { key: 'trust', url: '/api/trust' },
        { key: 'cve', url: '/api/cve?limit=15' },
        { key: 'pegel', url: '/api/pegel' },
      ]

      partialTimer = setTimeout(() => {
        if (!cancelled) setLoading(false)
      }, FULL_SITUATION_FETCH_MS)

      await Promise.all(endpoints.map(async (ep) => {
        try {
          const r = await fetchApiWithTimeout(ep.url, undefined, FULL_SITUATION_FETCH_MS)
          const data = r.ok ? await r.json() : { error: 'unavailable' }
          if (!cancelled) {
            setResults((prev: Record<string, unknown>) => ({ ...prev, [ep.key]: data }))
          }
        } catch {
          if (!cancelled) {
            setResults((prev: Record<string, unknown>) => ({ ...prev, [ep.key]: { error: 'unavailable' } }))
          }
        }
      }))

      if (partialTimer) clearTimeout(partialTimer)
      if (!cancelled) setLoading(false)
    }

    fetchAll()
    if (autoRefresh) interval = setInterval(fetchAll, 30000)
    return () => {
      cancelled = true
      if (interval) clearInterval(interval)
      if (partialTimer) clearTimeout(partialTimer)
    }
  }, [autoRefresh, reloadTick])

  const health = results.health
  const correlations = results.correlations
  const briefing = results.briefing
  const digest = briefing?.digest
  const briefingQuality = briefing?.quality
  const trust = results.trust
  const predictions = results.predictions
  const fusionHotspots = briefing?.fusion_hotspots || []
  const agenticTrace = briefing?.agentic as AgenticTrace | undefined
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
  const formatPredDue = (iso: string | null | undefined, overdue?: boolean) => {
    if (!iso) return '—'
    if (overdue) return 'OVERDUE'
    try {
      const ms = new Date(iso).getTime() - Date.now()
      const h = Math.round(ms / 3600000)
      if (h <= 0) return 'due now'
      return `${h}h left`
    } catch {
      return '—'
    }
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

  const alertCount =
    (correlations?.situations?.length || 0)
    + (briefing?.watch_items?.length || 0)
    + gdacs.length
    + ((anomalies?.count || 0) > 0 ? 1 : 0)
  const feedCount =
    (military?.count || 0)
    + quakes.length
    + allEvents.length
    + wildfires.length
    + (cveFeed?.vulnerabilities?.length ?? 0)
    + (air?.cities?.length ?? 0)

  const digestMeta = briefing?.digest_line_meta || []
  const weakDigestCount = digestMeta.filter(
    (row: any) =>
      row.label === 'single-source'
      || row.label === 'contradictory'
      || Number(row.corroboration ?? 1) < 0.5,
  ).length
  const feedDegrade = trust?.feed_drift?.degradation
  const showDegradeBanner =
    analysisTab === 'operator'
    && (trust?.degraded || trust?.field_warn || trust?.feed_warn)
  const degradeCritical = (trust?.score ?? 4) < 2
  const unavailableFeeds = Object.entries(results)
    .filter(([, v]) => (v as { error?: string })?.error === 'unavailable')
    .map(([k]) => k)

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
          <>
            <div className="analysis-tabs" role="tablist" aria-label="Full situation views">
              <button
                type="button"
                role="tab"
                aria-selected={analysisTab === 'operator'}
                className={analysisTab === 'operator' ? 'on' : ''}
                onClick={() => setAnalysisTab('operator')}
              >
                OPERATOR
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={analysisTab === 'alerts'}
                className={analysisTab === 'alerts' ? 'on' : ''}
                onClick={() => setAnalysisTab('alerts')}
              >
                ALERTS{alertCount > 0 ? ` · ${alertCount}` : ''}
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={analysisTab === 'feeds'}
                className={analysisTab === 'feeds' ? 'on' : ''}
                onClick={() => setAnalysisTab('feeds')}
              >
                FEEDS{feedCount > 0 ? ` · ${feedCount}` : ''}
              </button>
            </div>
            {unavailableFeeds.length > 0 && (
              <div className="analysis-degrade-banner" role="status">
                <strong>PARTIAL LOAD</strong>
                {' — '}
                {unavailableFeeds.length} feed(s) timed out ({unavailableFeeds.join(', ')}).
                Data shown from available endpoints; enable AUTO-REFRESH to retry.
              </div>
            )}
            {analysisTab === 'operator' && (trust || briefingQuality) && (
              <div className="analysis-summary-strip">
                <span>FIELD {trust?.score ?? '—'}/{trust?.max_score ?? 4}</span>
                <span>QUALITY {briefingQuality?.score != null ? `${Math.round(briefingQuality.score * 100)}%` : '—'}</span>
                <span>LOCAL {digest?.local_count ?? '—'}</span>
                <span>AGENTIC {agenticTrace?.rounds ?? '—'}/{agenticTrace?.max_rounds ?? 3}</span>
                <span>FUSION {fusionHotspots.length}</span>
                {weakDigestCount > 0 && (
                  <span style={{ color: '#ffd23f' }} title="Digest lines with weak or single-source corroboration">
                    VERIFY −{weakDigestCount}
                  </span>
                )}
                {feedDegrade?.offline_pct != null && feedDegrade.offline_pct > 0 && (
                  <span
                    style={{ color: feedDegrade.warn ? '#ff6b35' : '#8fb7a9' }}
                    title={(feedDegrade.offline_keys || []).join(', ')}
                  >
                    FEEDS OFFLINE {feedDegrade.offline_pct}%
                  </span>
                )}
              </div>
            )}
            {showDegradeBanner && (
              <div
                className={`analysis-degrade-banner${degradeCritical ? ' analysis-degrade-banner--critical' : ''}`}
                role="status"
              >
                <strong>{degradeCritical ? 'FIELD TRUST LOW' : 'DEGRADED MODE'}</strong>
                {' — '}
                {(trust?.failed_probes || []).length > 0 && (
                  <span>probes down: {(trust.failed_probes as string[]).join(', ')}. </span>
                )}
                {feedDegrade?.warn && (
                  <span>
                    {feedDegrade.offline_pct}% watch feeds offline/stale
                    {(feedDegrade.offline_keys?.length ?? 0) > 0
                      ? ` (${(feedDegrade.offline_keys as string[]).slice(0, 4).join(', ')})`
                      : ''}
                    .{' '}
                  </span>
                )}
                Briefing may be incomplete — expand TRUST DETAIL for provenance.
              </div>
            )}
            {analysisTab === 'feeds' && (
              <div className="analysis-summary-strip analysis-summary-strip--feeds">
                <span>MILITARY {military?.count ?? 0}</span>
                <span>SEISMIC {quakes.length}</span>
                <span>EVENTS {allEvents.length + wildfires.length}</span>
                <span>CVE {cveFeed?.vulnerabilities?.length ?? 0}</span>
                <span style={{ color: '#6f8c84' }}>Expand sections below — all collapsed by default</span>
              </div>
            )}
          <div className="analysis-body analysis-body--tabbed">
            {analysisTab === 'operator' && (trust || briefingQuality) && (
              <div
                className="analysis-section"
                style={{
                  marginBottom: 12,
                  borderLeft: `4px solid ${(trust?.score ?? 0) >= 3 ? '#00e5a0' : (trust?.score ?? 0) >= 2 ? '#ffd23f' : '#ff6b35'}`,
                }}
              >
                <h3>TRUST</h3>
                <div className="analysis-row">
                  <span style={{ fontWeight: 'bold' }}>
                    FIELD {trust?.score ?? '—'}/{trust?.max_score ?? 4}
                  </span>
                  <span style={{ color: '#8fb7a9' }}>
                    BRIEFING QUALITY {briefingQuality?.score != null ? Math.round(briefingQuality.score * 100) : '—'}%
                  </span>
                  <button
                    type="button"
                    className="analysis-trust-toggle"
                    onClick={() => setTrustExpanded((v) => !v)}
                  >
                    {trustExpanded ? 'LESS' : 'DETAIL'}
                  </button>
                </div>
                {trustExpanded && trust?.probes?.map((p: any) => (
                  <div key={p.name} className="analysis-row" style={{ fontSize: 11 }}>
                    <span style={{ color: p.ok ? '#00e5a0' : '#ff6b35', fontWeight: 'bold' }}>
                      {p.ok ? 'OK' : 'FAIL'}
                    </span>
                    <span>{p.name}: {p.detail}</span>
                  </div>
                ))}
                {trustExpanded && trust?.feed_drift && (
                  <div className="analysis-row" style={{ fontSize: 11, marginTop: 6 }}>
                    <span
                      style={{
                        color: trust.feed_drift.ok ? '#00e5a0' : '#ffd23f',
                        fontWeight: 'bold',
                      }}
                    >
                      {trust.feed_drift.ok ? 'OK' : 'DRIFT'}
                    </span>
                    <span>feeds: {trust.feed_drift.detail}</span>
                  </div>
                )}
                {trustExpanded && trust?.feed_drift?.drifting?.length > 0 && trust.feed_drift.drifting.map((d: any) => (
                  <div key={d.cache_key} className="analysis-row" style={{ fontSize: 10, color: '#ffd23f' }}>
                    <span style={{ fontWeight: 'bold' }}>{d.cache_key}</span>
                    <span>
                      {d.previous_count} → {d.current_count} (−{d.drop_pct}%)
                    </span>
                  </div>
                ))}
                {trustExpanded && trust?.feed_drift?.freshness?.length > 0 && (
                  <div style={{ marginTop: 8, fontSize: 10, color: '#8fb7a9' }}>
                    {trust.feed_drift.freshness.map((f: any) => {
                      const label = f.connector_name || f.connector_id || f.cache_key
                      const src = Array.isArray(f.source) ? f.source.join(', ') : f.source
                      const tip = [
                        f.connector_id && `id=${f.connector_id}`,
                        f.license && `license=${f.license}`,
                        f.bridge && `bridge=${f.bridge}`,
                        f.endpoint && `api=${f.endpoint}`,
                        src && `source=${src}`,
                        `status=${f.status}`,
                        f.count != null && `count=${f.count}`,
                        f.age_sec != null && `age=${f.age_sec}s`,
                        f.error && `error=${f.error}`,
                      ].filter(Boolean).join(' · ')
                      return (
                      <span
                        key={f.cache_key}
                        style={{
                          display: 'inline-block',
                          marginRight: 8,
                          marginBottom: 4,
                          color:
                            f.status === 'fresh'
                              ? '#00e5a0'
                              : f.status === 'error' || f.status === 'missing'
                                ? '#ff6b35'
                                : '#ffd23f',
                        }}
                        title={tip}
                      >
                        {label}:{f.count ?? '—'}
                      </span>
                      )
                    })}
                  </div>
                )}
                {(trust?.briefing_pipeline || briefingQuality?.meta) && (() => {
                  const pipe = trust?.briefing_pipeline || {}
                  const meta = briefingQuality?.meta || {}
                  const collected = pipe.gdelt_collected ?? meta.gdelt_collected
                  const placed = pipe.gdelt_digest_lines ?? meta.gdelt_digest_lines
                  const blocker = pipe.pipeline_blocker ?? meta.gdelt_pipeline_blocker
                  const placedOk = pipe.pipeline_placed_ok ?? meta.gdelt_pipeline_placed_ok
                  const watchCount = pipe.watch_count ?? meta.watch_count ?? briefing?.watch_items?.length
                  const corroAvg = pipe.corroboration_avg_local ?? meta.corroboration_avg_local
                  const corroBlocker = pipe.corroboration_blocker ?? meta.corroboration_blocker
                  const predAcc = pipe.prediction_accuracy_30d ?? meta.prediction_accuracy_30d
                  const predPending = pipe.prediction_pending ?? meta.prediction_pending
                  const predSample = pipe.prediction_sample_30d ?? meta.prediction_sample_30d
                  const blockerHint =
                    blocker === 'empty_feed_body'
                      ? 'GDELT rate limit or empty body — wait for disk cache'
                      : blocker === 'bucket_cap'
                        ? 'LOCAL bucket full — GDELT slots env may help'
                        : blocker === 'single_source_local'
                          ? 'LOCAL digest lines share one feed family only'
                          : blocker || ''
                  if (collected == null && placed == null && !blocker && watchCount == null && corroAvg == null && predPending == null) return null
                  return (
                    <div className="analysis-row" style={{ fontSize: 11, marginTop: 8 }}>
                      <span
                        style={{
                          color: placedOk === false ? '#ffd23f' : '#00e5a0',
                          fontWeight: 'bold',
                        }}
                      >
                        GDELT {collected ?? '—'}→{placed ?? '—'}
                      </span>
                      {watchCount != null && (
                        <span style={{ color: '#7ec8ff' }} title="Anticipatory watch items (24–72h)">
                          WATCH {watchCount}
                        </span>
                      )}
                      {corroAvg != null && (
                        <span
                          style={{ color: corroAvg >= 0.75 ? '#00e5a0' : corroAvg >= 0.5 ? '#ffd23f' : '#ff6b35' }}
                          title="LOCAL digest corroboration (multi-source verification)"
                        >
                          VERIFY {Math.round(corroAvg * 100)}%
                        </span>
                      )}
                      {predPending != null && (
                        <span
                          style={{ color: predAcc != null && predAcc >= 0.6 ? '#00e5a0' : '#7ec8ff' }}
                          title="Watch-item outcomes after 24–72h horizon (Track 4 ledger)"
                        >
                          PRED {predAcc != null ? `${Math.round(predAcc * 100)}%` : '—'}
                          {predSample != null ? ` n=${predSample}` : ''} · {predPending} pending
                        </span>
                      )}
                      {(blocker || corroBlocker) ? (
                        <span style={{ color: '#ffd23f' }} title={blockerHint}>
                          BLOCKER: {blocker || corroBlocker}
                        </span>
                      ) : (
                        <span style={{ color: '#8fb7a9' }}>pipeline OK</span>
                      )}
                    </div>
                  )
                })()}
              </div>
            )}
            <div className="analysis-col analysis-col--single">

              {analysisTab === 'alerts' && nodes?.nodes?.some((n: any) => (n.health?.disk_pct ?? 0) >= 85) && (
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

              {analysisTab === 'alerts' && (correlations?.situations?.length > 0 || anomalies?.count > 0) && (
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

              {analysisTab === 'alerts' && briefing?.watch_items?.length > 0 && (
                <div className="analysis-section">
                  <h3>👁 WATCH ITEMS ({briefing.watch_items.length})</h3>
                  {briefing.watch_items.map((w: any, i: number) => (
                    <div key={w.id || i} className="analysis-row" style={{ borderLeft: '3px solid #7ec8ff' }}>
                      <span style={{ color: '#7ec8ff', fontWeight: 'bold', minWidth: 52 }}>{w.horizon_h}h</span>
                      <span>{w.title}</span>
                      <span style={{ color: '#8fb7a9', fontSize: 10 }}>
                        {Math.round((w.confidence ?? 0) * 100)}% · {(w.sources || []).join(', ')}
                        {w.delta_score != null ? ` · Δ${Number(w.delta_score).toFixed(2)}` : ''}
                      </span>
                      {w.lat != null && w.lon != null && (
                        <button
                          className="locate-mini"
                          title="Fly to watch cell on globe"
                          onClick={() => {
                            onClose()
                            onFocus({
                              kind: 'watch',
                              lon: w.lon,
                              lat: w.lat,
                              height: 800000,
                              title: w.title,
                              lines: [
                                `HORIZON: ${w.horizon_h}h`,
                                `CONFIDENCE: ${Math.round((w.confidence ?? 0) * 100)}%`,
                                `BUCKET: ${w.bucket || '—'}`,
                                `SOURCES: ${(w.sources || []).join(', ') || '—'}`,
                              ],
                            })
                          }}
                        >
                          ◎
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {analysisTab === 'alerts' && predictions?.enabled && (
                predictions.pending?.length > 0 || predictions.resolved_recent?.length > 0
              ) && (
                <div className="analysis-section">
                  <h3>
                    📊 PREDICTION LEDGER ({predictions.stats?.pending ?? 0} pending
                    {predictions.overdue_count > 0 ? ` · ${predictions.overdue_count} overdue` : ''}
                    {predictions.due_next ? ` · next ${formatPredDue(predictions.due_next)}` : ''})
                  </h3>
                  {predictions.stats?.sample_size > 0 && (
                    <div className="analysis-row" style={{ fontSize: 10, color: '#8fb7a9' }}>
                      30d hit rate {Math.round((predictions.stats.accuracy ?? 0) * 100)}% · n={predictions.stats.sample_size}
                    </div>
                  )}
                  {predictions.pending?.slice(0, 6).map((p: any) => (
                    <div
                      key={p.id ?? p.watch_id}
                      className="analysis-row"
                      style={{ borderLeft: `3px solid ${p.overdue ? '#ffd23f' : '#7ec8ff'}` }}
                    >
                      <span style={{ color: p.overdue ? '#ffd23f' : '#7ec8ff', fontWeight: 'bold', minWidth: 72 }}>
                        {formatPredDue(p.due_at, p.overdue)}
                      </span>
                      <span style={{ flex: 1 }}>{p.claim}</span>
                      <span style={{ color: '#8fb7a9', fontSize: 10 }}>
                        {(p.prefix || '—').toUpperCase()} · {p.horizon_h}h
                      </span>
                    </div>
                  ))}
                  {predictions.resolved_recent?.slice(0, 4).map((p: any) => (
                    <div
                      key={`r-${p.id}`}
                      className="analysis-row"
                      style={{ borderLeft: `3px solid ${p.hit ? '#00e5a0' : '#ff6b35'}` }}
                    >
                      <span style={{ color: p.hit ? '#00e5a0' : '#ff6b35', fontWeight: 'bold', minWidth: 72 }}>
                        {p.hit ? 'HIT' : 'MISS'}
                      </span>
                      <span style={{ flex: 1 }} title={p.outcome || ''}>{p.claim}</span>
                      <span style={{ color: '#8fb7a9', fontSize: 10 }}>{(p.prefix || '—').toUpperCase()}</span>
                    </div>
                  ))}
                </div>
              )}

              {analysisTab === 'alerts' && briefing?.intel?.entities?.length > 0 && (
                <div className="analysis-section">
                  <h3>🕸 INTEL ENTITIES ({briefing.intel.count ?? briefing.intel.entities.length})</h3>
                  {(briefing.intel.by_bucket) && (
                    <div className="analysis-row" style={{ fontSize: 10, color: '#8fb7a9' }}>
                      LOCAL {briefing.intel.by_bucket.local ?? 0} · REGION {briefing.intel.by_bucket.regional ?? 0} · GLOBAL {briefing.intel.by_bucket.global ?? 0}
                    </div>
                  )}
                  {briefing.intel.entities.slice(0, 6).map((e: any, i: number) => (
                    <div key={e.id || i} className="analysis-row" style={{ borderLeft: '3px solid #c084fc' }}>
                      <span style={{ color: '#c084fc', fontWeight: 'bold', minWidth: 52, textTransform: 'uppercase', fontSize: 10 }}>
                        {(e.bucket || '—').slice(0, 6)}
                      </span>
                      <span style={{ flex: 1 }}>{e.caption || e.id}</span>
                      <span style={{ color: '#8fb7a9', fontSize: 10 }}>{e.schema || 'Entity'}</span>
                      {e.lat != null && e.lon != null && (
                        <button
                          className="locate-mini"
                          title="Fly to entity on globe"
                          onClick={() => {
                            onClose()
                            onFocus({
                              kind: 'intel',
                              lon: e.lon,
                              lat: e.lat,
                              height: 600000,
                              title: e.caption || e.id,
                              lines: [
                                `SCHEMA: ${e.schema || '—'}`,
                                `BUCKET: ${e.bucket || '—'}`,
                                `DATASETS: ${(e.datasets || []).join(', ') || '—'}`,
                              ],
                            })
                          }}
                        >
                          ◎
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {analysisTab === 'alerts' && gdacs.length > 0 && (
                <div className="analysis-section">
                  <h3>🌊 HUMANITARIAN ALERTS ({gdacs.length})</h3>
                  {gdacs.slice(0, 8).map((a: any, i: number) => {
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

              {analysisTab === 'operator' && agenticTrace && <AgenticLoopPanel agentic={agenticTrace} />}

              {analysisTab === 'operator' && briefing?.digest_line_meta?.length > 0 && (
                <AnalysisCollapsible
                  title="✓ DIGEST VERIFICATION"
                  count={briefing.digest_line_meta.length}
                  defaultOpen={weakDigestCount > 0}
                >
                  {briefing.digest_line_meta.slice(0, 8).map((row: any, i: number) => (
                    <div
                      key={i}
                      className="analysis-row"
                      style={{
                        borderLeft: `3px solid ${
                          row.label === 'corroborated'
                            ? '#00e5a0'
                            : row.label === 'contradictory'
                              ? '#ff2d00'
                              : '#ffd23f'
                        }`,
                      }}
                    >
                      <span style={{ fontWeight: 'bold', minWidth: 88, textTransform: 'uppercase', fontSize: 10 }}>
                        {row.label || 'single-source'}
                      </span>
                      <span style={{ flex: 1 }}>{String(row.text || '').replace(/^-\s*/, '').slice(0, 120)}</span>
                      {row.observed_at && (
                        <span style={{ color: '#6a9a8c', fontSize: 10, minWidth: 72, textAlign: 'right' }}>
                          {new Date(row.observed_at).toLocaleString(undefined, {
                            month: 'short',
                            day: 'numeric',
                            hour: '2-digit',
                            minute: '2-digit',
                          })}
                        </span>
                      )}
                      <span style={{ color: '#8fb7a9', fontSize: 10 }}>
                        {Math.round((row.corroboration ?? 0) * 100)}% · {(row.sources || []).slice(0, 3).join(', ')}
                      </span>
                    </div>
                  ))}
                </AnalysisCollapsible>
              )}

              {analysisTab === 'operator' && briefing?.text && (
                <div className="analysis-section">
                  <div className="analysis-section-head">
                    <h3>📋 24H SECURITY DIGEST</h3>
                    <div className="brief-controls">
                      <div className="brief-lang" role="group" aria-label="Briefing language">
                        <button
                          type="button"
                          className={briefLang === 'en' ? 'on' : ''}
                          onClick={() => setBriefLang('en')}
                          disabled={briefBusy}
                        >
                          EN
                        </button>
                        <button
                          type="button"
                          className={briefLang === 'de' ? 'on' : ''}
                          onClick={() => setBriefLang('de')}
                          disabled={briefBusy}
                        >
                          DE
                        </button>
                      </div>
                      <button
                        type="button"
                        className="brief-generate"
                        onClick={generateBriefing}
                        disabled={briefBusy}
                        title="Re-run briefing pipeline now"
                      >
                        {briefBusy ? 'GENERATING…' : 'GENERATE'}
                      </button>
                    </div>
                  </div>
                  {briefError && <div className="brief-error">{briefError}</div>}
                  {(digest || fusionHotspots.length > 0) && (
                    <>
                      {digest && (
                        <div className="analysis-digest-meta">
                          {digest.region_label && (
                            <span className="analysis-digest-chip">
                              REGION <strong>{digest.region_label}</strong>
                            </span>
                          )}
                          {digest.window && (
                            <span className="analysis-digest-chip">
                              WINDOW <strong>{digest.window}</strong>
                            </span>
                          )}
                          <span className="analysis-digest-chip local">
                            LOCAL <strong>{digest.local_count ?? 0}</strong>
                          </span>
                          <span className="analysis-digest-chip regional">
                            REGIONAL <strong>{digest.regional_count ?? 0}</strong>
                          </span>
                          <span className="analysis-digest-chip global">
                            GLOBAL <strong>{digest.global_count ?? 0}</strong>
                          </span>
                          {briefing.created_at && (
                            <span className="analysis-digest-chip">
                              UPDATED <strong>{new Date(briefing.created_at).toLocaleString()}</strong>
                            </span>
                          )}
                        </div>
                      )}
                      {fusionHotspots.slice(0, 3).map((h: any, i: number) => (
                        <div key={i} className="analysis-fusion-row">
                          <span style={{ color: '#ff6b35', fontWeight: 'bold' }}>FUSION #{i + 1}</span>
                          <span>{h.label || h.summary || `${h.lat?.toFixed(1)}, ${h.lon?.toFixed(1)}`}</span>
                          {h.score != null && <span>score {Number(h.score).toFixed(1)}</span>}
                          {h.lat != null && h.lon != null && (
                            <button
                              className="locate-mini"
                              onClick={() => {
                                onClose()
                                onFocus({
                                  kind: 'fusion',
                                  lon: h.lon,
                                  lat: h.lat,
                                  height: 800000,
                                  title: h.label || `Fusion hotspot ${i + 1}`,
                                  lines: [`Score: ${h.score ?? '—'}`, h.summary].filter(Boolean) as string[],
                                })
                              }}
                            >
                              ◎
                            </button>
                          )}
                        </div>
                      ))}
                    </>
                  )}
                  <div className="analysis-briefing">{briefing.text}</div>
                </div>
              )}

              {analysisTab === 'feeds' && (cveFeed?.vulnerabilities?.length ?? 0) > 0 && (
                <AnalysisCollapsible title="🔐 CISA KEV" count={cveFeed.vulnerabilities.length} defaultOpen={false}>
                  {cveFeed.vulnerabilities.slice(0, 8).map((v: any, i: number) => (
                    <div key={i} className="analysis-row" style={{ borderLeft: `3px solid ${v.ransomware === 'Known' ? '#ff2d00' : '#ff6b35'}` }}>
                      <span style={{ fontWeight: 'bold', minWidth: 120 }}>{v.cve_id}</span>
                      <span style={{ flex: 1 }}>{v.vendor} — {v.product}</span>
                      <span style={{ color: '#6f8c84', fontSize: 10 }}>due {v.due_date || '—'}</span>
                    </div>
                  ))}
                </AnalysisCollapsible>
              )}

              {analysisTab === 'feeds' && quakes.length > 0 && (
                <AnalysisCollapsible title="🌋 SEISMIC" count={quakes.length} defaultOpen={false}>
                  {quakes.slice(0, 6).map((q: any, i: number) => (
                    <div key={i} className="analysis-row" style={{ borderLeft: `3px solid ${q.mag >= 5 ? '#ff2d00' : q.mag >= 3.5 ? '#ff6b35' : '#00e5a0'}` }}>
                      <span style={{ fontWeight: 'bold', minWidth: 50 }}>M{q.mag?.toFixed(1) ?? '—'}</span>
                      <span style={{ flex: 1 }}>{q.place || '—'}</span>
                      <span style={{ color: '#6f8c84', minWidth: 70 }}>{q.depth != null ? q.depth.toFixed(1) + ' km' : '—'}</span>
                      <span style={{ color: '#6f8c84', minWidth: 50 }}>{q.tsunami ? 'TSU' : ''}</span>
                      <button className="locate-mini" onClick={() => { onClose(); onFocus({ kind: 'quake', lon: q.lon, lat: q.lat, height: 400000, title: `M${q.mag} ${q.place}`, lines: [`Depth: ${q.depth} km`, `Time: ${new Date(q.time).toLocaleString()}`, `Tsunami: ${q.tsunami ? 'YES' : 'no'}`] }) }}>◎</button>
                    </div>
                  ))}
                </AnalysisCollapsible>
              )}

              {analysisTab === 'feeds' && results.spaceweather && (
                <AnalysisCollapsible title="☀️ SPACE WEATHER" defaultOpen={false}>
                  <div className="analysis-row">
                    <span>Kp: <strong>{results.spaceweather.kp_index ?? '—'}</strong></span>
                    <span>Scale: {results.spaceweather.scale ?? '—'}</span>
                    <span style={{ color: results.spaceweather.aurora_visible_midlat ? '#ff6b35' : '#6f8c84' }}>Aurora: {results.spaceweather.aurora_visible_midlat ? 'VISIBLE' : 'none'}</span>
                    <span style={{ color: results.spaceweather.hf_radio_impact ? '#ff6b35' : '#6f8c84' }}>HF: {results.spaceweather.hf_radio_impact ? 'IMPACTED' : 'OK'}</span>
                    <span style={{ color: '#6f8c84' }}>History: {results.spaceweather.history?.length ?? 0} pts</span>
                  </div>
                </AnalysisCollapsible>
              )}

              {analysisTab === 'feeds' && allEvents.length > 0 && (
                <AnalysisCollapsible title="🔔 EVENTS" count={allEvents.length} defaultOpen={false}>
                  {allEvents.slice(0, 5).map((e: any, i: number) => (
                    <div key={i} className="analysis-row" style={{ borderLeft: `3px solid ${(e.magnitude || 0) > 6 ? '#ff2d00' : '#ff6b35'}` }}>
                      <span style={{ minWidth: 90, fontWeight: 'bold' }}>{e.category || 'EVENT'}</span>
                      <span style={{ flex: 1 }}>{e.title || '—'}</span>
                      <span style={{ color: '#6f8c84' }}>{e.date ? new Date(e.date).toLocaleDateString() : '—'}</span>
                      {e.lon != null && (
                        <button className="locate-mini" onClick={() => { onClose(); onFocus({ kind: 'event', lon: e.lon, lat: e.lat, height: 400000, title: e.title, lines: [`Category: ${e.category}`, `Date: ${e.date}`] }) }}>◎</button>
                      )}
                    </div>
                  ))}
                </AnalysisCollapsible>
              )}

              {analysisTab === 'feeds' && wildfires.length > 0 && (
                <AnalysisCollapsible title="🔥 WILDFIRES" count={wildfires.length} defaultOpen={false}>
                  {wildfires.slice(0, 5).map((e: any, i: number) => (
                    <div key={i} className="analysis-row" style={{ borderLeft: '3px solid #ff2d00' }}>
                      <span style={{ flex: 1 }}>{e.title || '—'}</span>
                      <span style={{ color: '#6f8c84' }}>{e.date ? new Date(e.date).toLocaleDateString() : '—'}</span>
                      {e.lon != null && (
                        <button className="locate-mini" onClick={() => { onClose(); onFocus({ kind: 'wildfire', lon: e.lon, lat: e.lat, height: 400000, title: e.title, lines: [`Category: ${e.category}`, `Date: ${e.date}`] }) }}>◎</button>
                      )}
                    </div>
                  ))}
                </AnalysisCollapsible>
              )}

              {analysisTab === 'feeds' && military?.count > 0 && (
                <AnalysisCollapsible title="✈️ MILITARY AIRCRAFT" count={military.count} defaultOpen={false}>
                  {military.aircraft?.slice(0, 8).map((a: any, i: number) => (
                    <div key={i} className="analysis-row" style={{ borderLeft: ['7500', '7600', '7700'].includes(a.squawk) ? '3px solid #ff2d00' : '3px solid #ff6b35' }}>
                      <span style={{ fontWeight: 'bold', minWidth: 80 }}>{a.flight || a.hex}</span>
                      <span style={{ minWidth: 50 }}>{a.type || '—'}</span>
                      <span style={{ color: '#6f8c84', minWidth: 90 }}>Alt: {a.alt != null && !isNaN(Number(a.alt)) ? Number(a.alt).toFixed(0) + ' m' : '—'}</span>
                      <span style={{ color: '#6f8c84', minWidth: 90 }}>Spd: {a.speed != null && !isNaN(Number(a.speed)) ? Number(a.speed).toFixed(0) + ' m/s' : '—'}</span>
                      {a.squawk && <span style={{ color: '#ff2d00', fontWeight: 'bold', minWidth: 80 }}>SQ {a.squawk}</span>}
                      <button className="locate-mini" onClick={() => { onClose(); onFocus({ kind: 'military', lon: a.lon, lat: a.lat, height: 400000, title: a.flight || a.hex, lines: [`Type: ${a.type || '—'}`, `Alt: ${a.alt} m`, `Speed: ${a.speed} m/s`, `Squawk: ${a.squawk || '—'}`] }) }}>◎</button>
                    </div>
                  ))}
                </AnalysisCollapsible>
              )}

              {analysisTab === 'feeds' && air?.cities?.length > 0 && (
                <AnalysisCollapsible title="💨 AIR QUALITY" count={air.cities.length} defaultOpen={false}>
                  <div className="analysis-grid">
                    {air.cities.map((c: any, i: number) => (
                      <div key={i} className="analysis-card" style={{ borderLeft: `3px solid ${aqColor(c.pm25)}` }}>
                        <strong>{c.city}</strong>
                        <span style={{ color: aqColor(c.pm25) }}>PM2.5: {c.pm25 != null ? c.pm25.toFixed(1) : '—'}</span>
                        <span>PM10: {c.pm10 != null ? c.pm10.toFixed(1) : '—'}</span>
                      </div>
                    ))}
                  </div>
                </AnalysisCollapsible>
              )}

              {analysisTab === 'feeds' && (pegel?.gauges?.length ?? 0) > 0 && (
                <AnalysisCollapsible title="🌊 RIVER GAUGES DE" count={pegel.gauges.length} defaultOpen={false}>
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
                </AnalysisCollapsible>
              )}

              {analysisTab === 'feeds' && results.markets?.crypto && (
                <AnalysisCollapsible title="📈 CRYPTO MARKETS" defaultOpen={false}>
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
                </AnalysisCollapsible>
              )}

              {analysisTab === 'feeds' && nodes?.nodes?.length > 0 && (
                <AnalysisCollapsible title="📡 NODES" count={nodes.count} defaultOpen={false}>
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
                </AnalysisCollapsible>
              )}

              {analysisTab === 'feeds' && health?.feeds && (
                <AnalysisCollapsible title="🔌 FEED HEALTH" count={Object.keys(health.feeds).length} defaultOpen={false}>
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
                </AnalysisCollapsible>
              )}

            </div>
          </div>
          </>
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









