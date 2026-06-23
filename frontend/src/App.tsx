import { useState, useEffect, useRef, useCallback } from 'react'
import Globe from './components/Globe'
import MapPanel from './components/MapPanel'
import ChatPanel from './components/ChatPanel'
import OsintPanel from './components/OsintPanel'
import DataPanel from './components/DataPanel'
import NewsPanel from './components/NewsPanel'
import SituationBoard from './components/SituationBoard'
import FullAnalysisOverlay from './components/FullAnalysisOverlay'
import { NodeHealthBanner } from './components/NodeHealthBanner'
import type { FocusTarget } from './lib/focus'
import type { OsintPin } from './lib/osintPins'
import { loadOsintPins, saveOsintPins, mergeImportedPins } from './lib/osintPins'
import WindyMapOverlay from './components/WindyMapOverlay'
import MapModeBar from './components/MapModeBar'
import { DEFAULT_MAP_VIEW, type MapViewMode } from './lib/mapView'
import { fetchApi } from './lib/networkFetch'
import { agentBusEnabled } from './lib/agentBus'
import { useAgentBus } from './hooks/useAgentBus'
import { useHudSessionState } from './lib/hudSessionState'
import { agenticBadgeMeta } from './lib/agentic'
import {
  useSituationsQuery,
  useBriefingQuery,
  useHealthPingQuery,
  useModelsQuery,
} from './hooks/useSharedFeeds'

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

function useSituationsBadge() {
  const { data } = useSituationsQuery()
  if (!data) return null
  const items = data.items || []
  const count = data.count ?? items.length
  if (count <= 0) return null
  const high = items.filter((i: { severity?: string }) =>
    i.severity === 'critical' || i.severity === 'high',
  ).length
  return {
    label: String(count),
    tip: `${count} situation(s)${high > 0 ? ` · ${high} high/critical` : ''}`,
    tone: high > 0 ? 'warn' : 'ok',
  } as { label: string; tip: string; tone: 'ok' | 'warn' }
}

function useBriefingAgenticBadge() {
  const { data } = useBriefingQuery()
  return agenticBadgeMeta(data?.agentic ?? null)
}

function SystemStatus() {
  const ping = useHealthPingQuery()
  const models = useModelsQuery()
  const backend: 'online' | 'offline' | 'check' =
    ping.isLoading ? 'check' : ping.isError ? 'offline' : 'online'
  const ollama: 'online' | 'offline' | 'check' =
    models.isLoading ? 'check' : models.isError || models.data?.error ? 'offline' : 'online'

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
  const [intelEntityId, setIntelEntityId] = useState<string | null>(null)
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

  const openIntel = (entityId: string) => {
    if (!entityId) return
    setSituationOpen(false)
    setSplitView(false)
    setIntelEntityId(entityId)
    setView('data')
  }

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
          onOpenIntel={openIntel}
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
            {view === 'data' && <DataPanel onFocus={focusOnMap} onOpenWindyMap={openWindyMap} intelEntityId={intelEntityId} />}
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









