type SparklineProps = {
  data: number[];
  width?: number;
  height?: number;
  stroke?: string;
  fill?: boolean;
  baseline?: boolean;
};

// Lightweight inline-SVG sparkline. Auto-colors green/red by net direction
// unless an explicit stroke is supplied. No external charting dependency.
export default function Sparkline({
  data,
  width = 132,
  height = 38,
  stroke,
  fill = true,
  baseline = true,
}: SparklineProps) {
  const series = (data || []).filter((v) => Number.isFinite(v));
  if (series.length < 2) {
    return (
      <svg width={width} height={height} className="spark">
        <line
          x1={0}
          y1={height / 2}
          x2={width}
          y2={height / 2}
          stroke="rgba(111,140,132,0.4)"
          strokeWidth={1}
          strokeDasharray="2 3"
        />
      </svg>
    );
  }

  const min = Math.min(...series);
  const max = Math.max(...series);
  const range = max - min || 1;
  const n = series.length;
  const pad = 2;
  const innerH = height - pad * 2;

  const pts = series.map((v, i) => {
    const x = (i / (n - 1)) * width;
    const y = pad + innerH - ((v - min) / range) * innerH;
    return [x, y] as const;
  });

  const up = series[n - 1] >= series[0];
  const color = stroke || (up ? '#00e5a0' : '#ff4d5e');
  const gid = `sg-${Math.round(min)}-${n}-${up ? 'u' : 'd'}`;

  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ');
  const area = `M0 ${height} ${pts.map((p) => `L${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' ')} L${width} ${height} Z`;

  // Baseline = first value of the window, to read drawdown at a glance.
  const baseY = pad + innerH - ((series[0] - min) / range) * innerH;

  return (
    <svg width={width} height={height} className="spark" preserveAspectRatio="none">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.32" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {baseline && (
        <line
          x1={0}
          y1={baseY}
          x2={width}
          y2={baseY}
          stroke="rgba(111,140,132,0.35)"
          strokeWidth={1}
          strokeDasharray="2 3"
        />
      )}
      {fill && <path d={area} fill={`url(#${gid})`} stroke="none" />}
      <path
        d={line}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={pts[n - 1][0]} cy={pts[n - 1][1]} r={1.8} fill={color} />
    </svg>
  );
}
