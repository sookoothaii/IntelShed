import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Cartesian3,
  Color,
  LabelStyle,
  VerticalOrigin,
  Cartesian2,
  DistanceDisplayCondition,
  Viewer
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';
import type { Stats } from '../../lib/types';

const aqColor = (pm25: number | null) => {
  if (pm25 == null) return '#6f8c84';
  if (pm25 <= 12) return '#00e5a0';
  if (pm25 <= 35) return '#ffd23f';
  if (pm25 <= 55) return '#ff6b35';
  return '#ff2d00';
};

export function useAirqualityLayer({
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
    queryKey: ['airquality'],
    queryFn: async () => {
      const r = await fetchApi('/api/airquality');
      return r.json();
    },
    refetchInterval: 300000, // 5 min
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('airquality');
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
    
    for (const c of data.cities || []) {
      if (c.lon == null || c.lat == null) continue;
      const col = Color.fromCssColorString(aqColor(c.pm25));
      src.entities.add({
        position: Cartesian3.fromDegrees(c.lon, c.lat, 0),
        point: {
          pixelSize: 12,
          color: col.withAlpha(0.9),
          outlineColor: Color.BLACK,
          outlineWidth: 1,
        },
        label: {
          text: c.city,
          font: '600 9px "Courier New"',
          fillColor: col,
          outlineColor: Color.BLACK,
          outlineWidth: 2,
          style: LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: VerticalOrigin.BOTTOM,
          pixelOffset: new Cartesian2(0, -10),
          distanceDisplayCondition: new DistanceDisplayCondition(0, 2e7),
        },
        properties: {
          kind: 'airquality',
          city: c.city,
          pm25: c.pm25,
          pm10: c.pm10,
          time: c.time,
        },
      });
    }
    
    src.entities.resumeEvents();
    setStats((p: Stats) => ({ ...p, airquality: (data?.cities || []).length }));
  }, [viewer, data, active, setStats]);
}
