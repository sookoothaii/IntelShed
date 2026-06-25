import { describe, it, expect } from 'vitest'
import { agenticBadgeMeta, type AgenticTrace } from '../../src/lib/agentic'

describe('agentic', () => {
  describe('agenticBadgeMeta', () => {
    it('returns null for null input', () => {
      expect(agenticBadgeMeta(null)).toBeNull()
    })

    it('returns null for undefined input', () => {
      expect(agenticBadgeMeta(undefined)).toBeNull()
    })

    it('returns OFF badge when disabled', () => {
      const trace: AgenticTrace = { enabled: false }
      const meta = agenticBadgeMeta(trace)!
      expect(meta.label).toBe('OFF')
      expect(meta.tone).toBe('off')
      expect(meta.tip).toContain('disabled')
    })

    it('returns badge with round count', () => {
      const trace: AgenticTrace = { enabled: true, rounds: 2, max_rounds: 3 }
      const meta = agenticBadgeMeta(trace)!
      expect(meta.label).toBe('A2')
      expect(meta.tone).toBe('ok')
    })

    it('shows warn tone when gaps exist and no retrieve', () => {
      const trace: AgenticTrace = {
        enabled: true,
        rounds: 1,
        max_rounds: 3,
        phases: [
          { phase: 'coverage', gaps: ['geo', 'maritime'] },
        ],
      }
      const meta = agenticBadgeMeta(trace)!
      expect(meta.tone).toBe('warn')
      expect(meta.tip).toContain('2 bucket gap')
    })

    it('shows ok tone when gaps exist but retrieve ran', () => {
      const trace: AgenticTrace = {
        enabled: true,
        rounds: 2,
        max_rounds: 3,
        phases: [
          { phase: 'coverage', gaps: ['geo'] },
          { phase: 'retrieve' },
        ],
      }
      const meta = agenticBadgeMeta(trace)!
      expect(meta.tone).toBe('ok')
      expect(meta.tip).toContain('RAG retrieve ran')
    })

    it('includes phase chain in tip', () => {
      const trace: AgenticTrace = {
        enabled: true,
        rounds: 3,
        max_rounds: 3,
        phases: [
          { phase: 'coverage' },
          { phase: 'retrieve' },
          { phase: 'corroboration' },
        ],
      }
      const meta = agenticBadgeMeta(trace)!
      expect(meta.tip).toContain('coverage → retrieve → corroboration')
    })

    it('shows coverage OK when no gaps', () => {
      const trace: AgenticTrace = {
        enabled: true,
        rounds: 1,
        max_rounds: 3,
        phases: [{ phase: 'coverage', gaps: [] }],
      }
      const meta = agenticBadgeMeta(trace)!
      expect(meta.tip).toContain('coverage OK')
    })

    it('includes status in tip when present', () => {
      const trace: AgenticTrace = {
        enabled: true,
        rounds: 2,
        max_rounds: 3,
        status: 'completed',
      }
      const meta = agenticBadgeMeta(trace)!
      expect(meta.tip).toContain('status: completed')
    })
  })
})
