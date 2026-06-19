/** Agent Bus layer toggle event (Globe.tsx listens). */
export const AGENT_BUS_LAYER_EVENT = 'worldbase:agent-layer'

export type AgentLayerDetail = {
  layer: string
  enabled?: boolean
}

export type AgentBusMessage = {
  id?: string
  ts?: string
  action: string
  lat?: number
  lon?: number
  height?: number
  title?: string
  lines?: string[]
  layer?: string
  enabled?: boolean
  type?: string
}

export function agentBusEnabled(): boolean {
  return import.meta.env.VITE_WORLDBASE_AGENT_BUS === '1'
}

export function dispatchAgentLayerToggle(detail: AgentLayerDetail): void {
  window.dispatchEvent(new CustomEvent(AGENT_BUS_LAYER_EVENT, { detail }))
}
