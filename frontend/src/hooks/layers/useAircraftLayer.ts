import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Cartesian2,
  Cartesian3,
  Color,
  DistanceDisplayCondition,
  HorizontalOrigin,
  LabelCollection,
  LabelStyle,
  NearFarScalar,
  PointPrimitiveCollection,
  VerticalOrigin,
  Viewer,
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import type { GlobePrimitivePick } from '../../lib/globePick';
import type { Stats, AircraftState, AircraftApiResponse } from '../../lib/types';
import {
  attachPrimitiveCollection,
  detachPrimitiveCollection,
  requestSceneRender,
} from './layerUtils';

type AcEntry = {
  point: ReturnType<PointPrimitiveCollection['add']>;
  label: ReturnType<LabelCollection['add']>;
};

function acColor(onGround: boolean): Color {
  return onGround ? Color.GRAY : Color.fromCssColorString('#ffd23f');
}

export function useAircraftLayer({
  viewer,
  active,
  feedActive,
  canFetch,
  setStats,
  setAircraftSource,
}: {
  viewer: Viewer | null;
  active: boolean;
  feedActive: boolean;
  canFetch: boolean;
  setStats: React.Dispatch<React.SetStateAction<Stats>>;
  setAircraftSource: React.Dispatch<React.SetStateAction<string>>;
}) {
  const pointsRef = useRef<PointPrimitiveCollection | null>(null);
  const labelsRef = useRef<LabelCollection | null>(null);
  const acMapRef = useRef(new Map<string, AcEntry>());

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
    const points = new PointPrimitiveCollection();
    const labels = new LabelCollection();
    attachPrimitiveCollection(viewer, points);
    attachPrimitiveCollection(viewer, labels);
    pointsRef.current = points;
    labelsRef.current = labels;

    return () => {
      detachPrimitiveCollection(viewer, points);
      detachPrimitiveCollection(viewer, labels);
      pointsRef.current = null;
      labelsRef.current = null;
      acMapRef.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    if (pointsRef.current) pointsRef.current.show = active;
    if (labelsRef.current) labelsRef.current.show = active;
  }, [active]);

  useEffect(() => {
    if (!isSuccess || !data || !pointsRef.current || !labelsRef.current || !viewer) return;
    const points = pointsRef.current;
    const labels = labelsRef.current;
    const acMap = acMapRef.current;
    const states: AircraftState[] = (data as AircraftApiResponse)?.states || [];
    const seen = new Set<string>();

    for (const s of states) {
      const lon = s[5];
      const lat = s[6];
      if (lon == null || lat == null) continue;
      const id = s[0];
      const alt = Math.max(s[7] ?? s[13] ?? 0, 0);
      const callsign = (s[1] || '').trim() || id;
      const onGround = !!s[8];
      seen.add(id);
      const pos = Cartesian3.fromDegrees(lon, lat, alt);
      const pickMeta: GlobePrimitivePick = {
        kind: 'aircraft',
        lon,
        lat,
        icao: id,
        callsign,
        country: s[2],
        alt,
        vel: s[9] ?? 0,
        heading: s[10] ?? 0,
      };

      let entry = acMap.get(id);
      if (entry) {
        entry.point.position = pos;
        entry.point.color = acColor(onGround);
        entry.label.position = pos;
        entry.label.text = callsign;
        entry.point.id = pickMeta;
        entry.label.id = pickMeta;
      } else {
        const point = points.add({
          position: pos,
          pixelSize: 7,
          color: acColor(onGround),
          outlineColor: Color.BLACK,
          outlineWidth: 1,
          scaleByDistance: new NearFarScalar(1e5, 1.6, 1e7, 0.5),
          id: pickMeta,
        });
        const label = labels.add({
          position: pos,
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
          id: pickMeta,
        });
        entry = { point, label };
        acMap.set(id, entry);
      }
    }

    for (const [id, entry] of acMap) {
      if (!seen.has(id)) {
        points.remove(entry.point);
        labels.remove(entry.label);
        acMap.delete(id);
      }
    }

    setStats((p: Stats) => ({ ...p, aircraft: acMap.size }));
    if ((data as AircraftApiResponse)?.source) setAircraftSource(String((data as AircraftApiResponse).source));
    requestSceneRender(viewer);
  }, [viewer, data, isSuccess, active, setStats, setAircraftSource]);
}
