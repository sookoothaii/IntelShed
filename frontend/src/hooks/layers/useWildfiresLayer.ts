import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Color,
  LabelStyle,
  VerticalOrigin,
  Cartesian2,
  DistanceDisplayCondition,
  NearFarScalar,
  Viewer
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';
import { feedPos, feedPoint } from './layerUtils';

export function useWildfiresLayer({
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
  setStats: React.Dispatch<React.SetStateAction<any>>;
  setFeedHud: React.Dispatch<React.SetStateAction<any>>;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);

  const { data } = useQuery({
    queryKey: ['wildfires'],
    queryFn: async () => {
      const r = await fetchApi('/api/wildfires');
      return r.json();
    },
    refetchInterval: 600000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('wildfires');
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
    const fires: any[] = data.fires || [];
    
    src.entities.suspendEvents();
    src.entities.removeAll();
    
    for (const f of fires) {
      if (f.lon == null || f.lat == null) continue;
      const conf = f.confidence ?? 0;
      const isRegional = f.zone === 'regional';
      const color = isRegional
        ? (conf >= 80 ? '#ff2d00' : conf >= 50 ? '#ff6b35' : '#ffd23f')
        : (conf >= 80 ? '#ff8c42' : conf >= 50 ? '#ffb347' : '#ffd23f');
      
      src.entities.add({
        position: feedPos(f.lon, f.lat),
        point: feedPoint(conf >= 80 ? 10 : conf >= 50 ? 8 : 6, Color.fromCssColorString(color).withAlpha(0.9), {
          outlineWidth: 1,
          scaleByDistance: new NearFarScalar(1e5, 1.8, 1e7, 0.6),
        }),
        label: {
          text: isRegional ? `ASEAN ${f.confidence ?? '?'}%` : `${f.confidence_label || 'fire'} ${f.confidence ?? '?'}%`,
          font: '600 9px "Courier New"',
          fillColor: Color.fromCssColorString(color),
          outlineColor: Color.BLACK,
          outlineWidth: 2,
          style: LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: VerticalOrigin.BOTTOM,
          pixelOffset: new Cartesian2(0, -8),
          distanceDisplayCondition: new DistanceDisplayCondition(0, 2e6),
        },
        properties: {
          kind: 'wildfire',
          confidence: f.confidence,
          confidence_label: f.confidence_label,
          brightness: f.brightness,
          frp: f.frp,
          satellite: f.satellite,
          zone: f.zone,
          acq_date: f.acq_date,
        } as any,
      });
    }
    
    src.entities.resumeEvents();
    
    const mapped = fires.filter((f) => f.lon != null && f.lat != null).length;
    setStats((p: any) => ({ ...p, wildfires: data.count ?? mapped }));
    const source = data.source === 'eonet_fallback' ? 'eonet' : (data.source || '');
    setFeedHud((p: any) => ({ ...p, wildfires: source || (data.errors ? 'degraded' : '') }));
  }, [viewer, data, active, setStats, setFeedHud]);
}
