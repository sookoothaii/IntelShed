import { memo } from 'react'

export interface TrustGaugeProps {
  value: number | null | undefined
  label: string
  size?: number
  compact?: boolean
}

function gaugeColor(v: number): string {
  if (v >= 0.7) return 'var(--green)'
  if (v >= 0.4) return 'var(--amber)'
  return 'var(--red)'
}

function TrustGaugeBase({ value, label, size = 80, compact = false }: TrustGaugeProps) {
  const v = value != null && !isNaN(value) ? Math.max(0, Math.min(1, value)) : null
  const pct = v != null ? Math.round(v * 100) : 0
  const stroke = compact ? 3 : 4
  const radius = size / 2 - stroke
  const circumference = Math.PI * radius
  const dashoffset = v != null ? circumference * (1 - v) : circumference
  const color = v != null ? gaugeColor(v) : 'var(--txt-muted)'
  const half = size / 2
  const height = half + stroke + 2

  return (
    <div
      className={`trust-gauge${compact ? ' trust-gauge--compact' : ''}`}
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={v != null ? pct : 0}
      aria-label={label}
    >
      <div className="trust-gauge-arc" style={{ width: size, height }}>
        <svg width={size} height={height} viewBox={`0 0 ${size} ${height}`}>
          <path
            d={`M ${stroke} ${half} A ${radius} ${radius} 0 0 1 ${size - stroke} ${half}`}
            fill="none"
            stroke="var(--line)"
            strokeWidth={stroke}
            strokeLinecap="round"
          />
          <path
            d={`M ${stroke} ${half} A ${radius} ${radius} 0 0 1 ${size - stroke} ${half}`}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashoffset}
            style={{ transition: 'stroke-dashoffset 500ms ease' }}
          />
        </svg>
        <div
          className="trust-gauge-value"
          style={{ fontSize: compact ? 11 : 14 }}
        >
          {v != null ? `${pct}%` : '—'}
        </div>
      </div>
      <div className="trust-gauge-label">{label}</div>
    </div>
  )
}

const TrustGauge = memo(TrustGaugeBase)
export default TrustGauge
