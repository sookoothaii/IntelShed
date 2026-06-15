import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Entity,
  Cartesian3,
  ConstantPositionProperty,
  Color,
  NearFarScalar,
  LabelStyle,
  VerticalOrigin,
  HorizontalOrigin,
  Cartesian2,
  DistanceDisplayCondition,
  CallbackProperty,
  ColorMaterialProperty,
  Viewer
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';

export function useMilitaryLayer({
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
  const milMapRef = useRef(new Map<string, Entity>());

  const { data } = useQuery({
    queryKey: ['military'],
    queryFn: async () => {
      const r = await fetchApi('/api/military');
      return r.json();
    },
    refetchInterval: 15000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('military');
    attachDataSource(viewer, src);
    srcRef.current = src;
    
    return () => {
      detachDataSource(viewer, src);
      srcRef.current = null;
      milMapRef.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    if (!srcRef.current) return;
    srcRef.current.show = active;
  }, [active]);

  useEffect(() => {
    if (!data || !srcRef.current || !active) return;
    const src = srcRef.current;
    const milMap = milMapRef.current;
    const list: any[] = data.aircraft || [];
    const seen = new Set<string>();

    src.entities.suspendEvents();
    
    for (const a of list) {
      if (a.lon == null || a.lat == null) continue;
      const id = a.hex;
      seen.add(id);
      const pos = Cartesian3.fromDegrees(a.lon, a.lat, Math.max(a.alt ?? 0, 0));
      
      let e = milMap.get(id);
      if (e) {
        (e.position as ConstantPositionProperty).setValue(pos);
      } else {
        const isEmergency = ['7500', '7600', '7700'].includes(a.squawk || '');
        e = src.entities.add({
          id: 'mil-' + id,
          position: new ConstantPositionProperty(pos),
          point: {
            pixelSize: isEmergency ? 12 : 8,
            color: isEmergency ? Color.fromCssColorString('#ff2d00') : Color.fromCssColorString('#ff6b35'),
            outlineColor: Color.BLACK,
            outlineWidth: 2,
            scaleByDistance: new NearFarScalar(1e5, 1.8, 1e7, 0.5),
          },
          label: {
            text: a.flight || a.hex,
            font: '600 11px "Courier New"',
            fillColor: isEmergency ? Color.fromCssColorString('#ff2d00') : Color.fromCssColorString('#ff9f7a'),
            outlineColor: Color.BLACK,
            outlineWidth: 2,
            style: LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: VerticalOrigin.BOTTOM,
            horizontalOrigin: HorizontalOrigin.LEFT,
            pixelOffset: new Cartesian2(8, -4),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 1.2e6),
          },
          properties: {
            kind: 'military', hex: a.hex, flight: a.flight || '', type: a.type || '',
            alt: a.alt ?? 0, speed: a.speed ?? 0, squawk: a.squawk || '',
          } as any,
        });
        
        if (isEmergency) {
          const t0 = Date.now();
          (e as any).ellipse = {
            semiMajorAxis: new CallbackProperty(() => {
              const ph = ((Date.now() - t0) % 1200) / 1200;
              return 20000 + ph * 80000;
            }, false),
            semiMinorAxis: new CallbackProperty(() => {
              const ph = ((Date.now() - t0) % 1200) / 1200;
              return (20000 + ph * 80000) * 0.97;
            }, false),
            material: new ColorMaterialProperty(
              new CallbackProperty(() => {
                const ph = ((Date.now() - t0) % 1200) / 1200;
                return Color.fromCssColorString('#ff2d00').withAlpha(0.5 * (1 - ph));
              }, false)
            ),
            height: 0,
          };
        }
        milMap.set(id, e);
      }
    }
    
    for (const [id, e] of milMap) {
      if (!seen.has(id)) {
        src.entities.remove(e);
        milMap.delete(id);
      }
    }
    
    src.entities.resumeEvents();
    setStats((p: any) => ({ ...p, military: milMap.size }));
  }, [viewer, data, active, setStats]);
}
