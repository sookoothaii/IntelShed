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
  Viewer,
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';
import type { Stats } from '../../lib/types';

const severityColor = (sev: string | undefined) => {
  if (sev === 'high') return '#ff2d00';
  if (sev === 'medium') return '#ff6b35';
  return '#ffd23f';
};

export function useAcledLayer({
  viewer,
  active,
  feedActive,
  canFetch,
  setStats,
}: {
  viewer: Viewer | null;
  active: boolean;
  feedActive: boolean;
  canFetch: boolean;
  setStats: React.Dispatch<React.SetStateAction<Stats>>;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);

  const { data } = useQuery({
    queryKey: ['acled'],
    queryFn: async () => {
      const r = await fetchApi('/api/acled/events?limit=100&days=7');
      return r.json();
    },
    refetchInterval: 3600000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('acled');
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

    for (const ev of data.events || []) {
      if (ev.lon == null || ev.lat == null) continue;
      const col = Color.fromCssColorString(severityColor(ev.severity));
      src.entities.add({
        position: Cartesian3.fromDegrees(ev.lon, ev.lat, 0),
        point: {
          pixelSize: ev.severity === 'high' ? 14 : 10,
          color: col.withAlpha(0.9),
          outlineColor: Color.BLACK,
          outlineWidth: 1,
        },
        label: {
          text: `${ev.event_type || '?'}`,
          font: '600 9px "Courier New"',
          fillColor: col,
          outlineColor: Color.BLACK,
          outlineWidth: 2,
          style: LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: VerticalOrigin.BOTTOM,
          pixelOffset: new Cartesian2(0, -10),
          distanceDisplayCondition: new DistanceDisplayCondition(0, 5e6),
        },
        properties: {
          kind: 'acled',
          event_type: ev.event_type,
          sub_event_type: ev.sub_event_type,
          country: ev.country,
          date: ev.date,
          fatalities: ev.fatalities,
          severity: ev.severity,
        },
      });
    }
    src.entities.resumeEvents();
    setStats((p: Stats) => ({ ...p, acled: (data?.events || []).length }));
  }, [viewer, data, active, setStats]);
}
