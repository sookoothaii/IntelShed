import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Cartesian3,
  Color,
  Entity,
  Viewer
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';
import type { Stats, FeedHud, LightningStrike } from '../../lib/types';

export function useLightningLayer({
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
  const lightningMapRef = useRef(new Map<string, { entity: Entity; ts: number }>());

  const { data } = useQuery({
    queryKey: ['lightning'],
    queryFn: async () => {
      const r = await fetchApi('/api/lightning');
      return r.json();
    },
    refetchInterval: 15000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('lightning');
    attachDataSource(viewer, src);
    srcRef.current = src;
    
    return () => {
      detachDataSource(viewer, src);
      srcRef.current = null;
      lightningMapRef.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    if (!srcRef.current) return;
    srcRef.current.show = active;
  }, [active]);

  useEffect(() => {
    if (!data || !srcRef.current || !active) return;
    const src = srcRef.current;
    const lightningMap = lightningMapRef.current;
    const strikes: LightningStrike[] = data.strikes || [];
    const now = Date.now();
    
    src.entities.suspendEvents();
    
    // Remove old strikes
    for (const [id, sd] of lightningMap) {
      if (now - sd.ts > 600000) {
        if (sd.entity) src.entities.remove(sd.entity);
        lightningMap.delete(id);
      }
    }
    
    for (const s of strikes) {
      if (s.lon == null || s.lat == null || !s.time) continue;
      const ts = new Date(s.time).getTime();
      if (now - ts > 600000) continue;
      const id = `${s.lat.toFixed(3)},${s.lon.toFixed(3)}`;
      if (lightningMap.has(id)) continue;
      
      const ageSec = (now - ts) / 1000;
      const alpha = Math.max(0.2, 1 - ageSec / 600);
      
      const e = src.entities.add({
        position: Cartesian3.fromDegrees(s.lon, s.lat, 0),
        point: {
          pixelSize: 10,
          color: Color.fromCssColorString('#22d3ee').withAlpha(alpha),
          outlineColor: Color.WHITE,
          outlineWidth: 1,
        },
        properties: {
          kind: 'lightning',
          time: s.time,
          stations: s.stations,
          participants: s.participants,
        },
      });
      lightningMap.set(id, { entity: e, ts });
    }
    
    src.entities.resumeEvents();
    
    if (data.error) {
      setStats((p: Stats) => ({ ...p, lightning: 0 }));
      setFeedHud((p: FeedHud) => ({ ...p, lightning: 'N/A' }));
    } else {
      setStats((p: Stats) => ({ ...p, lightning: lightningMap.size }));
      setFeedHud((p: FeedHud) => ({ ...p, lightning: '' }));
    }
  }, [viewer, data, active, setStats, setFeedHud]);
}
