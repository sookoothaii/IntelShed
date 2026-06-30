import { useCallback, useMemo, useState } from 'react';
import { DragDropContext, Droppable, Draggable, type DropResult } from '@hello-pangea/dnd';
import {
  useBriefingPipeline,
  useMovePipelineItem,
  useSyncPipeline,
  type PipelineItem,
} from '../hooks/useBriefingPipeline';
import ActionBar from './ActionBar';

const STAGE_COLORS: Record<string, string> = {
  INGEST: '#22d3ee',
  ANALYZE: '#a78bfa',
  CORROBORATE: '#fbbf24',
  SYNTHESIZE: '#fb923c',
  PUBLISHED: '#00ffa3',
};

const STAGE_LABELS: Record<string, string> = {
  INGEST: 'INGEST',
  ANALYZE: 'ANALYZE',
  CORROBORATE: 'CORROBORATE',
  SYNTHESIZE: 'SYNTHESIZE',
  PUBLISHED: 'PUBLISHED',
};

type Props = {
  onClose?: () => void;
};

export default function BriefingKanban({ onClose }: Props) {
  const { data, isLoading, error } = useBriefingPipeline({ refetchInterval: 60_000 });
  const moveItem = useMovePipelineItem();
  const syncPipeline = useSyncPipeline();
  const [syncFlash, setSyncFlash] = useState(false);
  const [selectedItem, setSelectedItem] = useState<PipelineItem | null>(null);

  const stages = data?.stages || ['INGEST', 'ANALYZE', 'CORROBORATE', 'SYNTHESIZE', 'PUBLISHED'];
  const pipeline = data?.pipeline || {};

  const onDragEnd = useCallback(
    (result: DropResult) => {
      if (!result.destination) return;
      const item_id = result.draggableId;
      const target_stage = result.destination.droppableId;
      if (result.source.droppableId === target_stage) return;
      moveItem.mutate({ item_id, target_stage });
    },
    [moveItem],
  );

  const handleSync = useCallback(() => {
    syncPipeline.mutate(undefined, {
      onSuccess: () => {
        setSyncFlash(true);
        setTimeout(() => setSyncFlash(false), 1200);
      },
    });
  }, [syncPipeline]);

  const totalItems = useMemo(
    () => stages.reduce((sum, s) => sum + (pipeline[s]?.length || 0), 0),
    [stages, pipeline],
  );

  return (
    <div className="kanban-overlay" role="dialog" aria-label="Briefing Pipeline Kanban">
      <div className="kanban-header">
        <div className="kanban-title">
          <span className="kanban-title-glyph">▦</span> BRIEFING PIPELINE
          <span className="kanban-count">{totalItems} items</span>
        </div>
        <div className="kanban-actions">
          <button
            className="kanban-btn"
            onClick={handleSync}
            disabled={syncPipeline.isPending}
            title="Sync pipeline from latest briefing"
          >
            {syncPipeline.isPending ? '⟳ SYNCING…' : '⟳ SYNC'}
          </button>
          {onClose && (
            <button className="kanban-btn kanban-btn--close" onClick={onClose} title="Close">
              ✕
            </button>
          )}
        </div>
      </div>

      {syncFlash && <div className="kanban-flash">Pipeline synced</div>}

      {isLoading && <div className="kanban-empty">Loading pipeline…</div>}
      {error && (
        <div className="kanban-empty kanban-empty--error">
          Failed to load pipeline: {String(error)}
        </div>
      )}

      {!isLoading && !error && totalItems === 0 && (
        <div className="kanban-empty">
          No items in pipeline. Click <strong>SYNC</strong> to load from the latest briefing.
        </div>
      )}

      {totalItems > 0 && (
        <DragDropContext onDragEnd={onDragEnd}>
          <div className="kanban-board">
            {stages.map((stage) => {
              const items = pipeline[stage] || [];
              const color = STAGE_COLORS[stage] || 'var(--accent-dim)';
              return (
                <div key={stage} className="kanban-column" style={{ borderTopColor: color }}>
                  <div className="kanban-column-head" style={{ color }}>
                    <span className="kanban-column-label">{STAGE_LABELS[stage] || stage}</span>
                    <span className="kanban-column-count">{items.length}</span>
                  </div>
                  <Droppable droppableId={stage}>
                    {(provided, snapshot) => (
                      <div
                        ref={provided.innerRef}
                        {...provided.droppableProps}
                        className={`kanban-column-body${snapshot.isDraggingOver ? ' kanban-column-body--over' : ''}`}
                      >
                        {items.map((item, idx) => (
                          <Draggable key={item.item_id} draggableId={item.item_id} index={idx}>
                            {(prov, snap) => (
                              <div
                                ref={prov.innerRef}
                                {...prov.draggableProps}
                                {...prov.dragHandleProps}
                                className={`kanban-card${snap.isDragging ? ' kanban-card--dragging' : ''}`}
                                data-item-type={item.item_type}
                              >
                                <div
                                  className="kanban-card-type"
                                  style={{ color: STAGE_COLORS[stage] || 'var(--accent-dim)' }}
                                >
                                  {item.item_type.toUpperCase()}
                                </div>
                                <div className="kanban-card-title">
                                  {item.title || item.item_id}
                                </div>
                                {item.confidence > 0 && (
                                  <div className="kanban-card-conf">
                                    <div
                                      className="kanban-card-conf-bar"
                                      style={{
                                        width: `${Math.round(item.confidence * 100)}%`,
                                        background: STAGE_COLORS[stage] || 'var(--accent-dim)',
                                      }}
                                    />
                                    <span>{Math.round(item.confidence * 100)}%</span>
                                  </div>
                                )}
                                {item.sources.length > 0 && (
                                  <div className="kanban-card-sources">
                                    {item.sources.slice(0, 3).map((s) => (
                                      <span key={s} className="kanban-card-source">
                                        {s}
                                      </span>
                                    ))}
                                    {item.sources.length > 3 && (
                                      <span className="kanban-card-source kanban-card-source--more">
                                        +{item.sources.length - 3}
                                      </span>
                                    )}
                                  </div>
                                )}
                                {item.lat != null && item.lon != null && (
                                  <div className="kanban-card-geo">
                                    {item.lat.toFixed(2)}, {item.lon.toFixed(2)}
                                  </div>
                                )}
                                <div className="kanban-card-actions">
                                  <button
                                    type="button"
                                    className="kanban-card-detail-btn"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setSelectedItem(item);
                                    }}
                                    aria-label="View actions"
                                    title="Actions"
                                  >
                                    ⋯
                                  </button>
                                </div>
                              </div>
                            )}
                          </Draggable>
                        ))}
                        {provided.placeholder}
                        {items.length === 0 && <div className="kanban-column-empty">—</div>}
                      </div>
                    )}
                  </Droppable>
                </div>
              );
            })}
          </div>
        </DragDropContext>
      )}
      {selectedItem && (
        <div className="kanban-detail-overlay" onClick={() => setSelectedItem(null)}>
          <div className="kanban-detail-panel" onClick={(e) => e.stopPropagation()}>
            <div className="kanban-detail-header">
              <span
                className="kanban-detail-type"
                style={{ color: STAGE_COLORS[selectedItem.stage] || 'var(--accent-dim)' }}
              >
                {selectedItem.item_type.toUpperCase()}
              </span>
              <span className="kanban-detail-title">
                {selectedItem.title || selectedItem.item_id}
              </span>
              <button
                className="kanban-btn kanban-btn--close"
                onClick={() => setSelectedItem(null)}
                title="Close"
              >
                ✕
              </button>
            </div>
            <div className="kanban-detail-meta">
              <span>
                Stage: <strong>{selectedItem.stage}</strong>
              </span>
              <span>
                Confidence: <strong>{Math.round(selectedItem.confidence * 100)}%</strong>
              </span>
              {selectedItem.sources.length > 0 && (
                <span>
                  Sources: <strong>{selectedItem.sources.join(', ')}</strong>
                </span>
              )}
              {selectedItem.lat != null && selectedItem.lon != null && (
                <span>
                  Coords:{' '}
                  <strong>
                    {selectedItem.lat.toFixed(2)}, {selectedItem.lon.toFixed(2)}
                  </strong>
                </span>
              )}
            </div>
            <ActionBar
              itemId={selectedItem.item_id}
              itemTitle={selectedItem.title}
              showPublish={selectedItem.stage !== 'PUBLISHED'}
            />
          </div>
        </div>
      )}
    </div>
  );
}
