import { useCallback, useEffect, useState } from 'react'
import type { FocusTarget } from '../lib/focus'
import { fetchApi } from '../lib/networkFetch'

type WeatherCurrent = {
  time?: string
  temperature_c?: number
  humidity_pct?: number
  wind_speed_ms?: number
  wind_direction_deg?: number
  precip_mm_3h?: number
  pressure_hpa?: number
  weather_code?: number
}

type WeatherHourly = {
  time?: string
  temperature_c?: number
  wind_speed_ms?: number
  wind_direction_deg?: number
  precip_prob_pct?: number
}

export type WeatherPayload = {
  lat: number
  lon: number
  source?: string
  model?: string
  timezone?: string
  current?: WeatherCurrent
  hourly?: WeatherHourly[]
  error?: string
}

type WindyConfig = {
  point_configured?: boolean
  map_configured?: boolean
  map_key?: string | null
  default_lat?: number
  default_lon?: number
  regions?: string[]
}

function windArrow(deg: number | undefined): string {
  if (deg == null) return '—'
  const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
  return dirs[Math.round(deg / 45) % 8]
}

export default function WeatherSection({
  onFocus,
  onOpenWindyMap,
}: {
  onFocus: (f: Omit<FocusTarget, 'ts'>) => void
  onOpenWindyMap: (lat: number, lon: number) => void
}) {
  const [config, setConfig] = useState<WindyConfig | null>(null)
  const [lat, setLat] = useState(9.55)
  const [lon, setLon] = useState(100.05)
  const [region, setRegion] = useState('thailand')
  const [weather, setWeather] = useState<WeatherPayload | null>(null)
  const [gridCount, setGridCount] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchApi('/api/windy/config')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!d) return
        setConfig(d)
        if (d.default_lat != null) setLat(d.default_lat)
        if (d.default_lon != null) setLon(d.default_lon)
      })
      .catch(() => {})
  }, [])

  const loadPoint = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await fetchApi(`/api/weather?lat=${lat}&lon=${lon}`)
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
      setWeather(await r.json())
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [lat, lon])

  const loadGridMeta = useCallback(async () => {
    try {
      const r = await fetchApi(`/api/windy/grid?region=${encodeURIComponent(region)}`)
      if (r.ok) {
        const d = await r.json()
        setGridCount(d.count ?? 0)
      }
    } catch {
      setGridCount(null)
    }
  }, [region])

  useEffect(() => {
    loadPoint()
    loadGridMeta()
  }, [loadPoint, loadGridMeta])

  const cur = weather?.current
  const canMap = Boolean(config?.map_configured && config?.map_key)

  return (
    <div className="weather-section">
      <div className="weather-controls">
        <button type="button" onClick={loadPoint} disabled={loading} className="refresh-btn">
          {loading ? 'LOADING…' : '↻ REFRESH'}
        </button>
        {weather?.source && (
          <span className="data-count">
            {weather.source.toUpperCase()}
            {weather.model ? ` · ${weather.model}` : ''}
          </span>
        )}
        {canMap && (
          <button type="button" className="refresh-btn" onClick={() => onOpenWindyMap(lat, lon)}>
            OPEN WINDY MAP
          </button>
        )}
      </div>

      {!config?.point_configured && (
        <div className="health-status pending">Point forecast: Open-Meteo fallback (no WINDY_POINT_API_KEY)</div>
      )}

      <div className="weather-coords">
        <label>
          LAT
          <input
            type="number"
            step="0.01"
            value={lat}
            onChange={(e) => setLat(parseFloat(e.target.value) || 0)}
          />
        </label>
        <label>
          LON
          <input
            type="number"
            step="0.01"
            value={lon}
            onChange={(e) => setLon(parseFloat(e.target.value) || 0)}
          />
        </label>
        <button
          type="button"
          className="locate-mini"
          onClick={() =>
            onFocus({
              kind: 'weather',
              lat,
              lon,
              title: `Weather ${lat.toFixed(2)}, ${lon.toFixed(2)}`,
              height: 800000,
              lines: cur
                ? [
                    `TEMP: ${cur.temperature_c ?? '—'}°C`,
                    `WIND: ${cur.wind_speed_ms ?? '—'} m/s ${windArrow(cur.wind_direction_deg)}`,
                  ]
                : [],
            })
          }
        >
          ◎ LOCATE
        </button>
      </div>

      {error && <div className="health-status pending">{error}</div>}

      {cur && (
        <div className="weather-cards">
          <div className="iss-card">
            <span>TEMP</span>
            <strong>{cur.temperature_c != null ? `${cur.temperature_c}°C` : '—'}</strong>
          </div>
          <div className="iss-card">
            <span>WIND</span>
            <strong>
              {cur.wind_speed_ms != null ? `${cur.wind_speed_ms} m/s` : '—'}{' '}
              {windArrow(cur.wind_direction_deg)}
            </strong>
          </div>
          <div className="iss-card">
            <span>HUMIDITY</span>
            <strong>{cur.humidity_pct != null ? `${cur.humidity_pct}%` : '—'}</strong>
          </div>
          <div className="iss-card">
            <span>PRESSURE</span>
            <strong>{cur.pressure_hpa != null ? `${cur.pressure_hpa} hPa` : '—'}</strong>
          </div>
          <div className="iss-card">
            <span>RAIN 3H</span>
            <strong>{cur.precip_mm_3h != null ? `${cur.precip_mm_3h} mm` : '—'}</strong>
          </div>
        </div>
      )}

      <div className="weather-grid-panel">
        <div className="weather-controls">
          <span className="data-count">Globe grid layer</span>
          <select value={region} onChange={(e) => setRegion(e.target.value)}>
            {(config?.regions || ['thailand', 'asean', 'operator']).map((r) => (
              <option key={r} value={r}>
                {r.toUpperCase()}
              </option>
            ))}
          </select>
          {gridCount != null && <span className="data-count">{gridCount} cells</span>}
        </div>
        <p className="weather-hint">
          Enable <strong>WEATHER</strong> on the globe ENV layer strip to show temperature labels on the map.
        </p>
      </div>

      {weather?.hourly && weather.hourly.length > 0 && (
        <div className="weather-hourly">
          <h4>24H OUTLOOK</h4>
          <div className="weather-hourly-scroll">
            {weather.hourly.map((h) => (
              <div key={h.time} className="weather-hourly-cell">
                <div className="weather-hourly-time">
                  {h.time ? new Date(h.time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—'}
                </div>
                <div className="weather-hourly-temp">{h.temperature_c != null ? `${Math.round(h.temperature_c)}°` : '—'}</div>
                <div className="weather-hourly-wind">{h.wind_speed_ms != null ? `${h.wind_speed_ms}` : '—'} m/s</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
