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
  Viewer
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';

export function useAircraftLayer({
  viewer,
  active,
  feedActive,
  canFetch,
  setStats,
  setAircraftSource
}: {
  viewer: Viewer | null;
  active: boolean;
  feedActive: boolean;
  canFetch: boolean;
  setStats: React.Dispatch<React.SetStateAction<any>>;
  setAircraftSource: React.Dispatch<React.SetStateAction<string>>;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);
  const acMapRef = useRef(new Map<string, Entity>());

  const { data, isSuccess } = useQuery({
    queryKey: ['aircraft'],
    queryFn: async () => {
      const r = await fetchApi('/api/aircraft');
      return r.json();
    },
    refetchInterval: 45000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('aircraft');
    if (!attachDataSource(viewer, src)) return;
    srcRef.current = src;
    
    // Hide or show based on active state without unmounting the source
    src.show = active;
    
    return () => {
      detachDataSource(viewer, src);
      srcRef.current = null;
      acMapRef.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    if (!srcRef.current) return;
    srcRef.current.show = active;
  }, [active]);

  useEffect(() => {
    if (!isSuccess || !data || !srcRef.current) return;
    const src = srcRef.current;
    const acMap = acMapRef.current;
    const states: any[] = data.states || [];
    const seen = new Set<string>();

    src.entities.suspendEvents();
    for (const s of states) {
      const lon = s[5], lat = s[6];
      if (lon == null || lat == null) continue;
      const id = s[0];
      const alt = Math.max(s[7] ?? s[13] ?? 0, 0);
      const callsign = (s[1] || '').trim() || id;
      seen.add(id);
      const pos = Cartesian3.fromDegrees(lon, lat, alt);
      
      let e = acMap.get(id);
      if (e) {
        (e.position as ConstantPositionProperty).setValue(pos);
      } else {
        e = src.entities.add({
          id: 'ac-' + id,
          position: new ConstantPositionProperty(pos),
          point: {
            pixelSize: 7,
            color: s[8] ? Color.GRAY : Color.fromCssColorString('#ffd23f'),
            outlineColor: Color.BLACK,
            outlineWidth: 1,
            scaleByDistance: new NearFarScalar(1e5, 1.6, 1e7, 0.5),
          },
          label: {
            text: callsign,
            font: '600 11px "Courier New"',
            fillColor: Color.fromCssColorString('#ffe98a'),
            outlineColor: Color.BLACK,
            outlineWidth: 2,
            style: LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: VerticalOrigin.BOTTOM,
            horizontalOrigin: HorizontalOrigin.LEFT,
            pixelOffset: new Cartesian2(8, -4),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 1.2e6),
          },
          properties: {
            kind: 'aircraft', icao: id, callsign,
            country: s[2], alt, vel: s[9] ?? 0, heading: s[10] ?? 0,
          } as any,
        });
        acMap.set(id, e);
      }
    }
    for (const [id, e] of acMap) {
      if (!seen.has(id)) {
        src.entities.remove(e);
        acMap.delete(id);
      }
    }
    src.entities.resumeEvents();

    setStats((p: any) => ({ ...p, aircraft: acMap.size }));
    if (data.source) setAircraftSource(String(data.source));
  }, [viewer, data, isSuccess, active, setStats, setAircraftSource]);
}
