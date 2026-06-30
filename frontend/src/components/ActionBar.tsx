import { useCallback, useState } from 'react';
import { fetchApi } from '../lib/networkFetch';

export type ActionBarContext = {
  itemId: string;
  itemTitle?: string;
  entityId?: string;
  onFlagged?: (itemId: string) => void;
  onReAnalyzed?: (itemId: string) => void;
  onPublished?: (itemId: string) => void;
  showFlag?: boolean;
  showReAnalyze?: boolean;
  showPublish?: boolean;
};

type ActionState = 'idle' | 'pending' | 'success' | 'error';

export default function ActionBar({
  itemId,
  itemTitle,
  entityId,
  onFlagged,
  onReAnalyzed,
  onPublished,
  showFlag = true,
  showReAnalyze = true,
  showPublish = true,
}: ActionBarContext) {
  const [flagState, setFlagState] = useState<ActionState>('idle');
  const [analyzeState, setAnalyzeState] = useState<ActionState>('idle');
  const [publishState, setPublishState] = useState<ActionState>('idle');
  const [flagged, setFlagged] = useState(false);

  const handleFlag = useCallback(async () => {
    if (flagged) return;
    setFlagState('pending');
    try {
      const r = await fetchApi('/api/briefing/pipeline/move', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_id: itemId, target_stage: 'INGEST' }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setFlagged(true);
      setFlagState('success');
      onFlagged?.(itemId);
      setTimeout(() => setFlagState('idle'), 2000);
    } catch {
      setFlagState('error');
      setTimeout(() => setFlagState('idle'), 3000);
    }
  }, [itemId, flagged, onFlagged]);

  const handleReAnalyze = useCallback(async () => {
    setAnalyzeState('pending');
    try {
      const url = entityId
        ? `/api/intel/semantic/run?window_hours=24&include_sanctions=true`
        : `/api/intel/semantic/run?window_hours=24`;
      const r = await fetchApi(url, { method: 'POST' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setAnalyzeState('success');
      onReAnalyzed?.(itemId);
      setTimeout(() => setAnalyzeState('idle'), 2000);
    } catch {
      setAnalyzeState('error');
      setTimeout(() => setAnalyzeState('idle'), 3000);
    }
  }, [entityId, itemId, onReAnalyzed]);

  const handlePublish = useCallback(async () => {
    setPublishState('pending');
    try {
      const r = await fetchApi('/api/briefing/generate', { method: 'POST' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setPublishState('success');
      onPublished?.(itemId);
      setTimeout(() => setPublishState('idle'), 2000);
    } catch {
      setPublishState('error');
      setTimeout(() => setPublishState('idle'), 3000);
    }
  }, [itemId, onPublished]);

  const btnLabel = (
    state: ActionState,
    idle: string,
    pending: string,
    success: string,
    error: string,
  ) => {
    switch (state) {
      case 'pending':
        return pending;
      case 'success':
        return success;
      case 'error':
        return error;
      default:
        return idle;
    }
  };

  return (
    <div className="action-bar" role="toolbar" aria-label={`Actions for ${itemTitle || itemId}`}>
      {showFlag && (
        <button
          type="button"
          className={`action-bar-btn action-bar-btn--flag${flagged ? ' action-bar-btn--active' : ''}${flagState === 'pending' ? ' action-bar-btn--pending' : ''}${flagState === 'error' ? ' action-bar-btn--error' : ''}`}
          onClick={handleFlag}
          disabled={flagState === 'pending' || flagged}
          aria-label={
            flagged ? 'Flagged as false positive' : 'Flag as false positive / requires review'
          }
          title={flagged ? 'Flagged' : 'Flag as false positive / requires review'}
        >
          {flagged
            ? '✓ FLAGGED'
            : btnLabel(flagState, '⚑ FLAG', 'FLAGGING…', '✓ FLAGGED', '✗ ERROR')}
        </button>
      )}
      {showReAnalyze && (
        <button
          type="button"
          className={`action-bar-btn action-bar-btn--analyze${analyzeState === 'pending' ? ' action-bar-btn--pending' : ''}${analyzeState === 'success' ? ' action-bar-btn--success' : ''}${analyzeState === 'error' ? ' action-bar-btn--error' : ''}`}
          onClick={handleReAnalyze}
          disabled={analyzeState === 'pending'}
          aria-label="Re-run agent orchestrator on this item"
          title="Re-run agent orchestrator on this item"
        >
          {btnLabel(analyzeState, '⟳ RE-ANALYZE', 'ANALYZING…', '✓ DONE', '✗ ERROR')}
        </button>
      )}
      {showPublish && (
        <button
          type="button"
          className={`action-bar-btn action-bar-btn--publish${publishState === 'pending' ? ' action-bar-btn--pending' : ''}${publishState === 'success' ? ' action-bar-btn--success' : ''}${publishState === 'error' ? ' action-bar-btn--error' : ''}`}
          onClick={handlePublish}
          disabled={publishState === 'pending'}
          aria-label="Add to next briefing and push to Pi"
          title="Add to next briefing and push to Pi"
        >
          {btnLabel(publishState, '▶ PUBLISH', 'PUBLISHING…', '✓ PUBLISHED', '✗ ERROR')}
        </button>
      )}
    </div>
  );
}
