/**
 * V4-65 TemporalReplay — time-travel replay with snapshot archiver.
 *
 * Periodically captures snapshots of globe state (feed stats, layer counts,
 * camera position) and lets the analyst scrub through them on a timeline.
 * Snapshots are stored in memory (ring buffer) and optionally exported as JSON.
 *
 * Uses existing /api/health and /api/fusion/heatmap endpoints for state capture.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchApi } from '../lib/networkFetch';
import { useSmartPoll } from '../hooks/useSmartPoll';

// ── Types ───────────────────────────────────────────────────────────────────

export type ReplaySnapshot = {
  id: string;
  timestamp: number;
  label: string;
  feeds: Record<string, { status: string; fresh: boolean; count: number }>;
  totalEntities: number;
  totalEvents: number;
  heatmapCells: number;
  insightCount: number;
  metadata?: Record<string, unknown>;
};

type SnapshotArchiver = {
  snapshots: ReplaySnapshot[];
  capture: () => Promise<ReplaySnapshot | null>;
  clear: () => void;
  exportJson: () => string;
  importJson: (json: string) => number;
  maxSnapshots: number;
};

const DEFAULT_MAX_SNAPSHOTS = 120;

function useSnapshotArchiver(maxSnapshots = DEFAULT_MAX_SNAPSHOTS): SnapshotArchiver {
  const [snapshots, setSnapshots] = useState<ReplaySnapshot[]>([]);
  const idCounter = useRef(0);

  const capture = useCallback(async (): Promise<ReplaySnapshot | null> => {
    try {
      const [healthR, heatmapR, insightsR] = await Promise.all([
        fetchApi('/api/health').then((r) => r.ok ? r.json() : null).catch(() => null),
        fetchApi('/api/fusion/heatmap').then((r) => r.ok ? r.json() : null).catch(() => null),
        fetchApi('/api/insights?top=50').then((r) => r.ok ? r.json() : null).catch(() => null),
      ]);

      const feeds: ReplaySnapshot['feeds'] = {};
      let totalEntities = 0;
      let totalEvents = 0;
      if (healthR?.feeds) {
        for (const [name, info] of Object.entries(healthR.feeds as Record<string, { status: string; fresh: boolean; count: number }>)) {
          feeds[name] = {
            status: info.status || 'unknown',
            fresh: info.fresh ?? false,
            count: info.count ?? 0,
          };
          totalEvents += info.count ?? 0;
        }
      }

      const heatmapCells = heatmapR?.cells?.length ?? 0;
      const insightCount = insightsR?.insights?.length ?? 0;

      idCounter.current += 1;
      const snap: ReplaySnapshot = {
        id: `snap-${idCounter.current}`,
        timestamp: Date.now(),
        label: new Date().toLocaleTimeString(),
        feeds,
        totalEntities,
        totalEvents,
        heatmapCells,
        insightCount,
      };

      setSnapshots((prev) => {
        const next = [...prev, snap];
        return next.length > maxSnapshots ? next.slice(-maxSnapshots) : next;
      });
      return snap;
    } catch {
      return null;
    }
  }, [maxSnapshots]);

  const clear = useCallback(() => {
    setSnapshots([]);
    idCounter.current = 0;
  }, []);

  const exportJson = useCallback(() => {
    return JSON.stringify(snapshots, null, 2);
  }, [snapshots]);

  const importJson = useCallback((json: string): number => {
    try {
      const parsed = JSON.parse(json) as ReplaySnapshot[];
      if (!Array.isArray(parsed)) return 0;
      setSnapshots(parsed.slice(-maxSnapshots));
      return parsed.length;
    } catch {
      return 0;
    }
  }, [maxSnapshots]);

  return { snapshots, capture, clear, exportJson, importJson, maxSnapshots };
}

// ── Snapshot Detail ─────────────────────────────────────────────────────────

function SnapshotDetail({ snap }: { snap: ReplaySnapshot }) {
  const feedEntries = Object.entries(snap.feeds);
  return (
    <div className="snapshot-detail">
      <div className="snapshot-detail-header">
        <span className="snapshot-detail-time">{new Date(snap.timestamp).toLocaleString()}</span>
        <span className="snapshot-detail-id">{snap.id}</span>
      </div>
      <div className="snapshot-detail-stats">
        <div className="metric-row">
          <span className="metric-label">Events</span>
          <span className="metric-val">{snap.totalEvents}</span>
        </div>
        <div className="metric-row">
          <span className="metric-label">Heatmap cells</span>
          <span className="metric-val">{snap.heatmapCells}</span>
        </div>
        <div className="metric-row">
          <span className="metric-label">Insights</span>
          <span className="metric-val">{snap.insightCount}</span>
        </div>
        <div className="metric-row">
          <span className="metric-label">Feeds tracked</span>
          <span className="metric-val">{feedEntries.length}</span>
        </div>
      </div>
      {feedEntries.length > 0 && (
        <div className="snapshot-feeds">
          <div className="snapshot-feeds-label">FEED STATUS</div>
          <div className="snapshot-feeds-list">
            {feedEntries.slice(0, 12).map(([name, info]) => (
              <div key={name} className="snapshot-feed-row">
                <span className={`feed-dot feed-dot--${info.fresh ? 'fresh' : 'stale'}`} />
                <span className="feed-name">{name}</span>
                <span className="feed-count">{info.count}</span>
              </div>
            ))}
            {feedEntries.length > 12 && (
              <div className="feed-more">+{feedEntries.length - 12} more</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Timeline Scrubber ───────────────────────────────────────────────────────

function ReplayTimeline({
  snapshots,
  currentIndex,
  onSeek,
}: {
  snapshots: ReplaySnapshot[];
  currentIndex: number;
  onSeek: (index: number) => void;
}) {
  const W = 600;
  const H = 60;
  const padX = 20;
  const padY = 10;

  if (snapshots.length === 0) {
    return <div className="replay-timeline-empty">No snapshots captured yet</div>;
  }

  const minT = snapshots[0].timestamp;
  const maxT = snapshots[snapshots.length - 1].timestamp;
  const span = Math.max(maxT - minT, 1000);

  const xFor = (t: number) => padX + ((t - minT) / span) * (W - padX * 2);

  // Event count sparkline
  const maxEvents = Math.max(...snapshots.map((s) => s.totalEvents), 1);
  const points = snapshots.map((s) => {
    const x = xFor(s.timestamp);
    const y = H - padY - (s.totalEvents / maxEvents) * (H - padY * 2);
    return `${x},${y}`;
  });

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="replay-timeline-svg" role="img" aria-label="Replay timeline">
      {/* Sparkline */}
      <polyline
        points={points.join(' ')}
        fill="none"
        stroke="var(--accent, #0ff)"
        strokeWidth={1}
        opacity={0.6}
      />
      {/* Snapshot markers */}
      {snapshots.map((s, i) => {
        const x = xFor(s.timestamp);
        const isActive = i === currentIndex;
        return (
          <g key={s.id}>
            <circle
              cx={x}
              cy={H - padY - (s.totalEvents / maxEvents) * (H - padY * 2)}
              r={isActive ? 5 : 2.5}
              fill={isActive ? '#fa0' : 'var(--accent, #0ff)'}
              opacity={isActive ? 1 : 0.5}
              style={{ cursor: 'pointer' }}
              onClick={() => onSeek(i)}
            >
              <title>{`${s.label} — ${s.totalEvents} events`}</title>
            </circle>
          </g>
        );
      })}
      {/* Time labels */}
      <text x={padX} y={H - 1} fontSize={8} fill="var(--text-dim, #888)" fontFamily="monospace">
        {new Date(minT).toLocaleTimeString()}
      </text>
      <text x={W - padX} y={H - 1} textAnchor="end" fontSize={8} fill="var(--text-dim, #888)" fontFamily="monospace">
        {new Date(maxT).toLocaleTimeString()}
      </text>
    </svg>
  );
}

// ── Main Component ──────────────────────────────────────────────────────────

export default function TemporalReplay({ onClose }: { onClose?: () => void }) {
  const archiver = useSnapshotArchiver(120);
  const [currentIndex, setCurrentIndex] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const [playSpeed, setPlaySpeed] = useState(1);
  const [autoCapture, setAutoCapture] = useState(true);
  const [captureInterval, setCaptureInterval] = useState(60_000);
  const playTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Auto-capture snapshots
  const capturePoll = useSmartPoll<ReplaySnapshot | null>({
    fetcher: async () => {
      if (!autoCapture) return null;
      return archiver.capture();
    },
    interval: captureInterval,
    hiddenInterval: captureInterval * 3,
    enabled: autoCapture,
    immediate: true,
  });

  // Keep currentIndex at latest snapshot when not playing
  useEffect(() => {
    if (!playing && archiver.snapshots.length > 0) {
      setCurrentIndex(archiver.snapshots.length - 1);
    }
  }, [archiver.snapshots.length, playing]);

  // Playback
  useEffect(() => {
    if (!playing) {
      if (playTimerRef.current) {
        clearInterval(playTimerRef.current);
        playTimerRef.current = null;
      }
      return;
    }
    const delay = 1000 / playSpeed;
    playTimerRef.current = setInterval(() => {
      setCurrentIndex((prev) => {
        if (prev >= archiver.snapshots.length - 1) {
          setPlaying(false);
          return prev;
        }
        return prev + 1;
      });
    }, delay);
    return () => {
      if (playTimerRef.current) {
        clearInterval(playTimerRef.current);
        playTimerRef.current = null;
      }
    };
  }, [playing, playSpeed, archiver.snapshots.length]);

  const handleSeek = useCallback((index: number) => {
    setPlaying(false);
    setCurrentIndex(index);
  }, []);

  const handleManualCapture = useCallback(async () => {
    await archiver.capture();
  }, [archiver]);

  const handleExport = useCallback(() => {
    const json = archiver.exportJson();
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `worldbase-snapshots-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [archiver]);

  const handleImport = useCallback(() => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'application/json';
    input.onchange = async () => {
      const file = input.files?.[0];
      if (!file) return;
      const text = await file.text();
      const count = archiver.importJson(text);
      if (count > 0) setCurrentIndex(count - 1);
    };
    input.click();
  }, [archiver]);

  const currentSnap = useMemo(() => {
    if (currentIndex < 0 || currentIndex >= archiver.snapshots.length) return null;
    return archiver.snapshots[currentIndex];
  }, [archiver.snapshots, currentIndex]);

  return (
    <div className="temporal-replay">
      <div className="temporal-replay-header">
        <div className="temporal-replay-title">TEMPORAL REPLAY</div>
        <div className="temporal-replay-controls">
          <button
            className="replay-btn"
            onClick={() => handleSeek(0)}
            disabled={archiver.snapshots.length === 0}
            title="Jump to first"
            type="button"
          >
            ⏮
          </button>
          <button
            className="replay-btn"
            onClick={() => setPlaying((p) => !p)}
            disabled={archiver.snapshots.length < 2}
            type="button"
          >
            {playing ? '⏸' : '▶'}
          </button>
          <button
            className="replay-btn"
            onClick={() => handleSeek(archiver.snapshots.length - 1)}
            disabled={archiver.snapshots.length === 0}
            title="Jump to latest"
            type="button"
          >
            ⏭
          </button>
          <select
            className="replay-speed"
            value={playSpeed}
            onChange={(e) => setPlaySpeed(Number(e.target.value))}
          >
            <option value={0.5}>0.5×</option>
            <option value={1}>1×</option>
            <option value={2}>2×</option>
            <option value={4}>4×</option>
          </select>
          <span className="replay-separator">|</span>
          <label className="replay-toggle">
            <input
              type="checkbox"
              checked={autoCapture}
              onChange={(e) => setAutoCapture(e.target.checked)}
            />
            AUTO
          </label>
          <select
            className="replay-interval"
            value={captureInterval}
            onChange={(e) => setCaptureInterval(Number(e.target.value))}
            disabled={!autoCapture}
          >
            <option value={30_000}>30s</option>
            <option value={60_000}>1m</option>
            <option value={300_000}>5m</option>
          </select>
          <span className="replay-separator">|</span>
          <button className="replay-btn" onClick={handleManualCapture} type="button" title="Capture now">
            📸
          </button>
          <button className="replay-btn" onClick={handleExport} disabled={archiver.snapshots.length === 0} type="button">
            ↓
          </button>
          <button className="replay-btn" onClick={handleImport} type="button">
            ↑
          </button>
          <button className="replay-btn" onClick={archiver.clear} disabled={archiver.snapshots.length === 0} type="button">
            🗑
          </button>
        </div>
        {onClose && (
          <button className="temporal-replay-close" onClick={onClose} type="button">
            ✕
          </button>
        )}
      </div>

      <div className="temporal-replay-body">
        <div className="replay-timeline-section">
          <ReplayTimeline
            snapshots={archiver.snapshots}
            currentIndex={currentIndex}
            onSeek={handleSeek}
          />
          <div className="replay-counter">
            {currentIndex >= 0 ? `${currentIndex + 1} / ${archiver.snapshots.length}` : `${archiver.snapshots.length} snapshots`}
          </div>
        </div>

        <div className="replay-detail-section">
          {currentSnap ? (
            <SnapshotDetail snap={currentSnap} />
          ) : (
            <div className="replay-empty">
              {archiver.snapshots.length === 0
                ? 'No snapshots yet. Enable AUTO or press 📸 to capture.'
                : 'Select a snapshot on the timeline.'}
            </div>
          )}
        </div>
      </div>

      <div className="temporal-replay-footer">
        <span className="replay-status">
          Capture: {capturePoll.status} · Snapshots: {archiver.snapshots.length}/{archiver.maxSnapshots}
        </span>
      </div>
    </div>
  );
}
