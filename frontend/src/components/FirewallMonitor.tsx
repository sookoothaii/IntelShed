interface FirewallMeta {
  action: string
  risk_score: number
  flags?: string[]
  policy_violations?: string[]
}

export default function FirewallMonitor({ meta }: { meta: FirewallMeta | null }) {
  if (!meta) return null
  const { action, risk_score, flags, policy_violations } = meta
  const isBlock = action === 'block'
  const color = isBlock ? '#ff4444' : risk_score > 0.5 ? '#ffaa00' : '#44ff44'

  return (
    <div style={{
      marginTop: 10, padding: 10, border: `1px solid ${color}`, borderRadius: 4,
      background: 'rgba(0,0,0,0.5)', fontSize: 12, fontFamily: 'monospace'
    }}>
      <div style={{ color, fontWeight: 'bold', marginBottom: 5 }}>
        🛡️ FIREWALL: {action.toUpperCase()} (Risk: {risk_score.toFixed(2)})
      </div>
      {flags && flags.length > 0 && (
        <div style={{ color: '#aaa' }}>Flags: {flags.join(', ')}</div>
      )}
      {policy_violations && policy_violations.length > 0 && (
        <div style={{ color: '#ff4444', marginTop: 4 }}>
          Violations: {policy_violations.join(' | ')}
        </div>
      )}
    </div>
  )
}
