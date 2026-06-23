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
import { attachPulseEllipse, clearPulseCleanups } from './pulseAnimation';

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
  const pulseCleanupsRef = useRef<Array<() => void>>([]);

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
      clearPulseCleanups(pulseCleanupsRef.current);
      detachDataSource(viewer, src);
      srcRef.current = null;
    };
  }, [viewer]);

  useEffect(() => {
    if (!srcRef.current) return;
    srcRef.current.show = active;
  }, [active]);

  useEffect(() => {
    if (!data || !srcRef.current || !active) return;
    const src = srcRef.current;
    
    const cutoff = timelineCutoffMs(scrubT, timelineHours);
    const list = (data.earthquakes || []).filter((q: any) => (q.time ?? 0) <= cutoff);
    
    clearPulseCleanups(pulseCleanupsRef.current);
    src.entities.suspendEvents();
    src.entities.removeAll();
    
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
        pulseCleanupsRef.current.push(
          attachPulseEllipse(ent, {
            baseRadius: 30000,
            pulseScale: mag * 90000,
            color: Color.fromCssColorString('#ff3b30'),
            alphaScale: 0.4,
            minorScale: 0.95,
          }),
        );
      }
    }
    
    src.entities.resumeEvents();
    setStats((p: any) => ({ ...p, quakes: list.length }));
  }, [viewer, data, active, scrubT, timelineHours, setStats]);
}
