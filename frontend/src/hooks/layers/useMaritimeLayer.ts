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
  type GeoJsonPrimitive,
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';
import {
  GEOJSON_PRIMITIVE_THRESHOLD,
  addGeoJsonPrimitive,
  removeGeoJsonPrimitive,
  pointsToGeoJson,
  type PointFeature,
} from './geoJsonPrimitive';
import type { Stats, MaritimeVessel } from '../../lib/types';

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
  setStats: React.Dispatch<React.SetStateAction<Stats>>;
  setSanctionedMmsi?: React.Dispatch<React.SetStateAction<Set<string>>>;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);
  const primRef = useRef<GeoJsonPrimitive | null>(null);
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
      removeGeoJsonPrimitive(viewer, primRef.current);
      srcRef.current = null;
      primRef.current = null;
      vesselMapRef.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    if (srcRef.current) srcRef.current.show = active;
    if (primRef.current) {
      if (primRef.current.points) primRef.current.points.show = active;
      if (primRef.current.polylines) primRef.current.polylines.show = active;
      if (primRef.current.polygons) primRef.current.polygons.show = active;
    }
  }, [active]);

  useEffect(() => {
    if (!data || !viewer || !active) return;
    const src = srcRef.current;
    const vesselMap = vesselMapRef.current;

    if (data.error) {
      for (const [id, e] of vesselMap) {
        src?.entities.remove(e);
        vesselMap.delete(id);
      }
      removeGeoJsonPrimitive(viewer, primRef.current);
      primRef.current = null;
      setStats((p: Stats) => ({ ...p, maritime: 0 }));
      return;
    }

    const vessels: MaritimeVessel[] = data.vessels || [];
    const valid = vessels.filter((v) => v.lon != null && v.lat != null);
    const sanctioned = sanctionsData || new Set<string>();
    const usePrimitive = valid.length > GEOJSON_PRIMITIVE_THRESHOLD;

    // Clear previous primitive if present or switching modes
    if (primRef.current) {
      removeGeoJsonPrimitive(viewer, primRef.current);
      primRef.current = null;
    }

    if (usePrimitive) {
      // --- GeoJsonPrimitive path (high-throughput, no labels) ---
      const features: PointFeature[] = valid.map((v) => {
        const flagged = sanctioned.has(String(v.mmsi || ''));
        return {
          lon: v.lon!,
          lat: v.lat!,
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
          },
        };
      });
      const gj = pointsToGeoJson(features);
      primRef.current = addGeoJsonPrimitive(
        viewer,
        gj,
        (props) => {
          const flagged = props.sanctioned as boolean;
          const vtype = props.type as string | undefined;
          const typeColor = flagged
            ? '#ff2d00'
            : (vtype === 'Cargo' ? '#8B4513' : vtype === 'Tanker' ? '#000080' : vtype === 'Passenger' ? '#FF69B4' : vtype === 'Fishing' ? '#32CD32' : '#00e5ff');
          return {
            color: Color.fromCssColorString(typeColor).withAlpha(0.95),
            outlineColor: flagged ? Color.fromCssColorString('#ffd23f') : Color.WHITE,
            outlineWidth: flagged ? 2 : 1,
            size: flagged ? 13 : 10,
          };
        },
        (_idx, props) => props,
      );
      // Hide DataSource when using primitive path
      if (src) src.show = false;
      // Clear entity-based vessel map
      for (const [, e] of vesselMap) src?.entities.remove(e);
      vesselMap.clear();
      setStats((p: Stats) => ({ ...p, maritime: valid.length }));
    } else {
      // --- DataSource path (incremental update with labels) ---
      if (src) src.show = true;
      if (!src) return;
      const seen = new Set<string>();

      src.entities.suspendEvents();

      for (const v of valid) {
        const id = v.mmsi || `${v.lat},${v.lon}`;
        seen.add(id);
        const pos = Cartesian3.fromDegrees(v.lon!, v.lat!, 0);

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
            },
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
      setStats((p: Stats) => ({ ...p, maritime: vesselMap.size }));
    }
  }, [viewer, data, sanctionsData, active, setStats]);
}
