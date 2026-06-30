import { memo, useEffect, useState } from 'react';
import { fetchApi } from '../lib/networkFetch';

/* ── Types ────────────────────────────────────────────────────────────────── */

interface EntityProvenance {
  entity_id: string;
  datasets: string[];
  total_statements: number;
  by_prop: Record<string, { count: number; datasets: string[] }>;
  by_dataset: Record<string, number>;
}

interface ProvenanceSummary {
  total: number;
  scored: number;
  avg_score: number;
  min_score: number;
  max_score: number;
  by_dataset: Record<string, { count: number; avg_score: number }>;
  conflicts: number;
  entity_id: string;
}

interface ConflictEntry {
  prop: string;
  conflict_type: string;
  values: { value: string; dataset: string; seen_at: string | null }[];
}

interface ConflictsResponse {
  entity_id: string;
  conflicts: ConflictEntry[];
}

interface StatementStats {
  total_statements: number;
  by_dataset: Record<string, number>;
  by_prop: Record<string, number>;
}

/* ── Helpers ───────────────────────────────────────────────────────────────── */

function reliabilityColor(score: number): string {
  if (score >= 0.7) return 'var(--green)';
  if (score >= 0.4) return 'var(--amber)';
  return 'var(--red)';
}

function fmtDate(ts: string | null | undefined): string {
  if (!ts) return '—';
  try {
    return new Date(ts).toLocaleDateString(undefined, {
      year: '2-digit',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return '—';
  }
}

/* ── Component ─────────────────────────────────────────────────────────────── */

interface ProvenanceChainProps {
  entityId: string;
  compact?: boolean;
}

function ProvenanceChainInner({ entityId, compact = false }: ProvenanceChainProps) {
  const [provenance, setProvenance] = useState<EntityProvenance | null>(null);
  const [summary, setSummary] = useState<ProvenanceSummary | null>(null);
  const [conflicts, setConflicts] = useState<ConflictEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!entityId) return;
    let active = true;
    setLoading(true);
    setError(null);

    Promise.all([
      fetchApi(`/api/intel/entity/${encodeURIComponent(entityId)}/provenance`).then((r) =>
        r.ok ? r.json() : null,
      ),
      fetchApi(
        `/api/intel/statements/provenance/summary?entity_id=${encodeURIComponent(entityId)}`,
      ).then((r) => (r.ok ? r.json() : null)),
      fetchApi(`/api/intel/statements/conflicts?entity_id=${encodeURIComponent(entityId)}`).then(
        (r) => (r.ok ? r.json() : null),
      ),
    ])
      .then(
        ([prov, summ, conf]: [
          EntityProvenance | null,
          ProvenanceSummary | null,
          ConflictsResponse | null,
        ]) => {
          if (!active) return;
          setProvenance(prov);
          setSummary(summ);
          setConflicts(conf?.conflicts ?? []);
          setLoading(false);
        },
      )
      .catch(() => {
        if (!active) return;
        setError('Failed to load provenance');
        setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [entityId]);

  if (!entityId) return null;

  if (loading) {
    return (
      <div className={`provenance-chain${compact ? ' provenance-chain--compact' : ''}`}>
        <div className="provenance-chain-loading">Loading provenance…</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={`provenance-chain${compact ? ' provenance-chain--compact' : ''}`}>
        <div className="provenance-chain-error">{error}</div>
      </div>
    );
  }

  const totalStatements = summary?.total ?? provenance?.total_statements ?? 0;
  const avgScore = summary?.avg_score ?? 0;
  const conflictCount = summary?.conflicts ?? conflicts.length;
  const datasets = summary?.by_dataset ?? {};
  const datasetNames = Object.keys(datasets).sort();

  // Corroboration: props with multiple datasets agreeing
  const corroboratedProps = provenance
    ? Object.entries(provenance.by_prop).filter(([, info]) => info.datasets.length > 1).length
    : 0;

  return (
    <div
      className={`provenance-chain${compact ? ' provenance-chain--compact' : ''}`}
      role="region"
      aria-label={`Provenance chain for entity ${entityId}`}
    >
      {/* Summary header */}
      <div className="provenance-chain-header">
        <span className="provenance-chain-stat">
          <strong>{totalStatements}</strong> statements
        </span>
        <span className="provenance-chain-stat">
          <i
            className="provenance-chain-dot"
            style={{ background: reliabilityColor(avgScore) }}
            aria-hidden="true"
          />
          {Math.round(avgScore * 100)}% avg
        </span>
        {conflictCount > 0 && (
          <span
            className="provenance-chain-badge provenance-chain-badge--conflict"
            title="Cross-dataset value disputes"
          >
            ⚠ {conflictCount} conflict{conflictCount > 1 ? 's' : ''}
          </span>
        )}
        {corroboratedProps > 0 && (
          <span
            className="provenance-chain-badge provenance-chain-badge--corrob"
            title="Properties confirmed by multiple sources"
          >
            ✓ {corroboratedProps} corroborated
          </span>
        )}
      </div>

      {/* Per-dataset rows */}
      {datasetNames.length > 0 && (
        <div className="provenance-chain-rows">
          {datasetNames.map((ds) => {
            const info = datasets[ds];
            const score = info?.avg_score ?? 0;
            const count = info?.count ?? 0;
            return (
              <div key={ds} className="provenance-chain-row">
                <i
                  className="provenance-chain-dot"
                  style={{ background: reliabilityColor(score) }}
                  aria-hidden="true"
                />
                <span className="provenance-chain-dataset">{ds}</span>
                <span className="provenance-chain-count">{count}</span>
                <span className="provenance-chain-score">{Math.round(score * 100)}%</span>
              </div>
            );
          })}
        </div>
      )}

      {/* Conflict details */}
      {!compact && conflicts.length > 0 && (
        <div className="provenance-chain-conflicts">
          <div className="provenance-chain-conflicts-title">CONFLICTS</div>
          {conflicts.map((c, i) => (
            <div key={i} className="provenance-chain-conflict-entry">
              <span className="provenance-chain-conflict-prop">{c.prop}</span>
              <div className="provenance-chain-conflict-values">
                {c.values.map((v, j) => (
                  <span key={j} className="provenance-chain-conflict-value">
                    <strong>{v.value}</strong>
                    <span className="provenance-chain-conflict-dataset">{v.dataset}</span>
                    <span className="provenance-chain-conflict-date">{fmtDate(v.seen_at)}</span>
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Corroboration details */}
      {!compact && corroboratedProps > 0 && provenance && (
        <div className="provenance-chain-corrob">
          <div className="provenance-chain-corrob-title">CORROBORATED</div>
          {Object.entries(provenance.by_prop)
            .filter(([, info]) => info.datasets.length > 1)
            .map(([prop, info]) => (
              <div key={prop} className="provenance-chain-corrob-row">
                <span className="provenance-chain-corrob-prop">{prop}</span>
                <span className="provenance-chain-corrob-sources">{info.datasets.join(', ')}</span>
                <span className="provenance-chain-corrob-count">
                  {info.datasets.length} sources
                </span>
              </div>
            ))}
        </div>
      )}

      {totalStatements === 0 && (
        <div className="provenance-chain-empty">No provenance data for this entity</div>
      )}
    </div>
  );
}

const ProvenanceChain = memo(ProvenanceChainInner);
export default ProvenanceChain;

/* ── Global Stats Variant ──────────────────────────────────────────────────── */

export function ProvenanceGlobalStats() {
  const [stats, setStats] = useState<StatementStats | null>(null);

  useEffect(() => {
    let active = true;
    fetchApi('/api/intel/statements/stats')
      .then((r) => (r.ok ? r.json() : null))
      .then((d: StatementStats | null) => active && setStats(d))
      .catch(() => {});
    return () => {
      active = false;
    };
  }, []);

  if (!stats || stats.total_statements === 0) return null;

  const datasets = Object.entries(stats.by_dataset)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 12);

  return (
    <div className="provenance-chain" role="region" aria-label="Global provenance statistics">
      <div className="provenance-chain-header">
        <span className="provenance-chain-stat">
          <strong>{stats.total_statements}</strong> total statements
        </span>
        <span className="provenance-chain-stat">{datasets.length} datasets</span>
      </div>
      <div className="provenance-chain-rows">
        {datasets.map(([ds, count]) => (
          <div key={ds} className="provenance-chain-row">
            <i
              className="provenance-chain-dot"
              style={{ background: 'var(--green)' }}
              aria-hidden="true"
            />
            <span className="provenance-chain-dataset">{ds}</span>
            <span className="provenance-chain-count">{count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
