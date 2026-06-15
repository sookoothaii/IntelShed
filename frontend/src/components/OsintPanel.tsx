import { useState, useEffect } from 'react';
import { fetchApi } from '../lib/networkFetch';
import type { OsintPin } from '../lib/osintPins';
import type { FocusTarget } from '../lib/focus';

const FLOWSINT_URL = (import.meta.env.VITE_FLOWSINT_URL as string | undefined)?.replace(/\/$/, '') || 'http://localhost:5173'

export default function OsintPanel({
  onFocus,
  onAddPin,
  onImportPins,
  pinCount,
}: {
  onFocus: (f: Omit<FocusTarget, 'ts'>) => void
  onAddPin: (pin: Omit<OsintPin, 'ts'>) => void
  onImportPins: (pins: OsintPin[]) => void
  pinCount: number
}) {
  const [mode, setMode] = useState<'tools' | 'flowsint'>('tools')
  const [flowsintOk, setFlowsintOk] = useState<boolean | null>(null)
  const [tool, setTool] = useState<'ip' | 'domain' | 'username' | 'email' | 'reverse'>('ip')
  const [query, setQuery] = useState('')
  const [latInput, setLatInput] = useState('')
  const [lonInput, setLonInput] = useState('')
  const [result, setResult] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [importJson, setImportJson] = useState('')
  const [importMsg, setImportMsg] = useState('')

  async function importFlowsintPins() {
    setImportMsg('')
    let body: unknown
    try {
      body = JSON.parse(importJson)
    } catch {
      setImportMsg('Invalid JSON')
      return
    }
    setBusy(true)
    try {
      const r = await fetchApi('/api/osint/pins/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || r.statusText)
      const pins = (d.pins || []) as OsintPin[]
      onImportPins(pins)
      setImportMsg(`Imported ${pins.length} pin(s) → globe`)
      setViewGlobeAfterImport(pins)
    } catch (e) {
      setImportMsg(String(e))
    } finally {
      setBusy(false)
    }
  }

  function setViewGlobeAfterImport(pins: OsintPin[]) {
    const first = pins[0]
    if (first) {
      onFocus({
        kind: 'osint',
        lat: first.lat,
        lon: first.lon,
        height: 400000,
        title: first.title,
        lines: first.lines,
      })
    }
  }

  useEffect(() => {
    if (mode !== 'flowsint') return
    let cancelled = false
    const poll = async () => {
      try {
        const r = await fetchApi('/api/flowsint/health')
        const d = await r.json()
        if (!cancelled) setFlowsintOk(!!d.ok)
      } catch {
        if (!cancelled) setFlowsintOk(false)
      }
    }
    poll()
    const t = setInterval(poll, 60000)
    return () => { cancelled = true; clearInterval(t) }
  }, [mode])

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
      const r = await fetchApi(url)
      const d = await r.json()
      setResult(d)
      if (!d.error) {
        if (tool === 'ip' && d.lat != null && d.lon != null) {
          const lines = [
            `Country: ${d.country || '—'}`,
            `Region: ${d.region || '—'}`,
            `City: ${d.city || '—'}`,
            `ISP: ${d.isp || '—'}`,
            `ASN: ${d.asn || '—'}`,
          ]
          onAddPin({
            id: `ip:${d.ip || query}`,
            tool: 'ip',
            query: d.ip || query,
            lat: d.lat,
            lon: d.lon,
            title: `IP ${d.ip || query}`,
            lines,
          })
        } else if (tool === 'reverse' && d.lat != null && d.lon != null) {
          onAddPin({
            id: `geo:${d.lat},${d.lon}`,
            tool: 'reverse',
            query: `${d.lat},${d.lon}`,
            lat: d.lat,
            lon: d.lon,
            title: d.locality || 'Reverse geocode',
            lines: [
              `City: ${d.city || '—'}`,
              `Region: ${d.region || '—'}`,
              `Country: ${d.country || '—'}`,
            ],
          })
        }
      }
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
    <div className="panel osint" style={{ padding: mode === 'flowsint' ? 0 : '0 18px', display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div style={{ padding: '0 18px', flexShrink: 0 }}>
        <h2>OSINT Reconnaissance {pinCount > 0 && <span style={{ fontSize: 11, color: '#00e5a0' }}>({pinCount} on globe)</span>}</h2>
        <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
          <button
            type="button"
            className={mode === 'tools' ? 'active' : ''}
            style={{
              padding: '6px 14px', fontSize: 11, fontFamily: 'monospace', cursor: 'pointer',
              background: mode === 'tools' ? 'rgba(0,229,160,0.2)' : 'rgba(0,229,160,0.05)',
              border: mode === 'tools' ? '1px solid #00e5a0' : '1px solid rgba(0,229,160,0.2)',
              color: mode === 'tools' ? '#00e5a0' : '#6f8c84',
            }}
            onClick={() => setMode('tools')}
          >
            QUICK TOOLS
          </button>
          <button
            type="button"
            className={mode === 'flowsint' ? 'active' : ''}
            style={{
              padding: '6px 14px', fontSize: 11, fontFamily: 'monospace', cursor: 'pointer',
              background: mode === 'flowsint' ? 'rgba(79,195,247,0.2)' : 'rgba(79,195,247,0.05)',
              border: mode === 'flowsint' ? '1px solid #4fc3f7' : '1px solid rgba(79,195,247,0.2)',
              color: mode === 'flowsint' ? '#4fc3f7' : '#6f8c84',
            }}
            onClick={() => setMode('flowsint')}
          >
            FLOWSINT GRAPH
            {flowsintOk === true && <span style={{ marginLeft: 6, color: '#00e5a0' }}>●</span>}
            {flowsintOk === false && <span style={{ marginLeft: 6, color: '#ff6b35' }}>○</span>}
          </button>
          {mode === 'flowsint' && (
            <a href={FLOWSINT_URL} target="_blank" rel="noreferrer" style={{ fontSize: 11, color: '#6f8c84', alignSelf: 'center' }}>
              Open in tab ↗
            </a>
          )}
        </div>
      </div>

      {mode === 'flowsint' && (
        <div style={{ flex: 1, minHeight: 320, display: 'flex', flexDirection: 'column', padding: '0 12px 12px' }}>
          <div style={{ marginBottom: 8, flexShrink: 0 }}>
            <div style={{ fontSize: 11, color: '#6f8c84', marginBottom: 6 }}>
              Paste Flowsint export JSON → <code>POST /api/osint/pins/import</code> → globe pins
            </div>
            <textarea
              value={importJson}
              onChange={(e) => setImportJson(e.target.value)}
              placeholder='{"pins":[{"lat":52.5,"lon":13.4,"label":"Node A","type":"ip","investigation_id":"inv-1"}]}'
              style={{
                width: '100%',
                minHeight: 56,
                fontSize: 11,
                fontFamily: 'monospace',
                background: 'rgba(0,0,0,0.35)',
                border: '1px solid #1a2e33',
                color: '#b0c4b1',
                borderRadius: 4,
                padding: 8,
              }}
            />
            <div style={{ display: 'flex', gap: 8, marginTop: 6, alignItems: 'center' }}>
              <button type="button" onClick={importFlowsintPins} disabled={busy || !importJson.trim()}>
                {busy ? '…' : 'IMPORT TO GLOBE'}
              </button>
              {importMsg && <span style={{ fontSize: 11, color: importMsg.startsWith('Imported') ? '#00e5a0' : '#ff6b35' }}>{importMsg}</span>}
            </div>
          </div>
          {flowsintOk === false && (
            <div className="data-error" style={{ marginBottom: 8, fontSize: 12 }}>
              Flowsint not reachable. On PC: <code>.\scripts\setup-flowsint.ps1</code> then <code>.\scripts\start-flowsint.ps1 -Build</code>
              (Docker). UI: {FLOWSINT_URL}
            </div>
          )}
          <iframe
            title="Flowsint OSINT"
            src={FLOWSINT_URL}
            style={{
              flex: 1,
              width: '100%',
              minHeight: 480,
              border: '1px solid #1a2e33',
              borderRadius: 6,
              background: '#02060a',
            }}
          />
        </div>
      )}

      {mode === 'tools' && (
      <>
      <div style={{ padding: '0 18px' }}>
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
      </>
      )}
    </div>
  )
}
