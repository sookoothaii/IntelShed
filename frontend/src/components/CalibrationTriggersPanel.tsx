import { useCallback, useEffect, useState } from 'react';
import { fetchApi } from '../lib/networkFetch';

type CalibrationBin = {
  bin_label: string;
  bin_low: number;
  bin_high: number;
  count: number;
  hits: number;
  misses: number;
  actual_accuracy: number | null;
  mean_confidence: number | null;
  calibration_gap: number | null;
};

type CalibrationCurve = {
  window_days: number;
  n_bins: number;
  total_resolved: number;
  bins: CalibrationBin[];
  overall_accuracy: number | null;
  mean_confidence: number | null;
  calibration_error: number | null;
  enabled: boolean;
};

type CalibrationMapBin = {
  bin_label: string;
  bin_low: number;
  bin_high: number;
  count: number;
  raw_confidence: number | null;
  actual_accuracy: number | null;
  adjusted_confidence: number | null;
  adjustment_factor: number | null;
  samples_sufficient: boolean;
};

type CalibrationMap = {
  window_days: number;
  n_bins: number;
  total_resolved: number;
  smoothing_k: number;
  min_samples: number;
  overall_accuracy: number | null;
  calibration_error: number | null;
  bins: CalibrationMapBin[];
  enabled: boolean;
};

type TriggerEntry = {
  id: number;
  rule_name: string;
  fired_at: string;
  cell_id: string | null;
  watch_id: string | null;
  confidence: number;
  severity: string;
  context: string;
  dismissed: number;
  dismissed_at: string | null;
  dismissed_reason: string | null;
};

type TriggerRule = {
  id: number;
  name: string;
  condition: string;
  min_confidence: number;
  bucket_filter: string | null;
  severity: string;
  cooldown_min: number;
  enabled: number;
};

type TriggerStats = {
  total_fires: number;
  active: number;
  critical_active: number;
  enabled_rules: number;
};

type Props = {
  onClose: () => void;
};

const SEV_CLASS: Record<string, string> = {
  critical: 'trig-sev-critical',
  warning: 'trig-sev-warning',
  info: 'trig-sev-info',
};

export default function CalibrationTriggersPanel({ onClose }: Props) {
  const [tab, setTab] = useState<'calibration' | 'triggers' | 'rules'>('calibration');
  const [curve, setCurve] = useState<CalibrationCurve | null>(null);
  const [cmap, setCmap] = useState<CalibrationMap | null>(null);
  const [triggers, setTriggers] = useState<TriggerEntry[]>([]);
  const [triggerStats, setTriggerStats] = useState<TriggerStats | null>(null);
  const [rules, setRules] = useState<TriggerRule[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nBins, setNBins] = useState(5);

  const fetchCalibration = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cRes, mRes] = await Promise.all([
        fetchApi(`/api/predictions/calibration?n_bins=${nBins}`),
        fetchApi(`/api/predictions/calibration/map?n_bins=${nBins}`),
      ]);
      if (cRes.ok) setCurve(await cRes.json());
      if (mRes.ok) setCmap(await mRes.json());
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [nBins]);

  const fetchTriggers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchApi('/api/triggers?limit=50&include_dismissed=true');
      if (res.ok) {
        const data = await res.json();
        setTriggers(data.triggers || []);
        setTriggerStats(data.stats || null);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchRules = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchApi('/api/triggers/rules?include_disabled=true');
      if (res.ok) {
        const data = await res.json();
        setRules(data.rules || []);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (tab === 'calibration') fetchCalibration();
    else if (tab === 'triggers') fetchTriggers();
    else if (tab === 'rules') fetchRules();
  }, [tab, fetchCalibration, fetchTriggers, fetchRules]);

  const dismissTrigger = async (id: number) => {
    try {
      await fetchApi(`/api/triggers/${id}/dismiss`, { method: 'POST' });
      fetchTriggers();
    } catch (e) {
      setError(String(e));
    }
  };

  const evaluateNow = async () => {
    setLoading(true);
    try {
      const res = await fetchApi('/api/triggers/evaluate', { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        if (data.fired?.length > 0) {
          setError(`${data.fired.length} trigger(s) fired`);
        } else {
          setError('No triggers fired');
        }
        fetchTriggers();
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="cal-trig-overlay" onClick={onClose}>
      <div className="cal-trig-panel" onClick={(e) => e.stopPropagation()}>
        <div className="cal-trig-header">
          <h2>CALIBRATION & TRIGGERS</h2>
          <div className="cal-trig-tabs">
            <button
              className={tab === 'calibration' ? 'active' : ''}
              onClick={() => setTab('calibration')}
            >
              CALIBRATION
            </button>
            <button
              className={tab === 'triggers' ? 'active' : ''}
              onClick={() => setTab('triggers')}
            >
              TRIGGERS
              {triggerStats && triggerStats.active > 0 && (
                <span className="trig-badge">{triggerStats.active}</span>
              )}
            </button>
            <button className={tab === 'rules' ? 'active' : ''} onClick={() => setTab('rules')}>
              RULES
            </button>
          </div>
          <button className="cal-trig-close" onClick={onClose} title="Close">
            ✕
          </button>
        </div>

        {error && <div className="cal-trig-error">{error}</div>}

        {loading && <div className="cal-trig-loading">Loading…</div>}

        {/* CALIBRATION TAB */}
        {tab === 'calibration' && !loading && (
          <div className="cal-trig-content">
            {/* Curve section */}
            <section>
              <h3>Calibration Curve</h3>
              <div className="cal-controls">
                <label>
                  Bins:
                  <select value={nBins} onChange={(e) => setNBins(Number(e.target.value))}>
                    {[2, 3, 5, 7, 10].map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </label>
                <button onClick={fetchCalibration}>Refresh</button>
              </div>

              {curve && (
                <>
                  <div className="cal-summary">
                    <span>
                      Resolved: <b>{curve.total_resolved}</b>
                    </span>
                    <span>
                      Overall Accuracy:{' '}
                      <b>
                        {curve.overall_accuracy != null
                          ? `${(curve.overall_accuracy * 100).toFixed(1)}%`
                          : '—'}
                      </b>
                    </span>
                    <span>
                      Mean Confidence:{' '}
                      <b>
                        {curve.mean_confidence != null ? curve.mean_confidence.toFixed(3) : '—'}
                      </b>
                    </span>
                    <span
                      className={
                        curve.calibration_error != null && curve.calibration_error > 0.15
                          ? 'cal-ece-bad'
                          : ''
                      }
                    >
                      ECE:{' '}
                      <b>
                        {curve.calibration_error != null ? curve.calibration_error.toFixed(3) : '—'}
                      </b>
                    </span>
                  </div>

                  {curve.total_resolved > 0 ? (
                    <div className="cal-bins">
                      <div className="cal-bin-header">
                        <span>Bin</span>
                        <span>Count</span>
                        <span>Hits</span>
                        <span>Misses</span>
                        <span>Actual Acc</span>
                        <span>Mean Conf</span>
                        <span>Gap</span>
                      </div>
                      {curve.bins.map((b) => (
                        <div key={b.bin_label} className="cal-bin-row">
                          <span>{b.bin_label}</span>
                          <span>{b.count}</span>
                          <span className="cal-hit">{b.hits}</span>
                          <span className="cal-miss">{b.misses}</span>
                          <span>
                            {b.actual_accuracy != null
                              ? `${(b.actual_accuracy * 100).toFixed(0)}%`
                              : '—'}
                          </span>
                          <span>
                            {b.mean_confidence != null ? b.mean_confidence.toFixed(2) : '—'}
                          </span>
                          <span
                            className={
                              b.calibration_gap != null && b.calibration_gap > 0.15
                                ? 'cal-gap-bad'
                                : b.calibration_gap != null && b.calibration_gap < -0.15
                                  ? 'cal-gap-under'
                                  : ''
                            }
                          >
                            {b.calibration_gap != null
                              ? `${b.calibration_gap > 0 ? '+' : ''}${b.calibration_gap.toFixed(2)}`
                              : '—'}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="cal-empty">
                      No resolved predictions with confidence data yet. New predictions store
                      confidence automatically.
                    </p>
                  )}
                </>
              )}
            </section>

            {/* Calibration Map section */}
            {cmap && cmap.total_resolved > 0 && (
              <section>
                <h3>Fusion Weight Adjustment Map</h3>
                <p className="cal-explain">
                  Bayesian shrinkage: adjusted = (N×A + k×raw) / (N+k), k={cmap.smoothing_k}, min
                  samples={cmap.min_samples}
                </p>
                <div className="cal-bins">
                  <div className="cal-bin-header">
                    <span>Bin</span>
                    <span>Count</span>
                    <span>Raw Conf</span>
                    <span>Actual Acc</span>
                    <span>Adjusted</span>
                    <span>Factor</span>
                    <span>Sufficient</span>
                  </div>
                  {cmap.bins.map((b) => (
                    <div key={b.bin_label} className="cal-bin-row">
                      <span>{b.bin_label}</span>
                      <span>{b.count}</span>
                      <span>{b.raw_confidence != null ? b.raw_confidence.toFixed(2) : '—'}</span>
                      <span>
                        {b.actual_accuracy != null
                          ? `${(b.actual_accuracy * 100).toFixed(0)}%`
                          : '—'}
                      </span>
                      <span
                        className={
                          b.adjustment_factor != null && b.adjustment_factor < 0.9
                            ? 'cal-adj-down'
                            : ''
                        }
                      >
                        {b.adjusted_confidence != null ? b.adjusted_confidence.toFixed(2) : '—'}
                      </span>
                      <span>
                        {b.adjustment_factor != null ? b.adjustment_factor.toFixed(3) : '—'}
                      </span>
                      <span>{b.samples_sufficient ? '✓' : '—'}</span>
                    </div>
                  ))}
                </div>
              </section>
            )}
          </div>
        )}

        {/* TRIGGERS TAB */}
        {tab === 'triggers' && !loading && (
          <div className="cal-trig-content">
            <div className="trig-actions">
              <button onClick={evaluateNow} disabled={loading}>
                Evaluate Now
              </button>
              <button onClick={fetchTriggers}>Refresh</button>
            </div>

            {triggerStats && (
              <div className="trig-stats">
                <span>
                  Total Fires: <b>{triggerStats.total_fires}</b>
                </span>
                <span>
                  Active: <b>{triggerStats.active}</b>
                </span>
                <span>
                  Critical:{' '}
                  <b className={triggerStats.critical_active > 0 ? 'trig-crit' : ''}>
                    {triggerStats.critical_active}
                  </b>
                </span>
                <span>
                  Enabled Rules: <b>{triggerStats.enabled_rules}</b>
                </span>
              </div>
            )}

            {triggers.length > 0 ? (
              <div className="trig-list">
                {triggers.map((t) => (
                  <div
                    key={t.id}
                    className={`trig-entry ${SEV_CLASS[t.severity] || ''} ${t.dismissed ? 'trig-dismissed' : ''}`}
                  >
                    <div className="trig-entry-header">
                      <span className={`trig-sev-tag ${SEV_CLASS[t.severity] || ''}`}>
                        {t.severity.toUpperCase()}
                      </span>
                      <span className="trig-rule-name">{t.rule_name}</span>
                      <span className="trig-conf">conf={t.confidence.toFixed(2)}</span>
                      <span className="trig-time">{new Date(t.fired_at).toLocaleString()}</span>
                      {!t.dismissed && (
                        <button className="trig-dismiss-btn" onClick={() => dismissTrigger(t.id)}>
                          Dismiss
                        </button>
                      )}
                      {t.dismissed === 1 && <span className="trig-dismissed-tag">DISMISSED</span>}
                    </div>
                    <div className="trig-context">{t.context}</div>
                    {t.cell_id && <div className="trig-cell">Cell: {t.cell_id}</div>}
                  </div>
                ))}
              </div>
            ) : (
              <p className="cal-empty">
                No triggers fired yet. Click "Evaluate Now" to check current conditions.
              </p>
            )}
          </div>
        )}

        {/* RULES TAB */}
        {tab === 'rules' && !loading && (
          <div className="cal-trig-content">
            <div className="trig-actions">
              <button onClick={fetchRules}>Refresh</button>
            </div>

            {rules.length > 0 ? (
              <div className="rules-list">
                <div className="rules-header">
                  <span>Name</span>
                  <span>Condition</span>
                  <span>Min Conf</span>
                  <span>Bucket</span>
                  <span>Severity</span>
                  <span>Cooldown</span>
                  <span>Enabled</span>
                </div>
                {rules.map((r) => (
                  <div key={r.id} className="rule-row">
                    <span className="rule-name">{r.name}</span>
                    <span className="rule-condition">{r.condition}</span>
                    <span>{r.min_confidence.toFixed(2)}</span>
                    <span>{r.bucket_filter || 'any'}</span>
                    <span className={SEV_CLASS[r.severity] || ''}>{r.severity}</span>
                    <span>{r.cooldown_min}m</span>
                    <span>{r.enabled ? '✓' : '✗'}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="cal-empty">No rules configured.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
