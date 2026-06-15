import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Color,
  CallbackProperty,
  ColorMaterialProperty,
  Viewer
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';
import { feedPos, feedPoint, timelineCutoffMs } from './layerUtils';

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
        const t0 = Date.now();
        ent.ellipse = {
          semiMajorAxis: new CallbackProperty(() => {
            const ph = ((Date.now() - t0) % 2000) / 2000;
            return 30000 + ph * mag * 90000;
          }, false) as any,
          semiMinorAxis: new CallbackProperty(() => {
            const ph = ((Date.now() - t0) % 2000) / 2000;
            return (30000 + ph * mag * 90000) * 0.95;
          }, false) as any,
          material: new ColorMaterialProperty(
            new CallbackProperty(() => {
              const ph = ((Date.now() - t0) % 2000) / 2000;
              return Color.fromCssColorString('#ff3b30').withAlpha(0.4 * (1 - ph));
            }, false) as any
          ),
          height: 0,
        } as any;
      }
    }
    
    src.entities.resumeEvents();
    setStats((p: any) => ({ ...p, quakes: list.length }));
  }, [viewer, data, active, scrubT, timelineHours, setStats]);
}
