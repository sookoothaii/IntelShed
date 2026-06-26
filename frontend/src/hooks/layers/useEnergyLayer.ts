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
import type { Stats, FeedHud } from '../../lib/types';

export function useEnergyLayer({
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
    queryKey: ['energy'],
    queryFn: async () => {
      const r = await fetchApi('/api/energy/de/globe');
      return r.json();
    },
    refetchInterval: 60000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('energy');
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
    
    const pulse = Date.now() / 1000;
    for (const p of data.points || []) {
      const col = Color.fromCssColorString(p.color || '#ffd23f');
      const rpx = p.radius || 12;
      const pulseScale = 1 + 0.15 * Math.sin(pulse * 2 + (p.lon || 0));
      
      src.entities.add({
        position: Cartesian3.fromDegrees(p.lon, p.lat, 0),
        point: {
          pixelSize: rpx * pulseScale,
          color: col.withAlpha(0.92),
          outlineColor: Color.WHITE.withAlpha(0.6),
          outlineWidth: 1,
        },
        label: {
          text: `${p.label}\n${p.mw} MW`,
          font: '600 9px "Courier New"',
          fillColor: col,
          outlineColor: Color.BLACK,
          outlineWidth: 2,
          style: LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: VerticalOrigin.BOTTOM,
          pixelOffset: new Cartesian2(0, -14),
          distanceDisplayCondition: new DistanceDisplayCondition(0, 2.5e6),
        },
        properties: {
          kind: 'energy',
          label: p.label,
          mw: p.mw,
          co2_factor: p.co2_factor,
          price: data.day_ahead_price_eur_mwh,
          load_mw: data.load_mw,
          co2_g_per_kwh: data.co2_g_per_kwh,
        },
      });
    }
    
    src.entities.resumeEvents();
    
    const activeSources = data.active_sources ?? (data.points || []).length;
    const genGw = data.total_generation_mw != null ? `${Math.round(data.total_generation_mw / 1000)}GW` : '';
    setStats((p: Stats) => ({ ...p, energy: activeSources || (data.total_generation_mw ? 1 : 0) }));
    setFeedHud((p: FeedHud) => ({
      ...p,
      energy: data.stale ? 'stale' : (genGw || (data.error ? 'err' : 'smard')),
    }));
  }, [viewer, data, active, setStats, setFeedHud]);
}
