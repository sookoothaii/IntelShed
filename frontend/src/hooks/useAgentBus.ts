import { useEffect } from 'react';
import type { FocusTarget } from '../lib/focus';
import {
  agentBusEnabled,
  dispatchAgentLayerToggle,
  dispatchAgentPhase,
  type AgentBusMessage,
} from '../lib/agentBus';
import { fetchApi } from '../lib/networkFetch';

type FlyToFn = (f: Omit<FocusTarget, 'ts'>) => void;

function handleAgentMessage(msg: AgentBusMessage, onFlyTo: FlyToFn): void {
  if (msg.type === 'connected') return;
  const action = (msg.action || '').toLowerCase();
  if (action === 'fly_to' && msg.lat != null && msg.lon != null) {
    onFlyTo({
      kind: 'agent_bus',
      lat: msg.lat,
      lon: msg.lon,
      height: msg.height ?? 400000,
      title: msg.title || 'Agent focus',
      lines: msg.lines || [],
    });
    return;
  }
  if (action === 'toggle_layer' && msg.layer) {
    dispatchAgentLayerToggle({ layer: msg.layer, enabled: msg.enabled });
    return;
  }
  if (action === 'agent_phase' && msg.title) {
    dispatchAgentPhase({
      title: msg.title,
      lines: msg.lines || [],
      lat: msg.lat,
      lon: msg.lon,
      ts: msg.ts,
    });
  }
}

/**
 * Subscribe to /api/agent/stream when VITE_WORLDBASE_AGENT_BUS=1.
 * Requires an open HUD tab with the globe visible for fly_to / layer toggles.
 */
export function useAgentBus(onFlyTo: FlyToFn): void {
  useEffect(() => {
    if (!agentBusEnabled()) return;

    const ac = new AbortController();

    const connect = async () => {
      try {
        const r = await fetchApi('/api/agent/stream', {
          signal: ac.signal,
          headers: { Accept: 'text/event-stream' },
        });
        if (!r.ok || !r.body) return;

        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (!ac.signal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const chunks = buffer.split('\n\n');
          buffer = chunks.pop() || '';
          for (const chunk of chunks) {
            const m = chunk.match(/^data: (.+)$/m);
            if (!m) continue;
            try {
              const msg = JSON.parse(m[1]) as AgentBusMessage;
              handleAgentMessage(msg, onFlyTo);
            } catch {
              /* ignore malformed */
            }
          }
        }
      } catch {
        if (!ac.signal.aborted) {
          window.setTimeout(connect, 5000);
        }
      }
    };

    connect();
    return () => ac.abort();
  }, [onFlyTo]);
}
