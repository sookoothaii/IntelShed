import { useState, useEffect } from 'react'
import { fetchApi } from '../lib/networkFetch';

interface FirewallEntry {
  timestamp: number
  query: string
  blocked: boolean
  risk_score: number
  confidence?: number
  evidence_type?: string
  source?: string
  engine?: string
  score_origin?: {
    layer?: string
    primary_cause?: string
    rule_id?: string
    detector_id?: string
  }
  routing_metadata?: RoutingMetadata
  semantic_intelligence?: SemanticIntelligence
  cognitive_probes?: CognitiveProbes
  tags?: string[]
  matched_patterns?: string[]
  category?: string
  should_block?: boolean
  mirage_active?: boolean
  mirage_response_type?: string
  decision_trace?: Record<string, unknown>
}

interface RoutingMetadata {
  perimeter_fast_path?: boolean
  perimeter_processing_time_ms?: number
  zedd_latency_ms?: number
  request_queue?: { processing_ms?: number }
  bypassed_checks?: string[]
  execution_context?: string
}

interface SemanticIntelligence {
  primary_intent?: string
  intent_confidence?: number
  router_decision?: string
  all_scores?: Record<string, { vector_score: number }>
}

interface CognitiveProbes {
  decision?: string
  risk_score?: number
  confidence?: number
  tier_used?: string
  tier?: string
  latency_ms?: number
}

interface FirewallTestResult {
  blocked?: boolean
  should_block?: boolean
  risk_score?: number
  confidence?: number
  evidence_type?: string
  source?: string
  engine?: string
  score_origin?: {
    layer?: string
    primary_cause?: string
    rule_id?: string
    detector_id?: string
  }
  tags?: string[]
  error?: string
  mirage_active?: boolean
  mirage_response_type?: string
}

function StatusBadge({ status, label }: { status: 'online' | 'offline' | 'warn'; label: string }) {
  const colors = {
    online: '#00c853',
    offline: '#ff2d00',
    warn: '#ffaa00',
  }
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 4,
      padding: '2px 8px',
      borderRadius: 3,
      background: `${colors[status]}22`,
      border: `1px solid ${colors[status]}44`,
      color: colors[status],
      fontSize: 10,
      fontFamily: 'monospace',
      fontWeight: 'bold',
    }}>
      <span style={{
        width: 6,
        height: 6,
        borderRadius: '50%',
        background: colors[status],
        display: 'inline-block',
        animation: status === 'online' ? 'pulse 2s infinite' : 'none',
      }} />
      {label}
    </span>
  )
}

function RiskBar({ risk }: { risk: number }) {
  const color = risk >= 0.9 ? '#ff2d00' : risk >= 0.7 ? '#ff6b35' : risk >= 0.4 ? '#ffaa00' : '#00c853'
  const label = risk >= 0.9 ? 'CRITICAL' : risk >= 0.7 ? 'HIGH' : risk >= 0.4 ? 'MEDIUM' : 'LOW'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 140 }}>
      <div style={{ flex: 1, height: 4, background: '#1a2a24', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ width: `${Math.min(risk * 100, 100)}%`, height: '100%', background: color, borderRadius: 2, transition: 'width 0.3s ease' }} />
      </div>
      <span style={{ fontSize: 9, color, fontWeight: 'bold', minWidth: 50, textAlign: 'right' }}>{label}</span>
    </div>
  )
}

function LayerBadge({ layer }: { layer: string }) {
  const colors: Record<string, string> = {
    zedd_pre_filter: '#00e5a0',
    perimeter_whitelist: '#00c853',
    hf_security_gate: '#ff2d00',
    perimeter_fast_path: '#00b0ff',
    semantic_gate: '#ffaa00',
    cognitive_probe: '#e040fb',
    orchestrator: '#ff6b35',
    default: '#6f8c84',
  }
  const color = colors[layer?.toLowerCase() || ''] || colors.default
  return (
    <span style={{
      fontSize: 9,
      padding: '1px 6px',
      borderRadius: 3,
      background: `${color}22`,
      border: `1px solid ${color}44`,
      color,
      fontFamily: 'monospace',
    }}>
      {layer || '—'}
    </span>
  )
}

function normalizeHistoryEntry(item: Record<string, unknown>): FirewallEntry {
  const rawTs = Number(item.timestamp ?? 0)
  const timestamp = rawTs > 1e12 ? rawTs : rawTs * 1000
  const source = String(item.source ?? item.engine ?? '')
  const blocked = Boolean(item.blocked || item.should_block)
  const matched = Array.isArray(item.matched_patterns) ? item.matched_patterns as string[] : []
  const isSlim = source.includes('slim') || String(item.engine ?? '').includes('slim')
  return {
    timestamp,
    query: String(item.query ?? item.text_preview ?? ''),
    blocked,
    risk_score: typeof item.risk_score === 'number'
      ? item.risk_score
      : (blocked && isSlim ? 1 : 0),
    confidence: typeof item.confidence === 'number' ? item.confidence : undefined,
    evidence_type: source || String(item.engine ?? '—'),
    source,
    engine: item.engine ? String(item.engine) : undefined,
    score_origin: item.score_origin as FirewallEntry['score_origin'],
    routing_metadata: item.routing_metadata as RoutingMetadata | undefined,
    semantic_intelligence: item.semantic_intelligence as SemanticIntelligence | undefined,
    cognitive_probes: item.cognitive_probes as CognitiveProbes | undefined,
    tags: item.tags as string[] | undefined,
    matched_patterns: matched,
    category: item.category ? String(item.category) : undefined,
    should_block: item.should_block as boolean | undefined,
    mirage_active: item.mirage_active as boolean | undefined,
    mirage_response_type: item.mirage_response_type as string | undefined,
    decision_trace: item.decision_trace as Record<string, unknown> | undefined,
  }
}

export default function FirewallPanel() {
  const [history, setHistory] = useState<FirewallEntry[]>([])
  const [selected, setSelected] = useState<FirewallEntry | null>(null)
  const [filter, setFilter] = useState<'all' | 'blocked' | 'allowed'>('all')
  const [testQuery, setTestQuery] = useState('')
  const [testResult, setTestResult] = useState<FirewallTestResult | null>(null)
  const [testBusy, setTestBusy] = useState(false)
  const [firewallStatus, setFirewallStatus] = useState<'online' | 'offline' | 'warn'>('offline')
  const [slimGuardOn, setSlimGuardOn] = useState(true)
  const [statusDetails, setStatusDetails] = useState('')

  const loadHistory = async () => {
    try {
      const r = await fetchApi('/api/firewall/history?limit=50')
      if (!r.ok) return
      const d = await r.json()
      const items = Array.isArray(d.items) ? d.items.map(normalizeHistoryEntry) : []
      setHistory(items)
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    loadHistory()
    const t = setInterval(loadHistory, 10000)
    return () => clearInterval(t)
  }, [])

  useEffect(() => {
    const checkStatus = async () => {
      try {
        const r = await fetchApi('/api/firewall/status', { method: 'GET' })
        if (r.ok) {
          const d = await r.json()
          setSlimGuardOn(Boolean(d.slim_guard))
          const hakGalUp = Boolean(d.reachable)
          setFirewallStatus(hakGalUp ? 'online' : d.slim_guard ? 'warn' : 'offline')
          const slimCount = d.slim_pattern_count ?? '—'
          setStatusDetails(
            d.slim_guard
              ? `SLIM ${slimCount} patterns · ${hakGalUp ? 'HAK_GAL online' : 'HAK_GAL offline'}`
              : (d.version || 'HAK_GAL v9.4+')
          )
        } else {
          setFirewallStatus('offline')
          setStatusDetails('HTTP ' + r.status)
        }
      } catch {
        setFirewallStatus('offline')
        setStatusDetails('Connection failed')
      }
    }
    checkStatus()
    const t = setInterval(checkStatus, 30000)
    return () => clearInterval(t)
  }, [])

  const filtered = history.filter((h) => {
    if (filter === 'blocked') return h.blocked || h.should_block
    if (filter === 'allowed') return !h.blocked && !h.should_block
    return true
  })

  const stats = {
    total: history.length,
    blocked: history.filter(h => h.blocked || h.should_block).length,
    allowed: history.filter(h => !h.blocked && !h.should_block).length,
    avgRisk: history.length > 0 ? history.reduce((a, h) => a + (h.risk_score || 0), 0) / history.length : 0,
    avgLatency: history.length > 0
      ? history.reduce((a, h) => a + (h.routing_metadata?.request_queue?.processing_ms || 0), 0) / history.length
      : 0,
  }

  const runTest = async () => {
    if (!testQuery.trim()) return
    setTestBusy(true)
    setTestResult(null)
    try {
      const r = await fetchApi('/api/firewall/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: testQuery.trim() }),
      })
      const d = await r.json()
      setTestResult(d)
      loadHistory()
    } catch (e) {
      setTestResult({ error: String(e) })
    } finally {
      setTestBusy(false)
    }
  }

  return (
    <div className="panel firewall" style={{ padding: '0 18px', display: 'flex', flexDirection: 'column', gap: 12, height: '100%' }}>
      <h2 style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 0, flexWrap: 'wrap' }}>
        <span>🛡️</span>
        FIREWALL MONITOR
        {slimGuardOn && (
          <StatusBadge status="online" label="SLIM ON" />
        )}
        <StatusBadge
          status={firewallStatus}
          label={
            firewallStatus === 'online'
              ? 'HAK_GAL ONLINE'
              : slimGuardOn
                ? 'HAK_GAL OFFLINE'
                : 'HAK_GAL OFFLINE'
          }
        />
        {statusDetails && <span style={{ fontSize: 10, color: '#6f8c84', marginLeft: 'auto' }}>{statusDetails}</span>}
      </h2>

      {/* Stats Bar */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(5, 1fr)',
        gap: 8,
        padding: 12,
        background: 'rgba(0,0,0,0.3)',
        borderRadius: 8,
        border: '1px solid #1a2a24',
      }}>
        <StatBox label="TOTAL QUERIES" value={stats.total} color="#00e5a0" />
        <StatBox label="BLOCKED" value={stats.blocked} color="#ff2d00" />
        <StatBox label="ALLOWED" value={stats.allowed} color="#00c853" />
        <StatBox label="AVG RISK" value={`${(stats.avgRisk * 100).toFixed(1)}%`} color={stats.avgRisk >= 0.5 ? '#ff6b35' : '#00c853'} />
        <StatBox label="AVG LATENCY" value={`${Math.round(stats.avgLatency)}ms`} color="#00b0ff" />
      </div>

      {/* Test Area */}
      <div style={{
        padding: 12,
        background: 'rgba(0,0,0,0.2)',
        borderRadius: 8,
        border: '1px solid #1a2a24',
      }}>
        <div style={{ fontSize: 11, color: '#8a9a94', marginBottom: 8, fontWeight: 'bold', textTransform: 'uppercase', letterSpacing: 1 }}>
          Quick Test
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            style={{ flex: 1, fontSize: 12 }}
            placeholder="Enter a query to test against HAK_GAL..."
            value={testQuery}
            onChange={(e) => setTestQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && runTest()}
          />
          <button onClick={runTest} disabled={testBusy} style={{ whiteSpace: 'nowrap' }}>
            {testBusy ? '⏳ SCANNING...' : 'TEST FIREWALL'}
          </button>
        </div>
        {testResult && (
          <div style={{ marginTop: 10 }}>
            {testResult.error ? (
              <div style={{ color: '#ff2d00', fontSize: 11 }}>Error: {testResult.error}</div>
            ) : (
              <TestResultView result={testResult} />
            )}
          </div>
        )}
      </div>

      {/* History Table */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
          <span style={{ fontSize: 11, color: '#8a9a94', fontWeight: 'bold', textTransform: 'uppercase', letterSpacing: 1 }}>
            Query History
          </span>
          <div style={{ display: 'flex', gap: 4 }}>
            {(['all', 'blocked', 'allowed'] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                style={{
                  padding: '3px 10px',
                  fontSize: 10,
                  fontFamily: 'monospace',
                  background: filter === f ? 'rgba(0,229,160,0.2)' : 'rgba(0,0,0,0.3)',
                  border: filter === f ? '1px solid #00e5a0' : '1px solid #1a2a24',
                  color: filter === f ? '#00e5a0' : '#6f8c84',
                  cursor: 'pointer',
                  borderRadius: 3,
                  textTransform: 'uppercase',
                }}
              >
                {f}
              </button>
            ))}
          </div>
          {history.length > 0 && (
            <span style={{ marginLeft: 'auto', fontSize: 10, color: '#6f8c84' }}>
              Showing {filtered.length} of {history.length}
            </span>
          )}
        </div>

        <div style={{
          flex: 1,
          overflow: 'auto',
          border: '1px solid #1a2a24',
          borderRadius: 8,
          background: 'rgba(0,0,0,0.2)',
        }}>
          {filtered.length === 0 ? (
            <div style={{ padding: 40, textAlign: 'center', color: '#6f8c84', fontSize: 12 }}>
              {history.length === 0
                ? 'No firewall queries yet. Send a message in the AI chat with firewall enabled to see results here.'
                : 'No queries match the current filter.'}
            </div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
              <thead>
                <tr style={{ background: 'rgba(0,0,0,0.4)', position: 'sticky', top: 0 }}>
                  <th style={{ padding: '8px 10px', textAlign: 'left', color: '#8a9a94', fontWeight: 'normal', borderBottom: '1px solid #1a2a24', width: 80 }}>Time</th>
                  <th style={{ padding: '8px 10px', textAlign: 'left', color: '#8a9a94', fontWeight: 'normal', borderBottom: '1px solid #1a2a24' }}>Query</th>
                  <th style={{ padding: '8px 10px', textAlign: 'center', color: '#8a9a94', fontWeight: 'normal', borderBottom: '1px solid #1a2a24', width: 80 }}>Status</th>
                  <th style={{ padding: '8px 10px', textAlign: 'left', color: '#8a9a94', fontWeight: 'normal', borderBottom: '1px solid #1a2a24', width: 140 }}>Risk</th>
                  <th style={{ padding: '8px 10px', textAlign: 'center', color: '#8a9a94', fontWeight: 'normal', borderBottom: '1px solid #1a2a24', width: 100 }}>Layer</th>
                  <th style={{ padding: '8px 10px', textAlign: 'center', color: '#8a9a94', fontWeight: 'normal', borderBottom: '1px solid #1a2a24', width: 60 }}>Detail</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((entry, i) => (
                  <tr
                    key={i}
                    onClick={() => setSelected(entry)}
                    style={{
                      cursor: 'pointer',
                      background: selected?.timestamp === entry.timestamp ? 'rgba(0,229,160,0.1)' : i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)',
                      borderBottom: '1px solid #0d1a14',
                    }}
                  >
                    <td style={{ padding: '6px 10px', color: '#6f8c84', fontFamily: 'monospace', fontSize: 10 }}>
                      {new Date(entry.timestamp).toLocaleTimeString()}
                    </td>
                    <td style={{ padding: '6px 10px', color: '#c8d4cf', maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {entry.query}
                    </td>
                    <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                      <span style={{
                        color: entry.blocked || entry.should_block ? '#ff2d00' : '#00c853',
                        fontWeight: 'bold',
                        fontSize: 10,
                      }}>
                        {entry.blocked || entry.should_block ? '🛡️ BLOCK' : '✅ ALLOW'}
                      </span>
                    </td>
                    <td style={{ padding: '6px 10px' }}>
                      <RiskBar risk={entry.risk_score ?? 0} />
                    </td>
                    <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                      <LayerBadge layer={entry.score_origin?.layer || entry.source || entry.evidence_type || '—'} />
                    </td>
                    <td style={{ padding: '6px 10px', textAlign: 'center' }}>
                      <button style={{
                        padding: '2px 8px',
                        fontSize: 9,
                        background: 'rgba(0,229,160,0.1)',
                        border: '1px solid rgba(0,229,160,0.3)',
                        color: '#00e5a0',
                        borderRadius: 3,
                        cursor: 'pointer',
                      }}>
                        VIEW
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Detail Panel */}
      {selected && (
        <DetailPanel entry={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}

function StatBox({ label, value, color }: { label: string; value: string | number; color: string }) {
  return (
    <div style={{ textAlign: 'center', padding: '6px 4px' }}>
      <div style={{ fontSize: 18, fontWeight: 'bold', color, fontFamily: 'monospace' }}>{value}</div>
      <div style={{ fontSize: 9, color: '#6f8c84', textTransform: 'uppercase', letterSpacing: 1, marginTop: 2 }}>{label}</div>
    </div>
  )
}

function TestResultView({ result }: { result: FirewallTestResult }) {
  const blocked = result.blocked || result.should_block
  const risk = result.risk_score ?? 0
  const confidence = result.confidence ?? 0
  const color = blocked ? '#ff2d00' : '#00c853'

  return (
    <div style={{
      border: `1px solid ${color}33`,
      borderRadius: 6,
      background: `${color}08`,
      padding: 10,
      overflow: 'hidden',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, paddingBottom: 8, borderBottom: `1px solid ${color}22` }}>
        <span style={{ fontSize: 16 }}>{blocked ? '🛡️' : '✅'}</span>
        <strong style={{ fontSize: 12, color }}>{blocked ? 'BLOCKED' : 'ALLOWED'}</strong>
        <span style={{ marginLeft: 'auto', fontSize: 10, color: '#6f8c84', fontFamily: 'monospace' }}>
          Risk: {(risk * 100).toFixed(1)}% | Confidence: {(confidence * 100).toFixed(0)}%
        </span>
      </div>
      <div style={{ fontSize: 10, color: '#8a9a94', lineHeight: 1.5 }}>
        <div><strong style={{ color: '#c8d4cf' }}>Evidence:</strong> {result.evidence_type || '—'}</div>
        {result.score_origin?.layer && <div><strong style={{ color: '#c8d4cf' }}>Layer:</strong> {result.score_origin.layer}</div>}
        {result.score_origin?.primary_cause && <div><strong style={{ color: '#c8d4cf' }}>Cause:</strong> {result.score_origin.primary_cause}</div>}
        {result.tags && result.tags.length > 0 && <div><strong style={{ color: '#c8d4cf' }}>Tags:</strong> {result.tags.join(', ')}</div>}
      </div>
      {result.mirage_active && (
        <div style={{ marginTop: 8, padding: '6px 8px', background: 'rgba(255,45,0,0.1)', borderRadius: 4, fontSize: 10, color: '#ff6b35' }}>
          🎭 MIRAGE ACTIVE — Response: {result.mirage_response_type}
        </div>
      )}
    </div>
  )
}

function DetailPanel({ entry, onClose }: { entry: FirewallEntry; onClose: () => void }) {
  const blocked = entry.blocked || entry.should_block
  const color = blocked ? '#ff2d00' : '#00c853'

  return (
    <div style={{
      position: 'fixed',
      top: 80,
      right: 20,
      width: 520,
      maxHeight: 'calc(100vh - 120px)',
      background: 'rgba(10,15,13,0.98)',
      border: '1px solid #1a2a24',
      borderRadius: 10,
      padding: 16,
      overflow: 'auto',
      zIndex: 100,
      boxShadow: '0 0 40px rgba(0,0,0,0.8)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, paddingBottom: 10, borderBottom: `1px solid ${color}33` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 18 }}>{blocked ? '🛡️' : '✅'}</span>
          <div>
            <div style={{ fontSize: 14, fontWeight: 'bold', color }}>{blocked ? 'BLOCKED' : 'ALLOWED'}</div>
            <div style={{ fontSize: 10, color: '#6f8c84' }}>{new Date(entry.timestamp).toLocaleString()}</div>
          </div>
        </div>
        <button onClick={onClose} style={{ fontSize: 16, background: 'none', border: 'none', color: '#6f8c84', cursor: 'pointer' }}>×</button>
      </div>

      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 10, color: '#8a9a94', marginBottom: 4, textTransform: 'uppercase', letterSpacing: 1 }}>Query</div>
        <div style={{ fontSize: 12, color: '#c8d4cf', padding: 8, background: 'rgba(0,0,0,0.3)', borderRadius: 4, wordBreak: 'break-word' }}>
          {entry.query}
        </div>
      </div>

      <DetailSection title="Risk Assessment">
        <DetailRow label="Risk Score" value={`${((entry.risk_score ?? 0) * 100).toFixed(1)}%`} />
        <DetailRow label="Confidence" value={`${((entry.confidence ?? 0) * 100).toFixed(1)}%`} />
        <DetailRow label="Evidence Type" value={entry.evidence_type || '—'} />
        <DetailRow label="Category" value={entry.category || '—'} />
      </DetailSection>

      <DetailSection title="Detection Layer">
        <DetailRow label="Layer" value={entry.score_origin?.layer || '—'} />
        <DetailRow label="Rule ID" value={entry.score_origin?.rule_id || '—'} />
        <DetailRow label="Detector" value={entry.score_origin?.detector_id || '—'} />
        <DetailRow label="Primary Cause" value={entry.score_origin?.primary_cause || '—'} />
      </DetailSection>

      {entry.cognitive_probes && (
        <DetailSection title="Cognitive Probes">
          <DetailRow label="Decision" value={entry.cognitive_probes.decision || '—'} />
          <DetailRow label="Risk" value={entry.cognitive_probes.risk_score != null ? `${(entry.cognitive_probes.risk_score * 100).toFixed(1)}%` : '—'} />
          <DetailRow label="Confidence" value={entry.cognitive_probes.confidence != null ? `${(entry.cognitive_probes.confidence * 100).toFixed(1)}%` : '—'} />
          <DetailRow label="Tier" value={entry.cognitive_probes.tier_used || entry.cognitive_probes.tier || '—'} />
          <DetailRow label="Latency" value={entry.cognitive_probes.latency_ms != null ? `${Math.round(entry.cognitive_probes.latency_ms)}ms` : '—'} />
        </DetailSection>
      )}

      {entry.semantic_intelligence && (
        <DetailSection title="Semantic Intelligence">
          <DetailRow label="Primary Intent" value={entry.semantic_intelligence.primary_intent || '—'} />
          <DetailRow label="Intent Confidence" value={entry.semantic_intelligence.intent_confidence != null ? `${(entry.semantic_intelligence.intent_confidence * 100).toFixed(1)}%` : '—'} />
          <DetailRow label="Router Decision" value={entry.semantic_intelligence.router_decision || '—'} />
          {entry.semantic_intelligence.all_scores && (
            <div style={{ marginTop: 6 }}>
              {Object.entries(entry.semantic_intelligence.all_scores).map(([k, v]: [string, { vector_score: number }]) => (
                <div key={k} style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0', fontSize: 10 }}>
                  <span style={{ color: '#8a9a94' }}>{k}</span>
                  <span style={{ color: '#c8d4cf', fontFamily: 'monospace' }}>
                    {(v.vector_score * 100).toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </DetailSection>
      )}

      {entry.routing_metadata && (
        <DetailSection title="Routing Metadata">
          {entry.routing_metadata.perimeter_fast_path != null && (
            <DetailRow label="Perimeter Fast Path" value={entry.routing_metadata.perimeter_fast_path ? 'YES' : 'NO'} />
          )}
          {entry.routing_metadata.perimeter_processing_time_ms != null && (
            <DetailRow label="Perimeter Latency" value={`${Math.round(entry.routing_metadata.perimeter_processing_time_ms)}ms`} />
          )}
          {entry.routing_metadata.zedd_latency_ms != null && (
            <DetailRow label="ZEDD Latency" value={`${Math.round(entry.routing_metadata.zedd_latency_ms)}ms`} />
          )}
          {entry.routing_metadata.request_queue?.processing_ms != null && (
            <DetailRow label="Total Processing" value={`${Math.round(entry.routing_metadata.request_queue.processing_ms)}ms`} />
          )}
          {entry.routing_metadata.bypassed_checks && (
            <DetailRow label="Bypassed" value={entry.routing_metadata.bypassed_checks.join(', ')} />
          )}
          {entry.routing_metadata.execution_context && (
            <DetailRow label="Execution Context" value={entry.routing_metadata.execution_context} />
          )}
        </DetailSection>
      )}

      {entry.mirage_active && (
        <div style={{
          marginTop: 12,
          padding: 10,
          background: 'rgba(255,45,0,0.1)',
          borderRadius: 6,
          border: '1px solid rgba(255,45,0,0.3)',
        }}>
          <div style={{ fontSize: 11, color: '#ff6b35', fontWeight: 'bold', marginBottom: 4 }}>
            🎭 MIRAGE ACTIVE — {entry.mirage_response_type}
          </div>
        </div>
      )}

      {entry.tags && entry.tags.length > 0 && (
        <DetailSection title="Tags">
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {entry.tags.map((t, i) => (
              <span key={i} style={{ fontSize: 9, padding: '2px 6px', borderRadius: 3, background: '#1a2a24', color: '#6f8c84' }}>{t}</span>
            ))}
          </div>
        </DetailSection>
      )}

      {entry.matched_patterns && entry.matched_patterns.length > 0 && (
        <DetailSection title="Matched Patterns">
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {entry.matched_patterns.map((p, i) => (
              <span key={i} style={{ fontSize: 9, padding: '2px 6px', borderRadius: 3, background: 'rgba(255,45,0,0.1)', color: '#ff6b35', border: '1px solid rgba(255,45,0,0.2)' }}>{p}</span>
            ))}
          </div>
        </DetailSection>
      )}
    </div>
  )
}

function DetailSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 10, color: '#8a9a94', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 1, borderBottom: '1px solid #1a2a24', paddingBottom: 4 }}>
        {title}
      </div>
      {children}
    </div>
  )
}

function DetailRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', fontSize: 10 }}>
      <span style={{ color: '#8a9a94' }}>{label}</span>
      <span style={{ color: '#c8d4cf', fontFamily: 'monospace', textAlign: 'right' }}>{value}</span>
    </div>
  )
}
