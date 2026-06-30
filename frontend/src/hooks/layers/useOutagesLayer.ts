import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { CustomDataSource, Cartesian3, Color, Viewer } from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';
import type { Stats, FeedHud, OutageItem } from '../../lib/types';

export function useOutagesLayer({
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
    queryKey: ['outages'],
    queryFn: async () => {
      const r = await fetchApi('/api/outages?hours=72&limit=35');
      return r.json();
    },
    refetchInterval: 300000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('outages');
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

    for (const o of (data.items || []) as OutageItem[]) {
      if (o.lon == null || o.lat == null) continue;
      const col = Color.fromCssColorString(o.source === 'cloudflare' ? '#ff9f43' : '#a855f7');
      src.entities.add({
        position: Cartesian3.fromDegrees(o.lon, o.lat, 0),
        point: {
          pixelSize: o.kind === 'event' ? 12 : 9,
          color: col.withAlpha(0.9),
          outlineColor: Color.WHITE,
          outlineWidth: 1,
        },
        properties: {
          kind: 'outage',
          title: o.title,
          source: o.source,
          level: o.level,
          duration_h: o.duration_h,
          datasource: o.datasource,
        },
      });
    }

    src.entities.resumeEvents();

    const total = data.count ?? (data.items || []).length;
    setStats((p: Stats) => ({ ...p, outages: total }));
    const srcLabel = (data.sources || []).join('+') || 'ioda';
    const mapNote =
      data.geocoded != null && data.geocoded < total ? `${data.geocoded} map` : srcLabel;
    setFeedHud((p: FeedHud) => ({ ...p, outages: mapNote }));
  }, [viewer, data, active, setStats, setFeedHud]);
}
