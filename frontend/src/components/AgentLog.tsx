import { useEffect, useRef, useState, useCallback } from 'react';
import { AGENT_PHASE_EVENT, agentBusEnabled, type AgentPhaseDetail } from '../lib/agentBus';

type LogEntry = {
  id: number;
  ts: string;
  title: string;
  lines: string[];
};

const MAX_ENTRIES = 20;

const PHASE_COLORS: Record<string, string> = {
  Coverage: '#00e5ff',
  Retrieval: '#00e5a0',
  Spatial: '#ffd23f',
  Corroboration: '#ff6b35',
  Synthesis: '#ff2d00',
  Critique: '#a855f7',
  Revise: '#a855f7',
};

export function AgentLog() {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [open, setOpen] = useState(true);
  const idRef = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!agentBusEnabled()) return;

    const onPhase = (ev: Event) => {
      const detail = (ev as CustomEvent<AgentPhaseDetail>).detail;
      if (!detail?.title) return;
      const entry: LogEntry = {
        id: ++idRef.current,
        ts: detail.ts || new Date().toISOString().slice(11, 19),
        title: detail.title,
        lines: detail.lines || [],
      };
      setEntries((prev) => [...prev.slice(-(MAX_ENTRIES - 1)), entry]);
    };

    window.addEventListener(AGENT_PHASE_EVENT, onPhase);
    return () => window.removeEventListener(AGENT_PHASE_EVENT, onPhase);
  }, []);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [entries]);

  const toggle = useCallback(() => setOpen((v) => !v), []);

  if (!agentBusEnabled()) return null;

  return (
    <div className={`agent-log${open ? '' : ' agent-log--collapsed'}`}>
      <button
        type="button"
        className="agent-log-toggle"
        onClick={toggle}
        aria-label="Toggle agent log"
      >
        {open ? '▾' : '▸'} AGENT SWARM
      </button>
      {open && (
        <div className="agent-log-body" ref={scrollRef}>
          {entries.length === 0 ? (
            <div className="agent-log-empty">Awaiting orchestrator events…</div>
          ) : (
            entries.map((e) => (
              <div key={e.id} className="agent-log-entry">
                <span className="agent-log-ts">{e.ts}</span>
                <span
                  className="agent-log-phase"
                  style={{ color: PHASE_COLORS[e.title] || '#00e5ff' }}
                >
                  {e.title.toUpperCase()}
                </span>
                {e.lines.map((line, i) => (
                  <span key={i} className="agent-log-line">
                    {line}
                  </span>
                ))}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
