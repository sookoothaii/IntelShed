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
import type { Stats } from '../../lib/types';

type TrafficCam = {
  id: string;
  name: string;
  lat: number;
  lon: number;
  image_url?: string;
  stream_url?: string;
  source?: string;
  country?: string;
  refresh_ms?: number;
};

export function useTrafficCamsLayer({
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
  const camMapRef = useRef(new Map<string, Entity>());

  const { data } = useQuery({
    queryKey: ['traffic-cams', 'regional'],
    queryFn: async () => {
      const r = await fetchApi('/api/traffic/cams?scope=regional');
      return r.json();
    },
    refetchInterval: 120_000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('traffic-cams');
    attachDataSource(viewer, src);
    srcRef.current = src;
    return () => {
      detachDataSource(viewer, src);
      srcRef.current = null;
      camMapRef.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    const src = srcRef.current;
    if (!src || !data?.cameras) return;

    const cams: TrafficCam[] = data.cameras;
    const seen = new Set<string>();

    for (const cam of cams) {
      if (cam.lat == null || cam.lon == null) continue;
      seen.add(cam.id);
      let ent = camMapRef.current.get(cam.id);
      const pos = Cartesian3.fromDegrees(cam.lon, cam.lat, 80);
      const label = cam.name || cam.id;

      const props = {
        kind: 'traffic_cam',
        cam_id: cam.id,
        name: label,
        lat: cam.lat,
        lon: cam.lon,
        image_url: cam.image_url || cam.stream_url || '',
        source: cam.source || 'traffic',
        country: cam.country || '',
        refresh_ms: cam.refresh_ms ?? 120_000,
      };

      if (!ent) {
        ent = src.entities.add({
          id: cam.id,
          name: label,
          position: pos,
          properties: props,
          point: {
            pixelSize: 12,
            color: Color.fromCssColorString('#ff6b00'),
            outlineColor: Color.BLACK,
            outlineWidth: 2,
            scaleByDistance: new NearFarScalar(5e4, 1.4, 8e6, 0.45),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 1.2e7),
          },
          label: {
            text: 'TRAFFIC',
            font: '700 9px JetBrains Mono, monospace',
            fillColor: Color.fromCssColorString('#ffcc80'),
            outlineColor: Color.BLACK,
            outlineWidth: 2,
            style: LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: VerticalOrigin.BOTTOM,
            horizontalOrigin: HorizontalOrigin.CENTER,
            pixelOffset: new Cartesian2(0, -14),
            scaleByDistance: new NearFarScalar(2e5, 1, 8e6, 0),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 8e6),
            show: true,
          },
        });
        camMapRef.current.set(cam.id, ent);
      } else {
        ent.position = new ConstantPositionProperty(pos);
        ent.properties = props as unknown as Entity['properties'];
        ent.name = label;
      }
    }

    for (const [id, ent] of camMapRef.current) {
      if (!seen.has(id)) {
        src.entities.remove(ent);
        camMapRef.current.delete(id);
      }
    }

    setStats((s: Stats) => ({ ...s, trafficCams: cams.length }));
  }, [data, setStats]);
}
