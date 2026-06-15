import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Cartesian3,
  Color,
  Viewer
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';

export function useVolcanoesLayer({
  viewer,
  active,
  feedActive,
  canFetch,
  setStats
}: {
  viewer: Viewer | null;
  active: boolean;
  feedActive: boolean;
  canFetch: boolean;
  setStats: React.Dispatch<React.SetStateAction<any>>;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);

  const { data } = useQuery({
    queryKey: ['volcanoes'],
    queryFn: async () => {
      const r = await fetchApi('/api/volcanoes?active_only=false&limit=350');
      return r.json();
    },
    refetchInterval: 3600000, // 1 hour
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('volcanoes');
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
    
    src.entities.suspendEvents();
    src.entities.removeAll();
    
    let n = 0;
    for (const v of data.volcanoes || []) {
      if (v.lon == null || v.lat == null) continue;
      const col = Color.fromCssColorString(v.active ? '#ff4d5e' : '#6b7280');
      src.entities.add({
        position: Cartesian3.fromDegrees(v.lon, v.lat, Math.max(v.elevation_m || 0, 0)),
        point: {
          pixelSize: v.active ? 10 : 5,
          color: col.withAlpha(v.active ? 0.95 : 0.55),
          outlineColor: Color.BLACK,
          outlineWidth: 1,
        },
        properties: {
          kind: 'volcano',
          name: v.name,
          country: v.country,
          type: v.type,
          last_eruption: v.last_eruption,
          elevation_m: v.elevation_m,
          active: v.active,
        } as any,
      });
      n++;
    }
    
    src.entities.resumeEvents();
    setStats((p: any) => ({ ...p, volcanoes: n }));
  }, [viewer, data, active, setStats]);
}
