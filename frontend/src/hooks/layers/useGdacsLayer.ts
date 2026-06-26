import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Color,
  Viewer
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';
import { feedPos, feedPoint } from './layerUtils';
import type { Stats, FeedHud } from '../../lib/types';

const gdacsTypeColor = (title: string) => {
  const t = (title || '').toLowerCase();
  if (t.includes('earthquake')) return '#ff6b35';
  if (t.includes('flood')) return '#22d3ee';
  if (t.includes('cyclone') || t.includes('typhoon') || t.includes('hurricane')) return '#ffd23f';
  if (t.includes('tsunami')) return '#ff2d00';
  if (t.includes('volcano')) return '#ff4d5e';
  return '#ff6b35';
};

export function useGdacsLayer({
  viewer,
  active,
  feedActive,
  canFetch,
  setStats,
  setFeedHud
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
    queryKey: ['gdacs'],
    queryFn: async () => {
      const r = await fetchApi('/api/gdacs');
      return r.json();
    },
    refetchInterval: 300000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('gdacs');
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
    for (const a of data.alerts || []) {
      if (a.lon == null || a.lat == null) continue;
      const col = Color.fromCssColorString(gdacsTypeColor(a.title));
      src.entities.add({
        position: feedPos(a.lon, a.lat),
        point: feedPoint(11, col.withAlpha(0.95), { outlineWidth: 1 }),
        properties: {
          kind: 'gdacs',
          title: a.title,
          description: (a.description || '').slice(0, 200),
          published: a.published,
          link: a.link,
        },
      });
      n++;
    }
    
    src.entities.resumeEvents();
    
    const total = data.count ?? (data.alerts || []).length;
    setStats((p: Stats) => ({ ...p, gdacs: total }));
    setFeedHud((p: FeedHud) => ({
      ...p,
      gdacs: n < total ? `${n} map` : (data.source ? String(data.source).replace('.org', '') : ''),
    }));
  }, [viewer, data, active, setStats, setFeedHud]);
}
