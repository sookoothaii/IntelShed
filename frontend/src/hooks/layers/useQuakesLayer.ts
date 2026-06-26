import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Cartesian3,
  Color,
  CustomDataSource,
  NearFarScalar,
  PointPrimitiveCollection,
  Viewer,
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import type { GlobePrimitivePick } from '../../lib/globePick';
import type { Stats, Earthquake } from '../../lib/types';
import {
  attachDataSource,
  detachDataSource,
  feedPos,
  requestSceneRender,
  timelineCutoffMs,
  viewerAlive,
} from './layerUtils';
import { attachPulseEllipse, clearPulseCleanups } from './pulseAnimation';

function attachPointCollection(viewer: Viewer, collection: PointPrimitiveCollection): boolean {
  if (!viewerAlive(viewer)) return false;
  try {
    viewer.scene.primitives.add(collection);
    return true;
  } catch {
    return false;
  }
}

function detachPointCollection(viewer: Viewer | null, collection: PointPrimitiveCollection | null): void {
  if (!collection || !viewerAlive(viewer)) return;
  try {
    viewer.scene.primitives.remove(collection);
  } catch {
    /* viewer already destroyed */
  }
}

export function useQuakesLayer({
  viewer,
  active,
  feedActive,
  canFetch,
  setStats,
  scrubT,
  timelineHours,
}: {
  viewer: Viewer | null;
  active: boolean;
  feedActive: boolean;
  canFetch: boolean;
  setStats: React.Dispatch<React.SetStateAction<Stats>>;
  scrubT: number;
  timelineHours: number;
}) {
  const pointsRef = useRef<PointPrimitiveCollection | null>(null);
  const pulseSrcRef = useRef<CustomDataSource | null>(null);
  const pulseCleanupsRef = useRef<Array<() => void>>([]);

  const { data } = useQuery({
    queryKey: ['earthquakes'],
    queryFn: async () => {
      const r = await fetchApi('/api/earthquakes?period=day&magnitude=2.5');
      return r.json();
    },
    refetchInterval: 60000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const points = new PointPrimitiveCollection();
    attachPointCollection(viewer, points);
    pointsRef.current = points;

    const pulseSrc = new CustomDataSource('quakes-pulse');
    attachDataSource(viewer, pulseSrc);
    pulseSrcRef.current = pulseSrc;

    return () => {
      clearPulseCleanups(pulseCleanupsRef.current);
      detachPointCollection(viewer, points);
      pointsRef.current = null;
      detachDataSource(viewer, pulseSrc);
      pulseSrcRef.current = null;
    };
  }, [viewer]);

  useEffect(() => {
    if (pointsRef.current) pointsRef.current.show = active;
    if (pulseSrcRef.current) pulseSrcRef.current.show = active;
  }, [active]);

  useEffect(() => {
    if (!data || !pointsRef.current || !pulseSrcRef.current || !active || !viewer) return;
    const points = pointsRef.current;
    const pulseSrc = pulseSrcRef.current;

    const cutoff = timelineCutoffMs(scrubT, timelineHours);
    const list = (data.earthquakes || []).filter((q: Earthquake) => (q.time ?? 0) <= cutoff);

    clearPulseCleanups(pulseCleanupsRef.current);
    points.removeAll();
    pulseSrc.entities.suspendEvents();
    pulseSrc.entities.removeAll();

    for (const q of list) {
      if (q.lon == null || q.lat == null) continue;
      const mag = q.mag ?? 0;
      const sev = Math.min(mag / 8, 1);

      const pickMeta: GlobePrimitivePick = {
        kind: 'quake',
        lon: q.lon,
        lat: q.lat,
        place: q.place,
        mag,
        depth: q.depth,
        time: q.time,
      };

      points.add({
        position: Cartesian3.fromDegrees(q.lon, q.lat, 0),
        pixelSize: 4 + mag * 2.5,
        color: Color.fromHsl(0.02 + 0.08 * (1 - sev), 1.0, 0.5, 0.9),
        outlineColor: Color.BLACK,
        outlineWidth: 1,
        scaleByDistance: new NearFarScalar(1e5, 1.6, 1e7, 0.5),
        id: pickMeta,
      });

      if (mag >= 5) {
        const ent = pulseSrc.entities.add({
          position: feedPos(q.lon, q.lat),
          properties: {
            kind: 'quake',
            place: q.place,
            mag,
            depth: q.depth,
            time: q.time,
          },
        });
        pulseCleanupsRef.current.push(
          attachPulseEllipse(ent, {
            baseRadius: 30000,
            pulseScale: mag * 90000,
            color: Color.fromCssColorString('#ff3b30'),
            alphaScale: 0.4,
            minorScale: 0.95,
          }),
        );
      }
    }

    pulseSrc.entities.resumeEvents();
    requestSceneRender(viewer);
    setStats((p: Stats) => ({ ...p, quakes: list.length }));
  }, [viewer, data, active, scrubT, timelineHours, setStats]);
}
