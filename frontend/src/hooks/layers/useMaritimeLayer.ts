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

export function useMaritimeLayer({
  viewer,
  active,
  feedActive,
  canFetch,
  setStats,
  setSanctionedMmsi
}: {
  viewer: Viewer | null;
  active: boolean;
  feedActive: boolean;
  canFetch: boolean;
  setStats: React.Dispatch<React.SetStateAction<any>>;
  setSanctionedMmsi?: React.Dispatch<React.SetStateAction<Set<string>>>;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);
  const vesselMapRef = useRef(new Map<string, Entity>());

  const { data: sanctionsData } = useQuery({
    queryKey: ['sanctions'],
    queryFn: async () => {
      const r = await fetchApi('/api/sanctions/screen/vessels?min_score=0.85&limit=400');
      if (!r.ok) return new Set<string>();
      const d = await r.json();
      const mmsi = new Set<string>();
      for (const m of d.matches || []) {
        if (m?.vessel?.mmsi) mmsi.add(String(m.vessel.mmsi));
      }
      return mmsi;
    },
    refetchInterval: 180000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (sanctionsData && setSanctionedMmsi) {
      setSanctionedMmsi(sanctionsData);
    }
  }, [sanctionsData, setSanctionedMmsi]);

  const { data } = useQuery({
    queryKey: ['maritime'],
    queryFn: async () => {
      const r = await fetchApi('/api/maritime');
      return r.json();
    },
    refetchInterval: 45000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('maritime');
    attachDataSource(viewer, src);
    srcRef.current = src;
    
    return () => {
      detachDataSource(viewer, src);
      srcRef.current = null;
      vesselMapRef.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    if (!srcRef.current) return;
    srcRef.current.show = active;
  }, [active]);

  useEffect(() => {
    if (!data || !srcRef.current || !active) return;
    const src = srcRef.current;
    const vesselMap = vesselMapRef.current;
    
    if (data.error) {
      for (const [id, e] of vesselMap) {
        src.entities.remove(e);
        vesselMap.delete(id);
      }
      setStats((p: any) => ({ ...p, maritime: 0 }));
      return;
    }
    
    const vessels: any[] = data.vessels || [];
    const seen = new Set<string>();
    const sanctioned = sanctionsData || new Set<string>();

    src.entities.suspendEvents();
    
    for (const v of vessels) {
      if (v.lon == null || v.lat == null) continue;
      const id = v.mmsi || `${v.lat},${v.lon}`;
      seen.add(id);
      const pos = Cartesian3.fromDegrees(v.lon, v.lat, 0);
      
      let e = vesselMap.get(id);
      if (e) {
        (e.position as ConstantPositionProperty).setValue(pos);
      } else {
        const flagged = sanctioned.has(String(v.mmsi || ''));
        const typeColor = flagged
          ? '#ff2d00'
          : (v.type === 'Cargo' ? '#8B4513' : v.type === 'Tanker' ? '#000080' : v.type === 'Passenger' ? '#FF69B4' : v.type === 'Fishing' ? '#32CD32' : '#00e5ff');
          
        e = src.entities.add({
          id: 'vs-' + id,
          position: new ConstantPositionProperty(pos),
          point: {
            pixelSize: flagged ? 13 : 10,
            color: Color.fromCssColorString(typeColor).withAlpha(0.95),
            outlineColor: flagged ? Color.fromCssColorString('#ffd23f') : Color.WHITE,
            outlineWidth: flagged ? 2 : 1,
            scaleByDistance: new NearFarScalar(1e5, 1.8, 1e7, 0.5),
          },
          label: {
            text: `${flagged ? '⚠ ' : ''}${(v.name?.substring(0, 12) || v.type || 'Vessel')}`,
            font: '600 9px "Courier New"',
            fillColor: Color.fromCssColorString(typeColor),
            outlineColor: Color.BLACK,
            outlineWidth: 2,
            style: LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: VerticalOrigin.BOTTOM,
            horizontalOrigin: HorizontalOrigin.CENTER,
            pixelOffset: new Cartesian2(0, -10),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 2e6),
          },
          properties: {
            kind: 'maritime',
            name: v.name,
            mmsi: v.mmsi,
            type: v.type,
            course: v.course,
            speed: v.speed,
            destination: v.destination,
            flag: v.flag,
            length: v.length,
            sanctioned: flagged,
          } as any,
        });
        vesselMap.set(id, e);
      }
    }
    
    for (const [id, e] of vesselMap) {
      if (!seen.has(id)) {
        src.entities.remove(e);
        vesselMap.delete(id);
      }
    }
    
    src.entities.resumeEvents();
    setStats((p: any) => ({ ...p, maritime: vesselMap.size }));
  }, [viewer, data, sanctionsData, active, setStats]);
}
