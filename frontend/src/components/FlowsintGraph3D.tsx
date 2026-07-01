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

// ---------------------------------------------------------------------------
// Node type → color mapping
// ---------------------------------------------------------------------------

const NODE_COLORS: Record<string, string> = {
  IpAddress: '#ff6b35',
  Domain: '#4fc3f7',
  Organization: '#00e5a0',
  Person: '#ffd23f',
  HyperText: '#e040fb',
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

  // ---------------------------------------------------------------------------
  // Live enrichment
  // ---------------------------------------------------------------------------

  async function runLiveEnrich() {
    if (!enrichInput.trim()) return;
    setEnriching(true);
    setEnrichResult(null);
    try {
      const body: Record<string, unknown> = {
        enricher_name: enrichType === 'ip' ? 'ip_to_infos' : enrichType === 'domain' ? 'domain_to_whois' : 'email_to_gravatar',
        entity_type: enrichType,
        value: enrichInput.trim(),
      };
      const r = await fetchApi('/api/flowsint/enrich', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const d = await r.json();
      if (d.error) {
        setEnrichResult(`Error: ${d.error}`);
      } else {
        const nodeCount = d.graph?.nds?.length || 0;
        setEnrichResult(`Enriched: ${nodeCount} nodes, status: ${d.scan_status}`);
        // Refresh graph data
        fetchGraph();
      }
    } catch (e) {
      setEnrichResult(`Error: ${String(e)}`);
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

        <div style={{ fontSize: 10, color: '#6f8c84', fontFamily: 'monospace' }}>
          {nodeCount} nodes · {linkCount} links · {pinCount} pins
        </div>
      </div>

      {/* Live enrichment bar */}
      <div style={{ flexShrink: 0, padding: '0 12px 8px', display: 'flex', gap: 6, alignItems: 'center' }}>
        <select
          value={enrichType}
          onChange={(e) => setEnrichType(e.target.value)}
          style={{
            fontSize: 10, fontFamily: 'monospace', background: 'rgba(0,0,0,0.35)',
            border: '1px solid #1a2e33', color: '#b0c4b1', borderRadius: 3, padding: '4px 6px',
          }}
        >
          <option value="ip">IP</option>
          <option value="domain">DOMAIN</option>
          <option value="email">EMAIL</option>
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
          {enriching ? '…' : 'ENRICH →'}
        </button>
        {enrichResult && (
          <span style={{ fontSize: 10, color: enrichResult.startsWith('Error') ? '#ff6b35' : '#00e5a0', fontFamily: 'monospace' }}>
            {enrichResult}
          </span>
        )}
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
          {Object.entries(NODE_COLORS).filter(([k]) => k !== 'Thing').map(([type, color]) => (
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
