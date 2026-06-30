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
  Viewer,
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';
import type { Stats, TransitVehicle } from '../../lib/types';

export function useTransitLayer({
  viewer,
  active,
  feedActive,
  canFetch,
  transitCity,
  setStats,
}: {
  viewer: Viewer | null;
  active: boolean;
  feedActive: boolean;
  canFetch: boolean;
  transitCity: string;
  setStats: React.Dispatch<React.SetStateAction<Stats>>;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);
  const transitMapRef = useRef(new Map<string, Entity>());

  const { data } = useQuery({
    queryKey: ['transit', transitCity],
    queryFn: async () => {
      const r = await fetchApi(`/api/transit/${transitCity}`);
      return r.json();
    },
    refetchInterval: 45000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('transit');
    attachDataSource(viewer, src);
    srcRef.current = src;

    return () => {
      detachDataSource(viewer, src);
      srcRef.current = null;
      transitMapRef.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    if (!srcRef.current) return;
    srcRef.current.show = active;
  }, [active]);

  useEffect(() => {
    if (!data || !srcRef.current || !active) return;
    const src = srcRef.current;
    const transitMap = transitMapRef.current;

    if (data.error) {
      for (const [id, e] of transitMap) {
        src.entities.remove(e);
        transitMap.delete(id);
      }
      setStats((p: Stats) => ({ ...p, transit: 0 }));
      return;
    }

    const vehicles: TransitVehicle[] = data.vehicles || [];
    const seen = new Set<string>();

    src.entities.suspendEvents();

    for (const v of vehicles) {
      if (v.lon == null || v.lat == null) continue;
      const id = v.id || `${v.lat},${v.lon}`;
      seen.add(id);
      const pos = Cartesian3.fromDegrees(v.lon, v.lat, 0);

      let e = transitMap.get(id);
      if (e) {
        (e.position as ConstantPositionProperty).setValue(pos);
      } else {
        e = src.entities.add({
          id: 'tr-' + id,
          position: new ConstantPositionProperty(pos),
          point: {
            pixelSize: 9,
            color: Color.fromCssColorString('#ffd23f').withAlpha(0.9),
            outlineColor: Color.BLACK,
            outlineWidth: 1,
            scaleByDistance: new NearFarScalar(1e5, 1.8, 1e7, 0.5),
          },
          label: {
            text: v.route_id || 'BUS',
            font: '600 9px "Courier New"',
            fillColor: Color.fromCssColorString('#ffd23f'),
            outlineColor: Color.BLACK,
            outlineWidth: 2,
            style: LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: VerticalOrigin.BOTTOM,
            horizontalOrigin: HorizontalOrigin.CENTER,
            pixelOffset: new Cartesian2(0, -8),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 1.5e6),
          },
          properties: {
            kind: 'transit',
            id: v.id,
            route_id: v.route_id,
            bearing: v.bearing,
            speed: v.speed,
            label: v.label,
          },
        });
        transitMap.set(id, e);
      }
    }

    for (const [id, e] of transitMap) {
      if (!seen.has(id)) {
        src.entities.remove(e);
        transitMap.delete(id);
      }
    }

    src.entities.resumeEvents();
    setStats((p: Stats) => ({ ...p, transit: transitMap.size }));
  }, [viewer, data, active, setStats]);
}
