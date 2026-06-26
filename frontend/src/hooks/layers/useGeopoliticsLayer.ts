import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Color,
  LabelStyle,
  VerticalOrigin,
  Cartesian2,
  DistanceDisplayCondition,
  Viewer
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';
import { feedPos, feedPoint } from './layerUtils';
import type { Stats, GeopoliticsDisaster } from '../../lib/types';

export function useGeopoliticsLayer({
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
  setStats: React.Dispatch<React.SetStateAction<Stats>>;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);

  const { data } = useQuery({
    queryKey: ['geopolitics'],
    queryFn: async () => {
      const r = await fetchApi('/api/geopolitics');
      return r.json();
    },
    refetchInterval: 300000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('geopolitics');
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
    const disasters: GeopoliticsDisaster[] = data.disasters || [];
    
    src.entities.suspendEvents();
    src.entities.removeAll();
    
    for (const dis of disasters) {
      const lat = dis.lat;
      const lon = dis.lon;
      if (lat == null || lon == null) continue;
      
      src.entities.add({
        position: feedPos(lon, lat),
        point: feedPoint(10, Color.fromCssColorString('#ff2d00'), { outlineWidth: 1 }),
        label: {
          text: dis.name.substring(0, 40),
          font: '600 10px "Courier New"',
          fillColor: Color.fromCssColorString('#ff6b35'),
          outlineColor: Color.BLACK,
          outlineWidth: 2,
          style: LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: VerticalOrigin.BOTTOM,
          pixelOffset: new Cartesian2(0, -10),
          distanceDisplayCondition: new DistanceDisplayCondition(0, 1.5e7),
        },
        properties: {
          kind: 'geopolitics',
          name: dis.name,
          status: dis.status,
          id: dis.id,
          source: dis.source || 'crisis',
          url: dis.url || '',
        },
      });
    }
    
    src.entities.resumeEvents();
    setStats((p: Stats) => ({ ...p, geopolitics: disasters.length }));
  }, [viewer, data, active, setStats]);
}
