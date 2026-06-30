import { useCallback, useEffect, useState } from 'react';
import { fetchApi } from '../lib/networkFetch';

type TimelineEvent = {
  type: string;
  timestamp: string;
  detail?: string;
  prop?: string;
  value?: string;
  dataset?: string;
  lang?: string | null;
  kind?: string;
  direction?: string;
  other_id?: string;
  confidence?: number | null;
  source_ref?: string | null;
};

type TimelineData = {
  entity_id: string;
  found: boolean;
  schema?: string;
  caption?: string;
  first_seen?: string | null;
  last_seen?: string | null;
  event_count: number;
  events: TimelineEvent[];
  error?: string;
};

const EVENT_ICON: Record<string, string> = {
  entity_created: '✨',
  entity_updated: '🔄',
  statement: '📝',
  edge: '🔗',
  intel_edge: '🛡',
};

const fmtTs = (ts: string) => {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return ts.slice(0, 19);
  }
};

const fmtConfidence = (v?: number | null) =>
  v == null || Number.isNaN(v) ? '' : `${Math.round(v * 100)}%`;

interface Props {
  entityId: string;
}

export default function EntityTimeline({ entityId }: Props) {
  const [data, setData] = useState<TimelineData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!entityId) return;
    setLoading(true);
    setError(null);
    try {
      const r = await fetchApi(
        `/api/intel/entities/${encodeURIComponent(entityId)}/timeline`,
      );
      const d: TimelineData = await r.json();
      if (d.error) {
        setError(d.error);
      } else {
        setData(d);
      }
    } catch (e: unknown) {
      setError(`timeline: ${(e as Error).message || e}`);
    } finally {
      setLoading(false);
    }
  }, [entityId]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    return (
      <div className="intel-section">
        <h3>📅 Entity Timeline</h3>
        <div className="stat-meta">Loading…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="intel-section">
        <h3>📅 Entity Timeline</h3>
        <div className="data-error">{error}</div>
      </div>
    );
  }

  if (!data || !data.found) {
    return (
      <div className="intel-section">
        <h3>📅 Entity Timeline</h3>
        <div className="stat-meta">Entity not found</div>
      </div>
    );
  }

  return (
    <div className="intel-section">
      <h3>
        📅 Entity Timeline{' '}
        <span className="stat-meta">
          {data.caption || data.entity_id.slice(0, 12)} · {data.schema} ·{' '}
          {data.event_count} events
        </span>
      </h3>

      {(data.first_seen || data.last_seen) && (
        <div className="stat-meta" style={{ marginBottom: '6px' }}>
          {data.first_seen && `first_seen: ${fmtTs(data.first_seen)}`}
          {data.first_seen && data.last_seen && ' → '}
          {data.last_seen && `last_seen: ${fmtTs(data.last_seen)}`}
        </div>
      )}

      <div className="timeline-list">
        {data.events.map((ev, i) => (
          <div key={i} className={`timeline-event timeline-${ev.type}`}>
            <span className="timeline-icon">{EVENT_ICON[ev.type] || '•'}</span>
            <span className="timeline-ts">{fmtTs(ev.timestamp)}</span>
            <span className="timeline-detail">
              {ev.type === 'entity_created' || ev.type === 'entity_updated'
                ? ev.detail
                : ev.type === 'statement'
                  ? `${ev.prop}: ${ev.value}${ev.dataset ? ` (${ev.dataset})` : ''}`
                  : ev.type === 'edge' || ev.type === 'intel_edge'
                    ? `${ev.direction === 'incoming' ? '←' : '→'} ${ev.kind} ${ev.other_id?.slice(0, 12) || ''}${fmtConfidence(ev.confidence) ? ` · ${fmtConfidence(ev.confidence)}` : ''}${ev.dataset ? ` · ${ev.dataset}` : ''}`
                    : ev.type}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
