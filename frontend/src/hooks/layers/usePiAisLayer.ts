import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Entity,
  Cartesian3,
  ConstantPositionProperty,
  ConstantProperty,
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
import { attachDataSource, detachDataSource, requestSceneRender } from './layerUtils';
import type { Stats } from '../../lib/types';

interface EdgeVessel {
  mmsi: string;
  name?: string;
  lat: number;
  lon: number;
  course?: number;
  speed?: number;
  source?: string;
}

interface EdgeStatus {
  status: {
    active: boolean;
    receiver_type: string;
    messages_received: number;
    vessels_seen: number;
    last_message_at: string;
    lat: number | null;
    lon: number | null;
    range_km: number;
  };
  vessels: EdgeVessel[];
  count: number;
}

export function usePiAisLayer({
  viewer,
  active,
  feedActive,
  canFetch,
  setStats,
}: {
  viewer: Viewer | null;
  active: boolean;
  feedActive: boolean;
  canFetch: boolean;
  setStats: React.Dispatch<React.SetStateAction<Stats>>;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);
  const vesselMapRef = useRef(new Map<string, Entity>());
  const coverageEntityRef = useRef<Entity | null>(null);

  const { data } = useQuery({
    queryKey: ['pi-ais-edge'],
    queryFn: async () => {
      const r = await fetchApi('/api/maritime/edge');
      return r.json() as Promise<EdgeStatus>;
    },
    refetchInterval: 30000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('piAis');
    attachDataSource(viewer, src);
    srcRef.current = src;

    return () => {
      detachDataSource(viewer, src);
      srcRef.current = null;
      vesselMapRef.current.clear();
      coverageEntityRef.current = null;
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
    const seen = new Set<string>();

    src.entities.suspendEvents();

    // Coverage circle at receiver location
    const rxLat = data.status?.lat;
    const rxLon = data.status?.lon;
    const rangeKm = data.status?.range_km ?? 25;
    const isActive = data.status?.active ?? false;

    if (rxLat != null && rxLon != null) {
      const covId = 'pi-ais-coverage';
      seen.add(covId);
      const pos = Cartesian3.fromDegrees(rxLon, rxLat, 0);
      const radiusM = rangeKm * 1000;

      let cov = coverageEntityRef.current;
      if (cov) {
        (cov.position as ConstantPositionProperty).setValue(pos);
        if (cov.ellipse) {
          cov.ellipse.semiMajorAxis = new ConstantProperty(radiusM);
          cov.ellipse.semiMinorAxis = new ConstantProperty(radiusM);
        }
      } else {
        cov = src.entities.add({
          id: covId,
          position: new ConstantPositionProperty(pos),
          ellipse: {
            semiMajorAxis: radiusM,
            semiMinorAxis: radiusM,
            material: Color.fromCssColorString('#00e5ff').withAlpha(0.08),
            outline: true,
            outlineColor: Color.fromCssColorString('#00e5ff').withAlpha(isActive ? 0.6 : 0.25),
            outlineWidth: 2,
          },
        });
        coverageEntityRef.current = cov;
      }
    }

    // Edge vessel positions
    const vessels = data.vessels || [];
    for (const v of vessels) {
      if (v.lat == null || v.lon == null) continue;
      const id = `pi-ais-${v.mmsi}`;
      seen.add(id);
      const pos = Cartesian3.fromDegrees(v.lon, v.lat, 0);

      let e = vesselMap.get(id);
      if (e) {
        (e.position as ConstantPositionProperty).setValue(pos);
      } else {
        e = src.entities.add({
          id,
          position: new ConstantPositionProperty(pos),
          point: {
            pixelSize: 8,
            color: Color.fromCssColorString('#00e5ff'),
            outlineColor: Color.BLACK,
            outlineWidth: 1,
            scaleByDistance: new NearFarScalar(1e4, 1.5, 1e7, 0.5),
          },
          label: {
            text: v.name || v.mmsi,
            font: '500 10px "Courier New"',
            fillColor: Color.fromCssColorString('#00e5ff'),
            outlineColor: Color.BLACK,
            outlineWidth: 1,
            style: LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: VerticalOrigin.BOTTOM,
            horizontalOrigin: HorizontalOrigin.CENTER,
            pixelOffset: new Cartesian2(0, -8),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 1e6),
          },
          properties: {
            kind: 'pi_ais_vessel',
            mmsi: v.mmsi,
            name: v.name || v.mmsi,
            source: 'pi_edge',
          },
        });
        vesselMap.set(id, e);
      }
    }

    // Cleanup removed entities
    for (const [id, e] of vesselMap) {
      if (!seen.has(id)) {
        src.entities.remove(e);
        vesselMap.delete(id);
      }
    }

    src.entities.resumeEvents();
    setStats((p: Stats) => ({ ...p, piAis: vessels.length }));
    requestSceneRender(viewer);
  }, [viewer, data, active, setStats]);
}
