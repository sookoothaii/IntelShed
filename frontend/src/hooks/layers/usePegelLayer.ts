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
import type { Stats, FeedHud, PegelGauge } from '../../lib/types';

const pegelColor = (sev?: string) => {
  if (sev === 'critical') return '#ff2d00';
  if (sev === 'high') return '#ff6b35';
  if (sev === 'low') return '#88aaff';
  return '#4fc3f7';
};

export function usePegelLayer({
  viewer,
  active,
  feedActive,
  canFetch,
  setStats,
  setFeedHud,
}: {
  viewer: Viewer | null;
  active: boolean;
  feedActive: boolean;
  canFetch: boolean;
  setStats: React.Dispatch<React.SetStateAction<Stats>>;
  setFeedHud: React.Dispatch<React.SetStateAction<FeedHud>>;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);

  const { data } = useQuery({
    queryKey: ['pegel'],
    queryFn: async () => {
      const r = await fetchApi('/api/pegel');
      return r.json();
    },
    refetchInterval: 300000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('pegel');
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

    for (const g of (data.gauges || []) as PegelGauge[]) {
      if (g.lon == null || g.lat == null) continue;
      const col = Color.fromCssColorString(pegelColor(g.severity));
      src.entities.add({
        position: Cartesian3.fromDegrees(g.lon, g.lat, 0),
        point: {
          pixelSize: g.severity === 'critical' || g.severity === 'high' ? 14 : 10,
          color: col.withAlpha(0.95),
          outlineColor: Color.BLACK,
          outlineWidth: 1,
        },
        label: {
          text: `${g.name}`,
          font: '600 9px "Courier New"',
          fillColor: col,
          outlineColor: Color.BLACK,
          outlineWidth: 2,
          style: LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: VerticalOrigin.BOTTOM,
          pixelOffset: new Cartesian2(0, -12),
          distanceDisplayCondition: new DistanceDisplayCondition(0, 1.5e7),
        },
        properties: {
          kind: 'pegel',
          uuid: g.uuid,
          name: g.name,
          water: g.water,
          value: g.value,
          unit: g.unit,
          severity: g.severity,
          state_mnw_mhw: g.state_mnw_mhw,
          state_nsw_hsw: g.state_nsw_hsw,
          timestamp: g.timestamp,
        },
      });
    }

    src.entities.resumeEvents();

    setStats((p: Stats) => ({ ...p, pegel: data.count ?? (data.gauges || []).length }));
    setFeedHud((p: FeedHud) => ({ ...p, pegel: data.error ? 'err' : data.source ? 'pegel' : '' }));
  }, [viewer, data, active, setStats, setFeedHud]);
}
