/** Agent Bus layer toggle event (Globe.tsx listens). */
export const AGENT_BUS_LAYER_EVENT = 'worldbase:agent-layer';

/** Agent Bus phase event (useAgentSwarm + AgentLog listen). */
export const AGENT_PHASE_EVENT = 'worldbase:agent-phase';

export type AgentLayerDetail = {
  layer: string;
  enabled?: boolean;
};

export type AgentPhaseDetail = {
  title: string;
  lines: string[];
  lat?: number;
  lon?: number;
  ts?: string;
};

export type AgentBusMessage = {
  id?: string;
  ts?: string;
  action: string;
  lat?: number;
  lon?: number;
  height?: number;
  title?: string;
  lines?: string[];
  layer?: string;
  enabled?: boolean;
  type?: string;
};

export function agentBusEnabled(): boolean {
  return import.meta.env.VITE_WORLDBASE_AGENT_BUS === '1';
}

export function dispatchAgentLayerToggle(detail: AgentLayerDetail): void {
  window.dispatchEvent(new CustomEvent(AGENT_BUS_LAYER_EVENT, { detail }));
}

export function dispatchAgentPhase(detail: AgentPhaseDetail): void {
  window.dispatchEvent(new CustomEvent(AGENT_PHASE_EVENT, { detail }));
}
