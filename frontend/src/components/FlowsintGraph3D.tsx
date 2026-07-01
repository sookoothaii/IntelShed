import { useEffect, useRef, useState, useCallback } from 'react';
import { fetchApi } from '../lib/networkFetch';
import type { OsintPin } from '../lib/osintPins';
import type { FocusTarget } from '../lib/focus';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface GraphNode {
  id: string;
  label: string;
  type: string;
  lat: number | null;
  lon: number | null;
  props: Record<string, unknown>;
  dataset: string;
}

interface GraphLink {
  source: string;
  target: string;
  type: string;
  confidence: number;
}

interface GraphPin {
  id: string;
  lat: number;
  lon: number;
  label: string;
  type: string;
  meta: Record<string, unknown>;
}

interface EnrichedGraphData {
  nodes: GraphNode[];
  links: GraphLink[];
  pins: GraphPin[];
  node_count: number;
  link_count: number;
  pin_count: number;
}

interface EnricherInfo {
  name: string;
  category: string;
  input_type: string;
  output_type: string;
  description: string;
  requires_params: boolean;
}

// ---------------------------------------------------------------------------
// Node type → color mapping
// ---------------------------------------------------------------------------

const NODE_COLORS: Record<string, string> = {
  IpAddress: '#ff6b35',
  Ip: '#ff6b35',
  Domain: '#4fc3f7',
  Organization: '#00e5a0',
  Person: '#ffd23f',
  HyperText: '#e040fb',
  Username: '#ba68c8',
  Website: '#e040fb',
  Email: '#ffd23f',
  Phone: '#ff8a65',
  CryptoWallet: '#fbc02d',
  Whois: '#81d4fa',
  Port: '#ffab40',
  ASN: '#aed581',
  RiskProfile: '#ef5350',
  SocialAccount: '#ce93d8',
  Thing: '#6f8c84',
};

const LINK_COLORS: Record<string, string> = {
  linkedTo: '#4fc3f7',
  ownsAsset: '#00e5a0',
  mentionedIn: '#ffd23f',
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function FlowsintGraph3D({
  onFocus,
  onImportPins,
}: {
  onFocus: (f: Omit<FocusTarget, 'ts'>) => void;
  onAddPin: (pin: Omit<OsintPin, 'ts'>) => void;
  onImportPins: (pins: OsintPin[]) => void;
}) {
  const [graphData, setGraphData] = useState<EnrichedGraphData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<'graph3d' | 'globe'>('graph3d');
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  // Live enrichment state
  const [enrichInput, setEnrichInput] = useState('');
  const [enrichType, setEnrichType] = useState('ip');
  const [enriching, setEnriching] = useState(false);
  const [enrichResult, setEnrichResult] = useState<string | null>(null);

  // Enricher catalog state
  const [enrichers, setEnrichers] = useState<Record<string, EnricherInfo[]>>({});
  const [selectedEnricher, setSelectedEnricher] = useState<string>('');

  // Enrich-further state (node-click)
  const [furtherEnricher, setFurtherEnricher] = useState<string>('');
  const [enrichingFurther, setEnrichingFurther] = useState(false);

  // Chain state
  const [chainMode, setChainMode] = useState(false);
  const [chainSteps, setChainSteps] = useState<string[]>([]);

  // Export state
  const [exporting, setExporting] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);

  // ---------------------------------------------------------------------------
  // Fetch enriched graph data
  // ---------------------------------------------------------------------------

  const fetchGraph = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetchApi('/api/flowsint/enriched-graph');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = (await r.json()) as EnrichedGraphData;
      setGraphData(d);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchGraph();
  }, [fetchGraph]);

  // Fetch enricher catalog
  useEffect(() => {
    fetchApi('/api/flowsint/enrichers')
      .then((r) => r.json())
      .then((d) => {
        if (d.categories) setEnrichers(d.categories);
      })
      .catch(() => {});
  }, []);

  // ---------------------------------------------------------------------------
  // Live enrichment
  // ---------------------------------------------------------------------------

  async function runLiveEnrich() {
    if (!enrichInput.trim()) return;
    setEnriching(true);
    setEnrichResult(null);
    try {
      if (chainMode && chainSteps.length > 0) {
        // Run chain enrichment
        const body = {
          entity_type: enrichType,
          value: enrichInput.trim(),
          chain: chainSteps,
        };
        const r = await fetchApi('/api/flowsint/auto-chain', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const d = await r.json();
        if (d.error) {
          setEnrichResult(`Error: ${d.error}`);
        } else {
          setEnrichResult(`Chain: ${d.total_entities} entities, ${d.total_edges} edges (${d.steps.length} steps)`);
          fetchGraph();
        }
      } else {
        const body: Record<string, unknown> = {
          entity_type: enrichType,
          value: enrichInput.trim(),
        };
        if (selectedEnricher) body.enricher_name = selectedEnricher;
        const r = await fetchApi('/api/flowsint/enrich-and-ingest', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        });
        const d = await r.json();
        if (d.error) {
          setEnrichResult(`Error: ${d.error}`);
        } else {
          let msg = `Enriched: ${d.entities_created} entities, ${d.pins_created} pins`;
          if (d.chain?.length) msg += ` + chain: ${d.chain.map((c: {enricher: string, entities?: number}) => `${c.enricher}(${c.entities || 0})`).join(', ')}`;
          setEnrichResult(msg);
          fetchGraph();
        }
      }
    } catch (e) {
      setEnrichResult(`Error: ${String(e)}`);
    } finally {
      setEnriching(false);
    }
  }

  async function runEnrichFurther() {
    if (!selectedNode || !furtherEnricher) return;
    setEnrichingFurther(true);
    try {
      const nodeValue =
        (selectedNode.props as Record<string, unknown[]>).address?.[0] as string ||
        (selectedNode.props as Record<string, unknown[]>).domain?.[0] as string ||
        (selectedNode.props as Record<string, unknown[]>).email?.[0] as string ||
        selectedNode.label;
      const r = await fetchApi('/api/flowsint/enrich-further', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          value: nodeValue,
          entity_type: enrichType,
          enricher_name: furtherEnricher,
        }),
      });
      const d = await r.json();
      if (d.error) {
        setEnrichResult(`Further error: ${d.error}`);
      } else {
        setEnrichResult(`Further: +${d.entities_created} entities, +${d.edges_created} edges`);
        fetchGraph();
      }
    } catch (e) {
      setEnrichResult(`Further error: ${String(e)}`);
    } finally {
      setEnrichingFurther(false);
    }
  }

  async function exportToFlowsint() {
    if (!graphData?.nodes?.length) return;
    setExporting(true);
    setEnrichResult(null);
    try {
      const entityIds = graphData.nodes.map((n) => n.id);
      const r = await fetchApi('/api/flowsint/export-investigation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: `intelshed-flowsint-${Date.now()}`,
          entity_ids: entityIds,
          enrich: true,
        }),
      });
      const d = await r.json();
      if (d.error) {
        setEnrichResult(`Export error: ${d.error}`);
      } else {
        setEnrichResult(`Exported ${d.nodes_sent} nodes to Flowsint (inv #${d.investigation_id})`);
      }
    } catch (e) {
      setEnrichResult(`Export error: ${String(e)}`);
    } finally {
      setExporting(false);
    }
  }

  async function runAutoChainPipeline() {
    if (!enrichInput.trim()) return;
    setEnriching(true);
    setEnrichResult(null);
    try {
      const r = await fetchApi('/api/flowsint/auto-chain-pipeline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          value: enrichInput.trim(),
          entity_type: enrichType,
        }),
      });
      const d = await r.json();
      if (d.error) {
        setEnrichResult(`Pipeline error: ${d.error}`);
      } else {
        setEnrichResult(`Pipeline: ${d.total_entities} entities, ${d.total_edges} edges (${d.steps.length} steps)`);
        fetchGraph();
      }
    } catch (e) {
      setEnrichResult(`Pipeline error: ${String(e)}`);
    } finally {
      setEnriching(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Send pins to globe
  // ---------------------------------------------------------------------------

  function sendPinsToGlobe() {
    if (!graphData?.pins?.length) return;
    const pins: OsintPin[] = graphData.pins
      .filter((p) => p.lat != null && p.lon != null)
      .map((p) => ({
        id: p.id,
        tool: 'flowsint',
        query: p.label,
        lat: p.lat,
        lon: p.lon,
        title: p.label,
        lines: [
          `Type: ${p.type}`,
          `Meta: ${JSON.stringify(p.meta).slice(0, 100)}`,
        ],
        ts: Date.now(),
      }));
    onImportPins(pins);
    if (pins[0]) {
      onFocus({
        kind: 'osint',
        lat: pins[0].lat,
        lon: pins[0].lon,
        height: 400000,
        title: pins[0].title,
        lines: pins[0].lines,
      });
    }
  }

  // ---------------------------------------------------------------------------
  // Build graph data for react-force-graph-3d
  // ---------------------------------------------------------------------------

  const fgData = graphData
    ? {
        nodes: graphData.nodes.map((n) => ({
          id: n.id,
          name: n.label,
          type: n.type,
          lat: n.lat,
          lon: n.lon,
          props: n.props,
          color: NODE_COLORS[n.type] || NODE_COLORS.Thing,
          val: n.type === 'IpAddress' ? 3 : n.type === 'Domain' ? 2 : 1,
        })),
        links: graphData.links.map((l) => ({
          source: l.source,
          target: l.target,
          color: LINK_COLORS[l.type] || '#333',
          type: l.type,
        })),
      }
    : { nodes: [], links: [] };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (loading && !graphData) {
    return (
      <div style={{ padding: 20, color: '#6f8c84', fontSize: 12 }}>
        Loading enriched graph…
      </div>
    );
  }

  if (error && !graphData) {
    return (
      <div style={{ padding: 20 }}>
        <div className="data-error" style={{ marginBottom: 12 }}>{error}</div>
        <button type="button" className="refresh-btn" onClick={fetchGraph}>
          RETRY
        </button>
      </div>
    );
  }

  const nodeCount = graphData?.node_count || 0;
  const linkCount = graphData?.link_count || 0;
  const pinCount = graphData?.pin_count || 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      {/* Toolbar */}
      <div style={{ flexShrink: 0, padding: '0 12px 8px', display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 4 }}>
          <button
            type="button"
            className={view === 'graph3d' ? 'active' : ''}
            style={{
              padding: '4px 12px', fontSize: 10, fontFamily: 'monospace', cursor: 'pointer',
              background: view === 'graph3d' ? 'rgba(79,195,247,0.2)' : 'rgba(79,195,247,0.05)',
              border: view === 'graph3d' ? '1px solid #4fc3f7' : '1px solid rgba(79,195,247,0.2)',
              color: view === 'graph3d' ? '#4fc3f7' : '#6f8c84',
            }}
            onClick={() => setView('graph3d')}
          >
            3D GRAPH
          </button>
          <button
            type="button"
            className={view === 'globe' ? 'active' : ''}
            style={{
              padding: '4px 12px', fontSize: 10, fontFamily: 'monospace', cursor: 'pointer',
              background: view === 'globe' ? 'rgba(0,229,160,0.2)' : 'rgba(0,229,160,0.05)',
              border: view === 'globe' ? '1px solid #00e5a0' : '1px solid rgba(0,229,160,0.2)',
              color: view === 'globe' ? '#00e5a0' : '#6f8c84',
            }}
            onClick={() => setView('globe')}
          >
            GLOBE PINS ({pinCount})
          </button>
        </div>

        <button type="button" className="refresh-btn" onClick={fetchGraph} disabled={loading} style={{ fontSize: 10, padding: '4px 10px' }}>
          {loading ? '⟳' : '↻'} REFRESH
        </button>

        {nodeCount > 0 && (
          <button
            type="button"
            onClick={exportToFlowsint}
            disabled={exporting}
            style={{
              fontSize: 10, padding: '4px 10px', fontFamily: 'monospace', cursor: 'pointer',
              background: 'rgba(0,229,160,0.1)', border: '1px solid rgba(0,229,160,0.3)',
              color: '#00e5a0', borderRadius: 3,
            }}
          >
            {exporting ? '…' : '⇄ EXPORT TO FLOWSINT'}
          </button>
        )}

        <div style={{ fontSize: 10, color: '#6f8c84', fontFamily: 'monospace' }}>
          {nodeCount} nodes · {linkCount} links · {pinCount} pins
        </div>
      </div>

      {/* Live enrichment bar */}
      <div style={{ flexShrink: 0, padding: '0 12px 8px', display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <select
            value={enrichType}
            onChange={(e) => { setEnrichType(e.target.value); setSelectedEnricher(''); }}
            style={{
              fontSize: 10, fontFamily: 'monospace', background: 'rgba(0,0,0,0.35)',
              border: '1px solid #1a2e33', color: '#b0c4b1', borderRadius: 3, padding: '4px 6px',
            }}
          >
            <option value="ip">IP</option>
            <option value="domain">DOMAIN</option>
            <option value="email">EMAIL</option>
            <option value="username">USERNAME</option>
            <option value="website">WEBSITE</option>
            <option value="organization">ORG</option>
            <option value="phone">PHONE</option>
            <option value="cryptowallet">CRYPTO</option>
          </select>
          <select
            value={selectedEnricher}
            onChange={(e) => setSelectedEnricher(e.target.value)}
            style={{
              fontSize: 10, fontFamily: 'monospace', background: 'rgba(0,0,0,0.35)',
              border: '1px solid #1a2e33', color: '#b0c4b1', borderRadius: 3, padding: '4px 6px',
              maxWidth: 200,
            }}
          >
            <option value="">Auto (default)</option>
            {Object.entries(enrichers).map(([cat, list]) => (
              <optgroup key={cat} label={cat}>
                {list.filter((e) => {
                  const inp = (e.input_type || '').toLowerCase();
                  return inp === enrichType || (enrichType === 'ip' && inp === 'ip') || inp === 'any';
                }).map((e) => (
                  <option key={e.name} value={e.name}>{e.name}</option>
                ))}
              </optgroup>
            ))}
          </select>
          <input
            value={enrichInput}
            onChange={(e) => setEnrichInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && runLiveEnrich()}
            placeholder="Enrich value…"
            style={{
              flex: 1, fontSize: 11, fontFamily: 'monospace', background: 'rgba(0,0,0,0.35)',
              border: '1px solid #1a2e33', color: '#b0c4b1', borderRadius: 3, padding: '4px 8px',
            }}
          />
          <button
            type="button"
            onClick={runLiveEnrich}
            disabled={enriching || !enrichInput.trim()}
            style={{ fontSize: 10, padding: '4px 12px' }}
          >
            {enriching ? '…' : chainMode ? 'CHAIN →' : 'ENRICH →'}
          </button>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <button
            type="button"
            onClick={() => setChainMode(!chainMode)}
            style={{
              fontSize: 9, padding: '2px 8px', fontFamily: 'monospace',
              background: chainMode ? 'rgba(255,210,63,0.15)' : 'rgba(0,0,0,0.3)',
              border: chainMode ? '1px solid #ffd23f' : '1px solid #1a2e33',
              color: chainMode ? '#ffd23f' : '#6f8c84', borderRadius: 3, cursor: 'pointer',
            }}
          >
            ⛓ CHAIN
          </button>
          <button
            type="button"
            onClick={runAutoChainPipeline}
            disabled={enriching || !enrichInput.trim()}
            style={{
              fontSize: 9, padding: '2px 8px', fontFamily: 'monospace',
              background: 'rgba(255,107,53,0.1)', border: '1px solid rgba(255,107,53,0.3)',
              color: '#ff6b35', borderRadius: 3, cursor: 'pointer',
            }}
          >
            ⚡ PIPELINE
          </button>
          {chainMode && (
            <select
              multiple
              value={chainSteps}
              onChange={(e) => setChainSteps(Array.from(e.target.selectedOptions).map((o) => o.value))}
              style={{
                fontSize: 9, fontFamily: 'monospace', background: 'rgba(0,0,0,0.35)',
                border: '1px solid #1a2e33', color: '#b0c4b1', borderRadius: 3,
                minHeight: 40, maxWidth: 300,
              }}
            >
              {Object.values(enrichers).flat().map((e) => (
                <option key={e.name} value={e.name}>{e.name}</option>
              ))}
            </select>
          )}
          {enrichResult && (
            <span style={{ fontSize: 10, color: enrichResult.startsWith('Error') || enrichResult.startsWith('Further error') ? '#ff6b35' : '#00e5a0', fontFamily: 'monospace' }}>
              {enrichResult}
            </span>
          )}
        </div>
      </div>

      {/* Main visualization area */}
      <div ref={containerRef} style={{ flex: 1, minHeight: 0, position: 'relative', overflow: 'hidden' }}>
        {view === 'graph3d' && (
          <>
            {nodeCount === 0 ? (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#6f8c84', fontSize: 13, textAlign: 'center' }}>
                <div>
                  <p style={{ marginBottom: 8 }}>No enriched entities yet.</p>
                  <p style={{ fontSize: 11 }}>Run auto-enrichment or use the enrichment bar above to populate the graph.</p>
                </div>
              </div>
            ) : (
              <ForceGraph3DWrapper data={fgData} onNodeClick={(n: GraphNode) => setSelectedNode(n)} />
            )}
          </>
        )}

        {view === 'globe' && (
          <div style={{ height: '100%', overflowY: 'auto', padding: '0 12px' }}>
            {pinCount === 0 ? (
              <div style={{ padding: 20, color: '#6f8c84', fontSize: 12 }}>
                No geo-located pins from enrichment. Enrich IPs to get geo coordinates.
              </div>
            ) : (
              <>
                <button
                  type="button"
                  className="refresh-btn"
                  onClick={sendPinsToGlobe}
                  style={{ marginBottom: 10, fontSize: 10, padding: '4px 12px' }}
                >
                  ◎ SEND ALL TO GLOBE
                </button>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {graphData!.pins.map((pin) => (
                    <div
                      key={pin.id}
                      onClick={() => {
                        if (pin.lat != null && pin.lon != null) {
                          onFocus({
                            kind: 'osint',
                            lat: pin.lat,
                            lon: pin.lon,
                            height: 400000,
                            title: pin.label,
                            lines: [`Type: ${pin.type}`, `Meta: ${JSON.stringify(pin.meta).slice(0, 80)}`],
                          });
                        }
                      }}
                      style={{
                        cursor: 'pointer',
                        padding: '8px 12px',
                        background: 'rgba(79,195,247,0.05)',
                        border: '1px solid rgba(79,195,247,0.15)',
                        borderRadius: 4,
                        transition: 'background 0.15s',
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(79,195,247,0.12)')}
                      onMouseLeave={(e) => (e.currentTarget.style.background = 'rgba(79,195,247,0.05)')}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: 12, color: '#4fc3f7', fontFamily: 'monospace' }}>
                          {pin.label}
                        </span>
                        <span style={{ fontSize: 9, color: '#6f8c84', textTransform: 'uppercase' }}>
                          {pin.type}
                        </span>
                      </div>
                      {pin.lat != null && pin.lon != null && (
                        <span style={{ fontSize: 9, color: '#6f8c84' }}>
                          {pin.lat.toFixed(4)}°, {pin.lon.toFixed(4)}°
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </div>

      {/* Node detail panel */}
      {selectedNode && view === 'graph3d' && (
        <div
          style={{
            position: 'absolute',
            bottom: 8,
            left: 12,
            right: 12,
            background: 'rgba(2,6,10,0.95)',
            border: '1px solid #1a2e33',
            borderRadius: 6,
            padding: '10px 14px',
            maxHeight: 180,
            overflowY: 'auto',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
            <span style={{ fontSize: 12, color: NODE_COLORS[selectedNode.type] || '#b0c4b1', fontFamily: 'monospace' }}>
              {selectedNode.label}
            </span>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: 9, color: '#6f8c84', textTransform: 'uppercase' }}>
                {selectedNode.type}
              </span>
              {selectedNode.lat != null && selectedNode.lon != null && (
                <button
                  type="button"
                  className="locate-mini"
                  onClick={() => {
                    onFocus({
                      kind: 'osint',
                      lat: selectedNode.lat!,
                      lon: selectedNode.lon!,
                      height: 400000,
                      title: selectedNode.label,
                      lines: [`Type: ${selectedNode.type}`],
                    });
                  }}
                  style={{ fontSize: 9, padding: '2px 8px' }}
                >
                  ◎ GLOBE
                </button>
              )}
              <button
                type="button"
                onClick={() => setSelectedNode(null)}
                style={{ fontSize: 10, color: '#6f8c84', background: 'none', border: 'none', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>
          </div>
          <pre style={{ fontSize: 10, color: '#8fb7a9', margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            {JSON.stringify(selectedNode.props, null, 2).slice(0, 500)}
          </pre>
          {/* Enrich Further */}
          <div style={{ display: 'flex', gap: 4, alignItems: 'center', marginTop: 6, paddingTop: 6, borderTop: '1px solid #1a2e33' }}>
            <span style={{ fontSize: 9, color: '#6f8c84', fontFamily: 'monospace' }}>ENRICH FURTHER:</span>
            <select
              value={furtherEnricher}
              onChange={(e) => setFurtherEnricher(e.target.value)}
              style={{
                fontSize: 9, fontFamily: 'monospace', background: 'rgba(0,0,0,0.35)',
                border: '1px solid #1a2e33', color: '#b0c4b1', borderRadius: 3, padding: '2px 4px',
                flex: 1,
              }}
            >
              <option value="">Select enricher…</option>
              {Object.entries(enrichers).map(([cat, list]) => (
                <optgroup key={cat} label={cat}>
                  {list.map((e) => (
                    <option key={e.name} value={e.name}>{e.name}</option>
                  ))}
                </optgroup>
              ))}
            </select>
            <button
              type="button"
              onClick={runEnrichFurther}
              disabled={!furtherEnricher || enrichingFurther}
              style={{ fontSize: 9, padding: '2px 8px' }}
            >
              {enrichingFurther ? '…' : '→'}
            </button>
          </div>
        </div>
      )}

      {/* Legend */}
      {view === 'graph3d' && nodeCount > 0 && (
        <div
          style={{
            position: 'absolute',
            top: 8,
            right: 8,
            background: 'rgba(2,6,10,0.85)',
            border: '1px solid #1a2e33',
            borderRadius: 4,
            padding: '6px 10px',
            fontSize: 9,
            fontFamily: 'monospace',
            color: '#6f8c84',
            pointerEvents: 'none',
          }}
        >
          {Object.entries(NODE_COLORS).filter(([k]) => {
            if (!graphData) return false;
            return graphData.nodes.some((n) => n.type === k);
          }).map(([type, color]) => (
            <div key={type} style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 2 }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, display: 'inline-block' }} />
              {type}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Lazy-loaded ForceGraph3D wrapper (heavy Three.js component)
// ---------------------------------------------------------------------------

import { lazy, Suspense } from 'react';

const ForceGraph3D = lazy(() => import('react-force-graph-3d'));

function ForceGraph3DWrapper({
  data,
  onNodeClick,
}: {
  data: { nodes: Record<string, unknown>[]; links: Record<string, unknown>[] };
  onNodeClick: (n: GraphNode) => void;
}) {
  return (
    <Suspense fallback={<div style={{ padding: 20, color: '#6f8c84', fontSize: 12 }}>Loading 3D engine…</div>}>
      <ForceGraph3D
        graphData={data as never}
        nodeLabel="name"
        nodeColor="color"
        nodeVal="val"
        linkColor="color"
        linkWidth={1}
        linkDirectionalArrowLength={3}
        linkDirectionalArrowRelPos={1}
        linkDirectionalParticles={1}
        linkDirectionalParticleWidth={0.5}
        linkDirectionalParticleSpeed={0.003}
        backgroundColor="rgba(2,6,10,1)"
        width={800}
        onNodeClick={(node: unknown) => {
          const n = node as GraphNode;
          onNodeClick(n);
        }}
        nodeOpacity={0.9}
        linkOpacity={0.4}
        cooldownTicks={100}
        warmupTicks={50}
      />
    </Suspense>
  );
}
