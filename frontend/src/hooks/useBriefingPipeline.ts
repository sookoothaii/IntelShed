import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { fetchApi } from '../lib/networkFetch';

async function getJson<T>(url: string): Promise<T> {
  const r = await fetchApi(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json() as T;
}

export type PipelineItem = {
  item_id: string;
  stage: string;
  title: string;
  item_type: string;
  confidence: number;
  sources: string[];
  lat: number | null;
  lon: number | null;
  bucket: string;
  created_at: string;
  updated_at: string;
  payload: Record<string, unknown>;
};

export type PipelineData = {
  stages: string[];
  pipeline: Record<string, PipelineItem[]>;
};

export function useBriefingPipeline(opts?: {
  refetchInterval?: number | false;
  enabled?: boolean;
}) {
  return useQuery({
    queryKey: ['briefing-pipeline'],
    queryFn: () => getJson<PipelineData>('/api/briefing/pipeline'),
    refetchInterval: opts?.refetchInterval ?? 60_000,
    enabled: opts?.enabled ?? true,
  });
}

export function useMovePipelineItem() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (params: { item_id: string; target_stage: string }) => {
      const r = await fetchApi('/api/briefing/pipeline/move', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    },
    onMutate: async ({ item_id, target_stage }) => {
      await qc.cancelQueries({ queryKey: ['briefing-pipeline'] });
      const prev = qc.getQueryData<PipelineData>(['briefing-pipeline']);
      if (prev) {
        const next: PipelineData = { ...prev, pipeline: { ...prev.pipeline } };
        for (const stage of prev.stages) {
          if (stage === target_stage) continue;
          next.pipeline[stage] = (prev.pipeline[stage] || []).map((item) =>
            item.item_id === item_id ? { ...item, stage: target_stage } : item,
          );
        }
        const movedItem = (prev.pipeline[target_stage] || []).find((i) => i.item_id === item_id);
        if (!movedItem) {
          for (const stage of prev.stages) {
            const found = (prev.pipeline[stage] || []).find((i) => i.item_id === item_id);
            if (found) {
              next.pipeline[target_stage] = [
                ...(prev.pipeline[target_stage] || []),
                { ...found, stage: target_stage },
              ];
              break;
            }
          }
        }
        qc.setQueryData<PipelineData>(['briefing-pipeline'], next);
      }
      return { prev };
    },
    onError: (_err, _vars, ctx) => {
      if (ctx?.prev) qc.setQueryData(['briefing-pipeline'], ctx.prev);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['briefing-pipeline'] });
    },
  });
}

export function useSyncPipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const r = await fetchApi('/api/briefing/pipeline/sync', {
        method: 'POST',
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ['briefing-pipeline'] });
    },
  });
}
