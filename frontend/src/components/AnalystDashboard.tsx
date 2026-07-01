/**
 * V4-31 AnalystDashboard — analytical dashboard with Sankey flow diagram,
 * event timeline, and geospatial heatmap. SVG-based, no deck.gl dependency.
 *
 * Fetches from existing API endpoints:
 * - /api/health (feed counts for Sankey)
 * - /api/insights?top=20 (timeline events)
 * - /api/fusion/heatmap (geospatial heatmap cells)
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { fetchApi } from '../lib/networkFetch';
import { useSmartPoll } from '../hooks/useSmartPoll';
import type { HeatmapCell } from '../lib/types';

// ── Types ───────────────────────────────────────────────────────────────────

type FeedHealth = {
  feeds?: Record<
    string,
    { status: string; fresh: boolean; count: number; age_sec: number; error?: boolean }
  >;
};

type InsightItem = {
  id?: string;
  title?: string;
  text?: string;
  severity?: string;
  source?: string;
  lat?: number | null;
  lon?: number | null;
  created_at?: string;
  timestamp?: string;
};

type TimelineEvent = {
  id: string;
  label: string;
  time: number;
  severity: 'low' | 'medium' | 'high' | 'info';
  source: string;
};

type SankeyLink = {
  source: string;
  target: string;
  value: number;
};

// ── Sankey Diagram ──────────────────────────────────────────────────────────

function SankeyDiagram({ links, nodes }: { links: SankeyLink[]; nodes: string[] }) {
  const W = 520;
  const H = 280;
  const padL = 100;
  const padR = 100;
  const padY = 20;

  const nodeSet = useMemo(() => {
    const s = new Set(nodes);
    links.forEach((l) => {
      s.add(l.source);
      s.add(l.target);
    });
    return Array.from(s);
  }, [links, nodes]);

  // Split into left (sources) and right (targets)
  const sourceNodes = useMemo(() => {
    const targets = new Set(links.map((l) => l.target));
    return nodeSet.filter((n) => !targets.has(n));
  }, [nodeSet, links]);

  const targetNodes = useMemo(() => {
    const sources = new Set(links.map((l) => l.source));
    return nodeSet.filter((n) => !sources.has(n));
  }, [nodeSet, links]);

  const totalValue = links.reduce((s, l) => s + l.value, 0) || 1;

  const layoutNode = (nodeList: string[], x: number) => {
    const gap = (H - padY * 2) / Math.max(nodeList.length, 1);
    return nodeList.map((name, i) => {
      const nodeLinks = links.filter((l) => (x === padL ? l.source === name : l.target === name));
      const nodeValue = nodeLinks.reduce((s, l) => s + l.value, 0) || totalValue / nodeSet.length;
      const barH = Math.max(4, (nodeValue / totalValue) * (H - padY * 2));
      return {
        name,
        x,
        y: padY + i * gap + (gap - barH) / 2,
        h: barH,
        value: nodeValue,
      };
    });
  };

  const leftLayout = layoutNode(sourceNodes, padL);
  const rightLayout = layoutNode(targetNodes, W - padR);

  const nodeIndex = new Map<string, { x: number; y: number; h: number }>();
  leftLayout.forEach((n) => nodeIndex.set(n.name, n));
  rightLayout.forEach((n) => nodeIndex.set(n.name, n));

  // Build curved paths for each link
  const paths = links.map((link, i) => {
    const src = nodeIndex.get(link.source);
    const tgt = nodeIndex.get(link.target);
    if (!src || !tgt) return null;
    const sx = src.x + 2;
    const sy = src.y + src.h / 2;
    const tx = tgt.x - 2;
    const ty = tgt.y + tgt.h / 2;
    const cx = (sx + tx) / 2;
    const opacity = 0.15 + 0.5 * (link.value / totalValue);
    const width = Math.max(1, (link.value / totalValue) * 40);
    return (
      <path
        key={`link-${i}`}
        d={`M ${sx} ${sy} C ${cx} ${sy}, ${cx} ${ty}, ${tx} ${ty}`}
        fill="none"
        stroke="var(--accent, #0ff)"
        strokeWidth={width}
        opacity={opacity}
      />
    );
  });

  const renderNode = (n: { name: string; x: number; y: number; h: number; value: number }) => (
    <g key={`node-${n.name}`}>
      <rect x={n.x - 2} y={n.y} width={4} height={n.h} fill="var(--accent, #0ff)" rx={1} />
      <text
        x={n.x === padL ? n.x - 8 : n.x + 8}
        y={n.y + n.h / 2}
        textAnchor={n.x === padL ? 'end' : 'start'}
        dominantBaseline="middle"
        fontSize={10}
        fill="var(--text, #ccc)"
        fontFamily="monospace"
      >
        {n.name.length > 14 ? n.name.slice(0, 12) + '…' : n.name}
      </text>
    </g>
  );

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="sankey-svg"
      role="img"
      aria-label="Feed flow Sankey diagram"
    >
      {paths}
      {leftLayout.map(renderNode)}
      {rightLayout.map(renderNode)}
    </svg>
  );
}

// ── Timeline ────────────────────────────────────────────────────────────────

function EventTimeline({ events }: { events: TimelineEvent[] }) {
  const W = 520;
  const H = 200;
  const padX = 40;
  const padY = 20;

  const sorted = useMemo(() => [...events].sort((a, b) => a.time - b.time), [events]);
  // Group events by source for swim lanes — must be before any early return (Rules of Hooks)
  const sources = useMemo(() => {
    const s = new Set(sorted.map((e) => e.source || 'unknown'));
    return Array.from(s).slice(0, 6);
  }, [sorted]);
  if (sorted.length === 0) {
    return <div className="timeline-empty">No events in window</div>;
  }

  const minT = sorted[0].time;
  const maxT = sorted[sorted.length - 1].time;
  const span = Math.max(maxT - minT, 60_000);

  const xFor = (t: number) => padX + ((t - minT) / span) * (W - padX * 2);
  const severityColor: Record<string, string> = {
    high: '#f44',
    medium: '#fa0',
    low: '#0f8',
    info: '#08f',
  };

  const laneH = (H - padY * 2) / Math.max(sources.length, 1);
  const laneFor = (src: string) => sources.indexOf(src);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="timeline-svg" role="img" aria-label="Event timeline">
      {/* Lane labels */}
      {sources.map((src, i) => (
        <g key={`lane-${src}`}>
          <line
            x1={padX}
            y1={padY + i * laneH + laneH / 2}
            x2={W - padX}
            y2={padY + i * laneH + laneH / 2}
            stroke="var(--border, #333)"
            strokeWidth={0.5}
            strokeDasharray="2 4"
          />
          <text
            x={padX - 6}
            y={padY + i * laneH + laneH / 2}
            textAnchor="end"
            dominantBaseline="middle"
            fontSize={9}
            fill="var(--text-dim, #888)"
            fontFamily="monospace"
          >
            {src.length > 10 ? src.slice(0, 8) + '…' : src}
          </text>
        </g>
      ))}

      {/* Time axis */}
      <line
        x1={padX}
        y1={H - padY + 4}
        x2={W - padX}
        y2={H - padY + 4}
        stroke="var(--border, #333)"
        strokeWidth={0.5}
      />
      <text x={padX} y={H - 4} fontSize={8} fill="var(--text-dim, #888)" fontFamily="monospace">
        {new Date(minT).toLocaleTimeString()}
      </text>
      <text
        x={W - padX}
        y={H - 4}
        textAnchor="end"
        fontSize={8}
        fill="var(--text-dim, #888)"
        fontFamily="monospace"
      >
        {new Date(maxT).toLocaleTimeString()}
      </text>

      {/* Events */}
      {sorted.map((ev, i) => {
        const lane = laneFor(ev.source || 'unknown');
        if (lane < 0) return null;
        const cx = xFor(ev.time);
        const cy = padY + lane * laneH + laneH / 2;
        const color = severityColor[ev.severity] || severityColor.info;
        return (
          <g key={`ev-${i}`}>
            <circle cx={cx} cy={cy} r={3} fill={color} opacity={0.8} />
            <title>{`${ev.label} (${ev.source})`}</title>
          </g>
        );
      })}
    </svg>
  );
}

// ── Heatmap ─────────────────────────────────────────────────────────────────

function GeoHeatmap({ cells }: { cells: HeatmapCell[] }) {
  const W = 520;
  const H = 240;
  const padX = 30;
  const padY = 20;

  const valid = cells.filter((c) => c.lat != null && c.lon != null);
  if (valid.length === 0) {
    return <div className="heatmap-empty">No heatmap data</div>;
  }

  const lats = valid.map((c) => c.lat!);
  const lons = valid.map((c) => c.lon!);
  const minLat = Math.min(...lats);
  const maxLat = Math.max(...lats);
  const minLon = Math.min(...lons);
  const maxLon = Math.max(...lons);
  const latSpan = Math.max(maxLat - minLat, 0.1);
  const lonSpan = Math.max(maxLon - minLon, 0.1);

  const xFor = (lon: number) => padX + ((lon - minLon) / lonSpan) * (W - padX * 2);
  const yFor = (lat: number) => H - padY - ((lat - minLat) / latSpan) * (H - padY * 2);

  const maxScore = Math.max(...valid.map((c) => c.score || c.intensity || 0), 0.01);

  const colorFor = (score: number) => {
    const t = Math.min(1, score / maxScore);
    if (t > 0.75) return '#f44';
    if (t > 0.5) return '#fa0';
    if (t > 0.25) return '#ff0';
    return '#0f8';
  };

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="heatmap-svg"
      role="img"
      aria-label="Geospatial heatmap"
    >
      {valid.map((c, i) => {
        const r = 4 + (c.score / maxScore) * 12;
        return (
          <g key={`cell-${i}`}>
            <circle
              cx={xFor(c.lon!)}
              cy={yFor(c.lat!)}
              r={r}
              fill={colorFor(c.score || c.intensity || 0)}
              opacity={0.3 + 0.5 * ((c.score || c.intensity || 0) / maxScore)}
            >
              <title>{`(${c.lat?.toFixed(2)}, ${c.lon?.toFixed(2)}) score=${(c.score || c.intensity || 0).toFixed(2)}`}</title>
            </circle>
          </g>
        );
      })}
      <text x={padX} y={H - 4} fontSize={8} fill="var(--text-dim, #888)" fontFamily="monospace">
        {minLon.toFixed(1)}, {minLat.toFixed(1)}
      </text>
      <text
        x={W - padX}
        y={H - 4}
        textAnchor="end"
        fontSize={8}
        fill="var(--text-dim, #888)"
        fontFamily="monospace"
      >
        {maxLon.toFixed(1)}, {maxLat.toFixed(1)}
      </text>
    </svg>
  );
}

// ── Main Component ──────────────────────────────────────────────────────────

export default function AnalystDashboard({ onClose }: { onClose?: () => void }) {
  const [sankeyLinks, setSankeyLinks] = useState<SankeyLink[]>([]);
  const [timelineEvents, setTimelineEvents] = useState<TimelineEvent[]>([]);
  const [heatmapCells, setHeatmapCells] = useState<HeatmapCell[]>([]);
  const containerRef = useRef<HTMLDivElement>(null);

  // Smart-poll health for Sankey source data
  const healthPoll = useSmartPoll<FeedHealth>({
    fetcher: async () => {
      const r = await fetchApi('/api/health');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json() as Promise<FeedHealth>;
    },
    interval: 60_000,
    hiddenInterval: 300_000,
    breakerThreshold: 5,
  });

  // Smart-poll insights for timeline
  const insightsPoll = useSmartPoll<{ insights?: InsightItem[] }>({
    fetcher: async () => {
      const r = await fetchApi('/api/insights?top=20');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json() as Promise<{ insights?: InsightItem[] }>;
    },
    interval: 90_000,
    hiddenInterval: 300_000,
    breakerThreshold: 5,
  });

  // Smart-poll heatmap
  const heatmapPoll = useSmartPoll<{ cells?: HeatmapCell[] }>({
    fetcher: async () => {
      const r = await fetchApi('/api/fusion/heatmap');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json() as Promise<{ cells?: HeatmapCell[] }>;
    },
    interval: 120_000,
    hiddenInterval: 600_000,
    breakerThreshold: 5,
  });

  // Transform health data into Sankey links
  useEffect(() => {
    const feeds = healthPoll.data?.feeds;
    if (!feeds) return;
    const links: SankeyLink[] = [];
    const freshCount = { value: 0 };
    const staleCount = { value: 0 };
    const errorCount = { value: 0 };

    for (const [name, info] of Object.entries(feeds)) {
      const val = info.count || 0;
      if (info.error || info.status === 'error') {
        links.push({ source: name, target: 'ERROR', value: val || 1 });
        errorCount.value += val || 1;
      } else if (info.fresh || info.status === 'ok') {
        links.push({ source: name, target: 'FRESH', value: val });
        freshCount.value += val;
      } else {
        links.push({ source: name, target: 'STALE', value: val });
        staleCount.value += val;
      }
    }
    setSankeyLinks(links);
  }, [healthPoll.data]);

  // Transform insights into timeline events
  useEffect(() => {
    const insights = insightsPoll.data?.insights;
    if (!insights) return;
    const now = Date.now();
    const events: TimelineEvent[] = insights
      .map((ins) => {
        const ts = ins.created_at || ins.timestamp || '';
        const time = ts ? new Date(ts).getTime() : now;
        const sev = (ins.severity || 'info').toLowerCase() as TimelineEvent['severity'];
        return {
          id: ins.id || `${ins.title}-${time}`,
          label: ins.title || ins.text?.slice(0, 60) || 'Untitled',
          time: Number.isFinite(time) ? time : now,
          severity: ['high', 'medium', 'low', 'info'].includes(sev) ? sev : 'info',
          source: ins.source || 'unknown',
        };
      })
      .slice(0, 50);
    setTimelineEvents(events);
  }, [insightsPoll.data]);

  // Transform heatmap data
  useEffect(() => {
    const cells = heatmapPoll.data?.cells;
    if (cells) setHeatmapCells(cells);
  }, [heatmapPoll.data]);

  const statusColor: Record<string, string> = {
    idle: 'var(--text-dim, #888)',
    polling: 'var(--accent, #0ff)',
    backoff: '#fa0',
    'circuit-open': '#f44',
  };

  const renderStatus = (label: string, status: string) => (
    <span className="poll-status" style={{ color: statusColor[status] || '#888' }}>
      {label}: {status}
    </span>
  );

  return (
    <div className="analyst-dashboard" ref={containerRef}>
      <div className="analyst-dashboard-header">
        <div className="analyst-dashboard-title">ANALYST DASHBOARD</div>
        <div className="analyst-dashboard-status">
          {renderStatus('HEALTH', healthPoll.status)}
          {renderStatus('INSIGHTS', insightsPoll.status)}
          {renderStatus('HEATMAP', heatmapPoll.status)}
        </div>
        {onClose && (
          <button className="analyst-dashboard-close" onClick={onClose} type="button">
            ✕
          </button>
        )}
      </div>

      <div className="analyst-dashboard-grid">
        <div className="analyst-panel">
          <div className="analyst-panel-label">FEED FLOW — SANKEY</div>
          <SankeyDiagram links={sankeyLinks} nodes={[]} />
        </div>

        <div className="analyst-panel">
          <div className="analyst-panel-label">EVENT TIMELINE</div>
          <EventTimeline events={timelineEvents} />
        </div>

        <div className="analyst-panel">
          <div className="analyst-panel-label">FUSION HEATMAP</div>
          <GeoHeatmap cells={heatmapCells} />
        </div>

        <div className="analyst-panel analyst-panel--metrics">
          <div className="analyst-panel-label">POLL METRICS</div>
          <div className="analyst-metrics-grid">
            <div className="metric-row">
              <span className="metric-label">Health polls</span>
              <span className="metric-val">{healthPoll.pollCount}</span>
            </div>
            <div className="metric-row">
              <span className="metric-label">Health errors</span>
              <span className="metric-val">{healthPoll.consecutiveErrors}</span>
            </div>
            <div className="metric-row">
              <span className="metric-label">Insight polls</span>
              <span className="metric-val">{insightsPoll.pollCount}</span>
            </div>
            <div className="metric-row">
              <span className="metric-label">Insight errors</span>
              <span className="metric-val">{insightsPoll.consecutiveErrors}</span>
            </div>
            <div className="metric-row">
              <span className="metric-label">Heatmap polls</span>
              <span className="metric-val">{heatmapPoll.pollCount}</span>
            </div>
            <div className="metric-row">
              <span className="metric-label">Heatmap errors</span>
              <span className="metric-val">{heatmapPoll.consecutiveErrors}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
