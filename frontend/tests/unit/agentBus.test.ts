import { describe, it, expect, vi, beforeEach } from 'vitest'
import { AGENT_BUS_LAYER_EVENT, agentBusEnabled, dispatchAgentLayerToggle } from '../../src/lib/agentBus'

describe('agentBus', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  describe('agentBusEnabled', () => {
    it('returns true when VITE_WORLDBASE_AGENT_BUS=1', async () => {
      vi.stubEnv('VITE_WORLDBASE_AGENT_BUS', '1')
      const mod = await import('../../src/lib/agentBus')
      expect(mod.agentBusEnabled()).toBe(true)
    })

    it('returns false when VITE_WORLDBASE_AGENT_BUS is unset', async () => {
      vi.stubEnv('VITE_WORLDBASE_AGENT_BUS', '')
      const mod = await import('../../src/lib/agentBus')
      expect(mod.agentBusEnabled()).toBe(false)
    })

    it('returns false when VITE_WORLDBASE_AGENT_BUS=0', async () => {
      vi.stubEnv('VITE_WORLDBASE_AGENT_BUS', '0')
      const mod = await import('../../src/lib/agentBus')
      expect(mod.agentBusEnabled()).toBe(false)
    })
  })

  describe('dispatchAgentLayerToggle', () => {
    it('dispatches CustomEvent with correct detail', () => {
      const spy = vi.fn()
      window.addEventListener(AGENT_BUS_LAYER_EVENT, spy)
      dispatchAgentLayerToggle({ layer: 'intelFt', enabled: true })
      expect(spy).toHaveBeenCalledOnce()
      const event = spy.mock.calls[0][0] as CustomEvent
      expect(event.detail).toEqual({ layer: 'intelFt', enabled: true })
      window.removeEventListener(AGENT_BUS_LAYER_EVENT, spy)
    })

    it('works without enabled field (undefined)', () => {
      const spy = vi.fn()
      window.addEventListener(AGENT_BUS_LAYER_EVENT, spy)
      dispatchAgentLayerToggle({ layer: 'quakes' })
      const event = spy.mock.calls[0][0] as CustomEvent
      expect(event.detail.layer).toBe('quakes')
      expect(event.detail.enabled).toBeUndefined()
      window.removeEventListener(AGENT_BUS_LAYER_EVENT, spy)
    })
  })

  describe('AGENT_BUS_LAYER_EVENT', () => {
    it('is the expected constant', () => {
      expect(AGENT_BUS_LAYER_EVENT).toBe('worldbase:agent-layer')
    })
  })
})
