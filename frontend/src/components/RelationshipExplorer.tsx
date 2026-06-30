import { useCallback, useEffect, useRef, useState } from 'react';
import cytoscape from 'cytoscape';
import type { Core, ElementDefinition } from 'cytoscape';
import { fetchApi } from '../lib/networkFetch';
import EntityTimeline from './EntityTimeline';

type GraphNode = {
  id: string;
  schema: string;
  caption: string;
  lat?: number | null;
  lon?: number | null;
  first_seen?: string | null;
  last_seen?: string | null;
};
type GraphEdge = {
  source_id: string;
  target_id: string;
  kind: string;
  confidence?: number | null;
  dataset?: string;
  seen_at?: string | null;
};
type GraphData = {
  root?: string | null;
  found: boolean;
  nodes: GraphNode[];
  edges: GraphEdge[];
};

const SCHEMA_COLOR: Record<string, string> = {
  Person: '#4ea1ff',
  Organization: '#ffb347',
  Company: '#ffb347',
  Address: '#7bdc8f',
  Vessel: '#56d4d4',
  Airplane: '#56d4d4',
  Event: '#ff6b6b',
  Document: '#b07cff',
  IpAddress: '#ff5e7e',
  Domain: '#5edfff',
  Url: '#a8e063',
  Asset: '#ffd23f',
};

const ALL_EDGE_TYPES = [
  'worksFor',
  'locatedAt',
  'ownsAsset',
  'mentionedIn',
  'linkedTo',
  'partOf',
  'sameAs',
  'mentions',
] as const;

const schemaColor = (s: string) => SCHEMA_COLOR[s] || '#9aa3b2';

const edgeConfidenceClass = (kind: string, confidence?: number | null) => {
  if (kind === 'mentions') return 'mentions';
  if (kind === 'sameAs') return 'same-as';
  if (confidence == null || Number.isNaN(confidence)) return '';
  if (confidence >= 0.9) return 'conf-high';
  if (confidence >= 0.75) return 'conf-mid';
  return 'conf-low';
};

const fmtConfidence = (v?: number | null) =>
  v == null || Number.isNaN(v) ? '—' : `${Math.round(v * 100)}%`;

interface Props {
  initialEntityId?: string | null;
}

export default function RelationshipExplorer({ initialEntityId }: Props) {
  const [rootId, setRootId] = useState(initialEntityId || '');
  const [selectedEntity, setSelectedEntity] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [graphEmpty, setGraphEmpty] = useState(true);
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [edgeFilter, setEdgeFilter] = useState<Set<string>>(new Set(ALL_EDGE_TYPES));
  const [showTimeline, setShowTimeline] = useState(false);

  const cyRef = useRef<Core | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);

  // Init cytoscape once
  useEffect(() => {
    if (cyRef.current || !containerRef.current) return;
    const container = containerRef.current;
    cyRef.current = cytoscape({
      container,
      elements: [],
      style: [
        {
          selector: 'node',
          style: {
            'background-color': 'data(color)',
            label: 'data(label)',
            color: '#e8edf4',
            'font-size': 9,
            'text-wrap': 'wrap',
            'text-max-width': '90px',
            'text-valign': 'bottom',
            'text-margin-y': 3,
            width: 22,
            height: 22,
            'border-width': 1,
            'border-color': '#0a0e14',
          },
        },
        {
          selector: 'node.root',
          style: { width: 32, height: 32, 'border-width': 2, 'border-color': '#fff' },
        },
        {
          selector: 'node.expanded',
          style: { 'border-color': '#5bdc8f', 'border-width': 2 },
        },
        {
          selector: 'edge',
          style: {
            width: 1.4,
            'line-color': '#46506a',
            'target-arrow-color': '#46506a',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            label: 'data(label)',
            'font-size': 7,
            color: '#9aa3b2',
            'text-rotation': 'autorotate',
            'text-background-color': '#0a0e14',
            'text-background-opacity': 0.7,
            'text-background-padding': '1px',
          },
        },
        {
          selector: 'edge.mentions',
          style: {
            'line-style': 'dashed',
            'line-color': '#2e3650',
            'target-arrow-color': '#2e3650',
          },
        },
        {
          selector: 'edge.same-as',
          style: { 'line-color': '#6b8cff', 'target-arrow-color': '#6b8cff', width: 2 },
        },
        {
          selector: 'edge.conf-high',
          style: { 'line-color': '#5bdc8f', 'target-arrow-color': '#5bdc8f' },
        },
        {
          selector: 'edge.conf-mid',
          style: { 'line-color': '#e6c84a', 'target-arrow-color': '#e6c84a' },
        },
        {
          selector: 'edge.conf-low',
          style: { 'line-color': '#ff7b6b', 'target-arrow-color': '#ff7b6b' },
        },
      ],
      layout: { name: 'grid' },
      wheelSensitivity: 1,
      minZoom: 0.08,
      maxZoom: 8,
    });

    const cy = cyRef.current;
    const ro = new ResizeObserver(() => cy.resize());
    ro.observe(container);

    cy.on('tap', 'node', (evt) => {
      const id = evt.target.id();
      setSelectedEntity(id);
      setShowTimeline(true);
    });

    return () => {
      ro.disconnect();
      cy.destroy();
      cyRef.current = null;
    };
  }, []);

  const renderGraph = useCallback(
    (g: GraphData, rootIdHint?: string, expanded?: Set<string>) => {
      const cy = cyRef.current;
      if (!cy) return;
      if (!g.found || !g.nodes.length) {
        cy.elements().remove();
        setGraphEmpty(true);
        setInfo('No entities found');
        return;
      }
      setGraphEmpty(false);
      const els: ElementDefinition[] = [];
      for (const n of g.nodes) {
        els.push({
          data: {
            id: n.id,
            label: n.caption || n.id.slice(0, 8),
            schema: n.schema,
            color: schemaColor(n.schema),
            lat: n.lat ?? undefined,
            lon: n.lon ?? undefined,
          },
          classes: [
            rootIdHint && n.id === rootIdHint ? 'root' : '',
            expanded?.has(n.id) ? 'expanded' : '',
          ].filter(Boolean).join(' ') || undefined,
        });
      }
      for (const e of g.edges) {
        if (!edgeFilter.has(e.kind)) continue;
        const conf = typeof e.confidence === 'number' ? e.confidence : undefined;
        els.push({
          data: {
            id: `${e.source_id}__${e.target_id}__${e.kind}`,
            source: e.source_id,
            target: e.target_id,
            label: e.kind === 'sameAs' ? `sameAs ${fmtConfidence(conf)}` : e.kind,
            confidence: conf,
            dataset: e.dataset,
            seen_at: e.seen_at,
          },
          classes: edgeConfidenceClass(e.kind, conf),
        });
      }
      cy.elements().remove();
      cy.add(els);
      cy.layout({
        name: 'cose',
        animate: false,
        nodeRepulsion: () => 9000,
        idealEdgeLength: () => 90,
        padding: 20,
      } as unknown as cytoscape.LayoutOptions).run();
      cy.fit(undefined, 30);
      setInfo(`${g.nodes.length} nodes · ${g.edges.length} edges`);
    },
    [edgeFilter],
  );

  const loadGraph = useCallback(
    async (id: string) => {
      if (!id) return;
      setError(null);
      try {
        const r = await fetchApi(
          `/api/entity/${encodeURIComponent(id)}/graph?depth=2&limit=300`,
        );
        const g: GraphData = await r.json();
        if (!g.found) {
          setError('Entity not found in graph store.');
          setGraphEmpty(true);
          return;
        }
        renderGraph(g, id, expandedNodes);
      } catch (e: unknown) {
        setError(`graph: ${(e as Error).message || e}`);
      }
    },
    [renderGraph, expandedNodes],
  );

  // Expand a node: fetch its subgraph and merge
  const expandNode = useCallback(
    async (id: string) => {
      if (expandedNodes.has(id)) {
        // Collapse: remove from expanded set and reload root
        const next = new Set(expandedNodes);
        next.delete(id);
        setExpandedNodes(next);
        loadGraph(rootId);
        return;
      }
      try {
        const r = await fetchApi(
          `/api/entity/${encodeURIComponent(id)}/graph?depth=1&limit=100`,
        );
        const g: GraphData = await r.json();
        if (!g.found) return;
        const cy = cyRef.current;
        if (!cy) return;
        // Add new nodes and edges that don't exist
        for (const n of g.nodes) {
          if (cy.getElementById(n.id).empty()) {
            cy.add({
              data: {
                id: n.id,
                label: n.caption || n.id.slice(0, 8),
                schema: n.schema,
                color: schemaColor(n.schema),
                lat: n.lat ?? undefined,
                lon: n.lon ?? undefined,
              },
            });
          }
        }
        for (const e of g.edges) {
          if (!edgeFilter.has(e.kind)) continue;
          const edgeId = `${e.source_id}__${e.target_id}__${e.kind}`;
          if (cy.getElementById(edgeId).empty()) {
            const conf = typeof e.confidence === 'number' ? e.confidence : undefined;
            cy.add({
              data: {
                id: edgeId,
                source: e.source_id,
                target: e.target_id,
                label: e.kind,
                confidence: conf,
                dataset: e.dataset,
                seen_at: e.seen_at,
              },
              classes: edgeConfidenceClass(e.kind, conf),
            });
          }
        }
        cy.getElementById(id).addClass('expanded');
        cy.layout({
          name: 'cose',
          animate: true,
          nodeRepulsion: () => 9000,
          idealEdgeLength: () => 90,
          padding: 20,
        } as unknown as cytoscape.LayoutOptions).run();
        cy.fit(undefined, 30);
        const next = new Set(expandedNodes);
        next.add(id);
        setExpandedNodes(next);
        setInfo(`${cy.nodes().length} nodes · ${cy.edges().length} edges`);
      } catch (e: unknown) {
        setError(`expand: ${(e as Error).message || e}`);
      }
    },
    [expandedNodes, rootId, loadGraph, edgeFilter],
  );

  // Auto-load initial entity
  useEffect(() => {
    if (initialEntityId) {
      setRootId(initialEntityId);
      loadGraph(initialEntityId);
    }
  }, [initialEntityId, loadGraph]);

  // Re-render when edge filter changes
  useEffect(() => {
    if (rootId) loadGraph(rootId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [edgeFilter]);

  const toggleEdgeFilter = (kind: string) => {
    setEdgeFilter((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
  };

  return (
    <div className="intel-panel">
      <div className="intel-section">
        <h3>
          🕸 Relationship Explorer <span className="stat-meta">{info || '—'}</span>
        </h3>
        <div className="intel-toolbar">
          <input
            className="intel-dataset wide"
            placeholder="Entity id…"
            value={rootId}
            onChange={(e) => setRootId(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && loadGraph(rootId)}
          />
          <button className="data-refresh" onClick={() => loadGraph(rootId)} disabled={!rootId}>
            LOAD
          </button>
          {selectedEntity && (
            <button
              className="data-refresh"
              onClick={() => expandNode(selectedEntity)}
              title={expandedNodes.has(selectedEntity) ? 'Collapse node' : 'Expand node neighbors'}
            >
              {expandedNodes.has(selectedEntity) ? 'COLLAPSE' : 'EXPAND'}
            </button>
          )}
          {selectedEntity && (
            <button
              className="data-refresh"
              onClick={() => setShowTimeline(!showTimeline)}
            >
              {showTimeline ? 'HIDE TIMELINE' : 'SHOW TIMELINE'}
            </button>
          )}
        </div>
      </div>

      <div className="intel-section">
        <div className="intel-schema-filter" title="Filter edges by kind">
          {ALL_EDGE_TYPES.map((k) => (
            <button
              key={k}
              type="button"
              className={`intel-schema-pill${edgeFilter.has(k) ? ' active' : ''}`}
              onClick={() => toggleEdgeFilter(k)}
            >
              {k}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="data-error">{error}</div>}

      <div className="intel-section intel-section-graph">
        <div className="intel-graph-wrap">
          {graphEmpty && (
            <div className="intel-graph-empty">
              Enter an entity id and click LOAD, or click a node to select it
            </div>
          )}
          <div ref={containerRef} className="intel-graph" />
        </div>
        <div className="intel-legend">
          {Object.entries(SCHEMA_COLOR)
            .filter(([k]) => k !== 'Company')
            .map(([k, c]) => (
              <span key={k}>
                <i style={{ background: c }} />
                {k}
              </span>
            ))}
          <span className="intel-legend-hint">
            click node to select · EXPAND/COLLAPSE neighbors · filter edges by kind
          </span>
        </div>
      </div>

      {showTimeline && selectedEntity && (
        <EntityTimeline entityId={selectedEntity} />
      )}
    </div>
  );
}
