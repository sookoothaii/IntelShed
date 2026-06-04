import { useEffect, useState } from 'react'

type Series = Record<string, { t: string; v: number }[]>

const SPARK_KEYS = ['cpu_temp_c', 'ram_pct', 'disk_pct', 'temp_c', 'humidity_pct'] as const

function Sparkline({ values, color }: { values: number[]; color: string }) {
  if (values.length < 2) return <span className="spark-empty">—</span>
  const w = 88
  const h = 22
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const pts = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * w
      const y = h - ((v - min) / span) * (h - 2) - 1
      return `${x},${y}`
    })
    .join(' ')
  return (
    <svg className="spark-svg" width={w} height={h} viewBox={`0 0 ${w} ${h}`}>
      <polyline fill="none" stroke={color} strokeWidth="1.5" points={pts} />
    </svg>
  )
}

export default function SensorSparklines({ nodeId, hours = 24 }: { nodeId: string; hours?: number }) {
  const [series, setSeries] = useState<Series | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setSeries(null)
    setErr(null)
    ;(async () => {
      try {
        const r = await fetch(`/api/node/${encodeURIComponent(nodeId)}/sensors/history?hours=${hours}`)
        if (!r.ok) throw new Error(`${r.status}`)
        const d = await r.json()
        if (!cancelled) setSeries(d.series || {})
      } catch (e) {
        if (!cancelled) setErr('no history')
      }
    })()
    return () => { cancelled = true }
  }, [nodeId, hours])

  if (err) return <div className="spark-block muted">{err}</div>
  if (!series) return <div className="spark-block muted">loading…</div>

  const rows = SPARK_KEYS.filter((k) => (series[k]?.length ?? 0) >= 2)
  if (!rows.length) {
    const any = Object.keys(series).filter((k) => (series[k]?.length ?? 0) >= 2)
    if (!any.length) return <div className="spark-block muted">no 24h series yet</div>
    return (
      <div className="spark-block">
        <div className="spark-head">SENSOR TREND (24H)</div>
        {any.slice(0, 4).map((k) => (
          <div key={k} className="spark-row">
            <span className="spark-label">{k}</span>
            <Sparkline values={series[k].map((p) => p.v)} color="#00e5a0" />
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="spark-block">
      <div className="spark-head">SENSOR TREND (24H)</div>
      {rows.map((k) => (
        <div key={k} className="spark-row">
          <span className="spark-label">{k.replace(/_/g, ' ')}</span>
          <Sparkline values={series[k].map((p) => p.v)} color="#00e5a0" />
        </div>
      ))}
    </div>
  )
}
