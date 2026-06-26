import { useEffect, useState, useCallback } from 'react'
import type { FocusTarget } from '../lib/focus'
import { fetchApi } from '../lib/networkFetch';

type Match = {
  entity_id: string
  schema: string
  caption: string
  aliases?: string[]
  countries?: string[]
  topics?: string[]
  datasets?: string[]
  sanctions?: string
  identifiers?: string[]
  first_seen?: string
  last_seen?: string
  url?: string
  score?: number
  reasons?: string[]
}

type ScreenHit = {
  vessel: {
    mmsi?: string
    name?: string
    flag?: string
    type?: string
    lat?: number
    lon?: number
    destination?: string
  }
  matched_term: string
  sanction: Match
}

type Status = {
  backend: string
  yente_url?: string | null
  hosted_api_configured?: boolean
  csv: { exists: boolean; path: string; size_mb: number; age_sec: number | null; fresh: boolean }
  index_rows: number
  source_url: string
  license: string
}

interface Props {
  onFocus: (f: Omit<FocusTarget, 'ts'>) => void
}

export default function SanctionsPanel({ onFocus }: Props) {
  const [status, setStatus] = useState<Status | null>(null)
  const [query, setQuery] = useState('')
  const [schema, setSchema] = useState('')
  const [results, setResults] = useState<Match[]>([])
  const [searching, setSearching] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [screenHits, setScreenHits] = useState<ScreenHit[]>([])
  const [screenLoading, setScreenLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchStatus = useCallback(async () => {
    try {
      const r = await fetchApi('/api/sanctions/status')
      setStatus(await r.json())
    } catch (e: unknown) { setError(`status: ${e instanceof Error ? e.message : String(e)}`) }
  }, [])

  useEffect(() => { fetchStatus() }, [fetchStatus])

  const search = async () => {
    if (!query || query.length < 2) return
    setSearching(true); setError(null)
    try {
      const u = new URLSearchParams({ q: query, limit: '15' })
      if (schema) u.set('schema', schema)
      const r = await fetchApi(`/api/sanctions/search?${u.toString()}`)
      const d = await r.json()
      setResults(d.results || [])
    } catch (e: unknown) { setError(`search: ${e instanceof Error ? e.message : String(e)}`); setResults([]) }
    finally { setSearching(false) }
  }

  const refresh = async () => {
    setRefreshing(true); setError(null)
    try {
      await fetchApi('/api/sanctions/refresh', { method: 'POST' })
      setTimeout(fetchStatus, 1500)
    } catch (e: unknown) { setError(`refresh: ${e instanceof Error ? e.message : String(e)}`) }
    finally { setTimeout(() => setRefreshing(false), 1500) }
  }

  const screen = useCallback(async () => {
    setScreenLoading(true); setError(null)
    try {
      const r = await fetchApi('/api/sanctions/screen/vessels?min_score=0.80&limit=300')
      const d = await r.json()
      setScreenHits(d.matches || [])
    } catch (e: unknown) { setError(`screen: ${e instanceof Error ? e.message : String(e)}`); setScreenHits([]) }
    finally { setScreenLoading(false) }
  }, [])

  useEffect(() => { screen() }, [screen])

  const focusVessel = (h: ScreenHit) => {
    const v = h.vessel
    if (v.lat == null || v.lon == null) return
    onFocus({
      kind: 'maritime',
      lon: v.lon,
      lat: v.lat,
      height: 500000,
      title: `⚠ SANCTIONED ${v.name || h.sanction.caption}`,
      lines: [
        `MMSI: ${v.mmsi || '—'}`,
        `MATCH SCORE: ${(h.sanction.score ?? 0).toFixed(2)}`,
        `DATASETS: ${(h.sanction.datasets || []).join(', ') || '—'}`,
        `TOPICS: ${(h.sanction.topics || []).join(', ') || '—'}`,
        `FLAG: ${v.flag || '—'}`,
      ],
    })
  }

  return (
    <div className="sanctions-panel">
      <div className="sanctions-status">
        {status ? (
          <>
            <span className={`stat-pill ${status.csv.fresh ? 'ok' : 'warn'}`}>BACKEND {status.backend.toUpperCase()}</span>
            <span className="stat-meta">{status.index_rows.toLocaleString()} entities · CSV {status.csv.size_mb} MB</span>
            <span className="stat-meta">{status.csv.age_sec != null ? `${(status.csv.age_sec / 3600).toFixed(1)}h old` : 'not loaded'}</span>
            <button className="data-refresh" onClick={refresh} disabled={refreshing}>{refreshing ? '…' : '↻ REFRESH CSV'}</button>
            <span className="stat-meta" title={status.license}>data: CC-BY · OpenSanctions</span>
          </>
        ) : (
          <span className="stat-meta">Loading status…</span>
        )}
      </div>

      {error && <div className="data-error">{error}</div>}

      <div className="sanctions-section">
        <h3>🔍 Watchlist search</h3>
        <div className="sanctions-toolbar">
          <input
            placeholder="Name, alias, IMO, MMSI…"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && search()}
          />
          <select value={schema} onChange={e => setSchema(e.target.value)}>
            <option value="">All schemas</option>
            <option value="Person">Person</option>
            <option value="Company">Company</option>
            <option value="Organization">Organization</option>
            <option value="Vessel">Vessel</option>
            <option value="Address">Address</option>
          </select>
          <button className="data-refresh" onClick={search} disabled={searching}>{searching ? '…' : 'SEARCH'}</button>
        </div>
        {results.length > 0 && (
          <div className="sanctions-results">
            {results.map(r => (
              <div key={r.entity_id} className={`sanc-card score-${Math.round((r.score ?? 0) * 10)}`}>
                <div className="sanc-head">
                  <span className="sanc-schema">{r.schema}</span>
                  <strong>{r.caption}</strong>
                  <span className="sanc-score">{((r.score ?? 0) * 100).toFixed(0)}%</span>
                </div>
                {(r.aliases?.length ?? 0) > 0 && (
                  <div className="sanc-aliases">aka: {r.aliases!.slice(0, 4).join(' · ')}</div>
                )}
                <div className="sanc-meta">
                  {(r.countries?.length ?? 0) > 0 && <span>🌐 {r.countries!.join(', ')}</span>}
                  {(r.topics?.length ?? 0) > 0 && <span>🏷 {r.topics!.join(', ')}</span>}
                  {(r.datasets?.length ?? 0) > 0 && <span>📚 {r.datasets!.slice(0, 4).join(', ')}</span>}
                </div>
                {(r.identifiers?.length ?? 0) > 0 && (
                  <div className="sanc-ids">IDs: <code>{r.identifiers!.slice(0, 5).join(' · ')}</code></div>
                )}
                {(r.reasons?.length ?? 0) > 0 && (
                  <div className="sanc-reasons">match: {r.reasons!.join(' · ')}</div>
                )}
                {r.url && <a href={r.url} target="_blank" rel="noreferrer" className="sanc-link">OpenSanctions page ↗</a>}
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="sanctions-section">
        <h3>🚢 AIS ↔ Sanctions screen <button className="data-refresh small" onClick={screen} disabled={screenLoading}>{screenLoading ? '…' : '↻'}</button></h3>
        {screenHits.length === 0 && !screenLoading && (
          <div className="data-info">No live vessel intersects the sanctions watchlist right now.</div>
        )}
        {screenHits.map((h, i) => (
          <div key={i} className="sanc-hit-row">
            <span className="hit-flag">⚠</span>
            <div className="hit-body">
              <div><strong>{h.vessel.name || '?'}</strong> <span className="hit-mmsi">{h.vessel.mmsi || '—'}</span> · {h.vessel.type || '—'}</div>
              <div className="hit-meta">
                matched: <code>{h.matched_term}</code> · {(h.sanction.score ?? 0).toFixed(2)} ·
                datasets: {(h.sanction.datasets || []).slice(0, 3).join(', ') || '—'}
              </div>
            </div>
            <button className="locate-mini" onClick={() => focusVessel(h)} disabled={h.vessel.lat == null}>◎</button>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Helper hook usable by Globe.tsx — returns a Set of MMSIs currently on the watchlist. */
export function useSanctionedVessels(intervalMs = 90000): Set<string> {
  const [hits, setHits] = useState<Set<string>>(new Set())
  useEffect(() => {
    let active = true
    const run = async () => {
      try {
        const r = await fetchApi('/api/sanctions/screen/vessels?min_score=0.85&limit=400')
        if (!r.ok) return
        const d = await r.json()
        if (!active) return
        const mmsi = new Set<string>()
        for (const m of d.matches || []) {
          if (m.vessel?.mmsi) mmsi.add(String(m.vessel.mmsi))
        }
        setHits(mmsi)
      } catch { /* ignore */ }
    }
    run()
    const t = setInterval(run, intervalMs)
    return () => { active = false; clearInterval(t) }
  }, [intervalMs])
  return hits
}
