import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Color,
  Viewer
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';
import { feedPos, feedPoint, timelineCutoffMs } from './layerUtils';
import { type PulseRingSpec, startPulseAnimator } from '../../lib/cesiumPulseRing';

export function useQuakesLayer({
  viewer,
  active,
  feedActive,
  canFetch,
  setStats,
  scrubT,
  timelineHours
}: {
  viewer: Viewer | null;
  active: boolean;
  feedActive: boolean;
  canFetch: boolean;
  setStats: React.Dispatch<React.SetStateAction<any>>;
  scrubT: number;
  timelineHours: number;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);
  const pulseRef = useRef<PulseRingSpec[]>([]);

  const { data } = useQuery({
    queryKey: ['earthquakes'],
    queryFn: async () => {
      const r = await fetchApi('/api/earthquakes?period=day&magnitude=2.5');
      return r.json();
    },
    refetchInterval: 60000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('quakes');
    attachDataSource(viewer, src);
    srcRef.current = src;
    
    return () => {
      detachDataSource(viewer, src);
      srcRef.current = null;
    };
  }, [viewer]);

  useEffect(() => {
    if (!viewer || !active) return;
    return startPulseAnimator(viewer, () => pulseRef.current);
  }, [viewer, active]);

  useEffect(() => {
    if (!srcRef.current) return;
    srcRef.current.show = active;
  }, [active]);

  useEffect(() => {
    if (!data || !srcRef.current || !active) return;
    const src = srcRef.current;
    
    const cutoff = timelineCutoffMs(scrubT, timelineHours);
    const list = (data.earthquakes || []).filter((q: any) => (q.time ?? 0) <= cutoff);
    
    src.entities.suspendEvents();
    src.entities.removeAll();
    pulseRef.current = [];
    
    for (const q of list) {
      if (q.lon == null || q.lat == null) continue;
      const mag = q.mag ?? 0;
      const sev = Math.min(mag / 8, 1);
      
      const ent = src.entities.add({
        position: feedPos(q.lon, q.lat),
        point: feedPoint(4 + mag * 2.5, Color.fromHsl(0.02 + 0.08 * (1 - sev), 1.0, 0.5, 0.9), {
          outline: Color.BLACK,
          outlineWidth: 1,
        }),
        properties: { kind: 'quake', place: q.place, mag, depth: q.depth, time: q.time } as any,
      });
      
      if (mag >= 5) {
        pulseRef.current.push({
          entity: ent,
          t0: Date.now(),
          periodMs: 2000,
          baseRadius: 30000,
          ampRadius: mag * 90000,
          color: Color.fromCssColorString('#ff3b30'),
          alphaPeak: 0.4,
        });
      }
    }
    
    src.entities.resumeEvents();
    setStats((p: any) => ({ ...p, quakes: list.length }));
  }, [viewer, data, active, scrubT, timelineHours, setStats]);
}
