export type AgenticTrace = {
  enabled?: boolean;
  rounds?: number;
  max_rounds?: number;
  status?: string;
  phases?: Array<Record<string, unknown>>;
  final_counts?: Record<string, number>;
};

export function agenticBadgeMeta(agentic: AgenticTrace | null | undefined): {
  label: string;
  tip: string;
  tone: 'ok' | 'warn' | 'off';
} | null {
  if (!agentic) return null;
  if (agentic.enabled === false) {
    return { label: 'OFF', tip: 'Agentic loop disabled (BRIEFING_AGENTIC_LOOP=0)', tone: 'off' };
  }
  const rounds = agentic.rounds ?? 0;
  const maxR = agentic.max_rounds ?? 3;
  const phases = (agentic.phases || []).map((p) => String(p.phase || '')).filter(Boolean);
  const coverage = agentic.phases?.find((p) => p.phase === 'coverage') as
    | Record<string, unknown>
    | undefined;
  const gaps = Array.isArray(coverage?.gaps) ? coverage!.gaps.length : 0;
  const retrieve = phases.includes('retrieve');
  const tip = [
    `Agentic loop ${rounds}/${maxR} rounds`,
    phases.length ? `phases: ${phases.join(' → ')}` : '',
    gaps ? `${gaps} bucket gap(s) at start` : 'coverage OK',
    retrieve ? 'RAG retrieve ran' : 'no retrieve (coverage sufficient)',
    agentic.status ? `status: ${agentic.status}` : '',
  ]
    .filter(Boolean)
    .join(' · ');
  return {
    label: `A${rounds}`,
    tip,
    tone: gaps && !retrieve ? 'warn' : 'ok',
  };
}
