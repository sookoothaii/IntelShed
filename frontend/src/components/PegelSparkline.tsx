import { useEffect, useState } from 'react'
import { fetchApi } from '../lib/networkFetch';

type Point = { t: string; v: number }
type Payload = {
  uuid: string
  name: string
  water: string
  unit: string
  hours: number
  count: number
  points: Point[]
  summary?: { min: number; max: number; first: number; last: number; delta: number } | null
  error?: string
}

interface Props {
  uuid: string
  hours?: number
  width?: number
  height?: number
  compact?: boolean
  /** Color of the line; falls back to neutral cyan. */
  color?: string
}

export default function PegelSparkline({ uuid, hours = 24, width = 220, height = 56, compact = false, color = '#4fc3f7' }: Props) {
  const [data, setData] = useState<Payload | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setData(null); setError(null)
    fetchApi(`/api/pegel/${encodeURIComponent(uuid)}/history?hours=${hours}`)
      .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
      .then(d => { if (active) setData(d) })
      .catch(err => { if (active) setError(err.message || String(err)) })
    return () => { active = false }
  }, [uuid, hours])

  if (error) {
    return <div className="sparkline-error" title={error}>⚠ no history</div>
  }
  if (!data) {
    return <div className="sparkline-skeleton" style={{ width, height }} />
  }
  const pts = data.points || []
  if (pts.length < 2) {
    return <div className="sparkline-empty" style={{ width, height }}>NO DATA</div>
  }

  const vals = pts.map(p => p.v)
  const lo = Math.min(...vals)
  const hi = Math.max(...vals)
  const range = Math.max(hi - lo, 0.5)
  const pad = 2
  const w = width - pad * 2
  const h = height - pad * 2
  const stepX = w / (pts.length - 1)
  const path = pts.map((p, i) => {
    const x = pad + i * stepX
    const y = pad + h - ((p.v - lo) / range) * h
    return `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
  }).join(' ')

  const last = pts[pts.length - 1]
  const first = pts[0]
  const dirColor = last.v > first.v ? '#ff6b35' : last.v < first.v ? '#4fc3f7' : color
  const delta = data.summary?.delta ?? (last.v - first.v)
  const dirArrow = delta > 0 ? '▲' : delta < 0 ? '▼' : '·'

  return (
    <div className={`sparkline ${compact ? 'sparkline-compact' : ''}`}>
      <svg width={width} height={height} className="sparkline-svg" aria-label={`${data.name} ${hours}h history`}>
        <defs>
          <linearGradient id={`spark-grad-${uuid}`} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.45" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={`${path} L ${pad + (pts.length - 1) * stepX} ${pad + h} L ${pad} ${pad + h} Z`} fill={`url(#spark-grad-${uuid})`} />
        <path d={path} fill="none" stroke={color} strokeWidth={1.4} />
        <circle cx={pad + (pts.length - 1) * stepX} cy={pad + h - ((last.v - lo) / range) * h} r={2.4} fill={dirColor} />
      </svg>
      {!compact && (
        <div className="sparkline-meta">
          <span style={{ color: dirColor }}>{dirArrow} {Math.abs(delta).toFixed(1)} {data.unit}</span>
          <span style={{ color: '#6f8c84' }}>{hours}h · n={pts.length}</span>
          <span style={{ color: '#00e5a0' }}>now {last.v.toFixed(1)} {data.unit}</span>
        </div>
      )}
    </div>
  )
}
