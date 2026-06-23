import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Cartesian2,
  Cartesian3,
  Color,
  CustomDataSource,
  DistanceDisplayCondition,
  LabelCollection,
  LabelStyle,
  PointPrimitiveCollection,
  PolylineGlowMaterialProperty,
  VerticalOrigin,
  Viewer,
  Math as CMath,
} from 'cesium';
import * as satellite from 'satellite.js';
import { fetchApi } from '../../lib/networkFetch';
import type { GlobePrimitivePick } from '../../lib/globePick';
import {
  attachDataSource,
  attachPrimitiveCollection,
  detachDataSource,
  detachPrimitiveCollection,
  requestSceneRender,
} from './layerUtils';

type SatEntry = {
  point: ReturnType<PointPrimitiveCollection['add']>;
  label: ReturnType<LabelCollection['add']>;
};

export function useSatellitesLayer({
  viewer,
  active,
  orbitsActive,
  satGroup,
  feedActive,
  setStats,
}: {
  viewer: Viewer | null;
  active: boolean;
  orbitsActive: boolean;
  satGroup: string;
  feedActive: boolean;
  setStats: React.Dispatch<React.SetStateAction<any>>;
}) {
  const pointsRef = useRef<PointPrimitiveCollection | null>(null);
  const labelsRef = useRef<LabelCollection | null>(null);
  const orbitSrcRef = useRef<CustomDataSource | null>(null);
  const satMapRef = useRef(new Map<string, SatEntry>());

  const { data: satCache } = useQuery({
    queryKey: ['satellites', satGroup],
    queryFn: async () => {
      const r = await fetchApi(`/api/satellites?group=${satGroup}&limit=500`);
      const d = await r.json();
      const cache: { name: string; rec: any }[] = [];
      for (const s of d.satellites || []) {
        try {
          cache.push({ name: s.name, rec: satellite.twoline2satrec(s.tle1, s.tle2) });
        } catch {
          /* skip */
        }
      }
      satMapRef.current.clear();
      pointsRef.current?.removeAll();
      labelsRef.current?.removeAll();
      orbitSrcRef.current?.entities.removeAll();
      return cache;
    },
    enabled: active && feedActive,
    staleTime: 1000 * 60 * 60,
  });

  useEffect(() => {
    if (!viewer) return;
    const points = new PointPrimitiveCollection();
    const labels = new LabelCollection();
    attachPrimitiveCollection(viewer, points);
    attachPrimitiveCollection(viewer, labels);
    pointsRef.current = points;
    labelsRef.current = labels;

    const orbitSrc = new CustomDataSource('orbits');
    attachDataSource(viewer, orbitSrc);
    orbitSrcRef.current = orbitSrc;

    points.show = active;
    labels.show = active;
    orbitSrc.show = active && orbitsActive;

    return () => {
      detachPrimitiveCollection(viewer, points);
      detachPrimitiveCollection(viewer, labels);
      detachDataSource(viewer, orbitSrc);
      pointsRef.current = null;
      labelsRef.current = null;
      orbitSrcRef.current = null;
      satMapRef.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    if (pointsRef.current) pointsRef.current.show = active;
    if (labelsRef.current) labelsRef.current.show = active;
    if (orbitSrcRef.current) orbitSrcRef.current.show = active && orbitsActive;
  }, [active, orbitsActive]);

  const lastOrbitDrawMs = useRef(0);

  useEffect(() => {
    if (!active || !feedActive || !satCache || satCache.length === 0 || !pointsRef.current || !labelsRef.current || !orbitSrcRef.current || !viewer) {
      return;
    }

    let isCancelled = false;

    const propagateSats = (forceOrbits = false) => {
      if (isCancelled) return;
      const now = new Date();
      const gmst = satellite.gstime(now);
      const seen = new Set<string>();
      const drawOrbits = forceOrbits || Date.now() - lastOrbitDrawMs.current >= 45000;

      const points = pointsRef.current!;
      const labels = labelsRef.current!;
      const orbitSrc = orbitSrcRef.current!;
      const satMap = satMapRef.current;

      if (drawOrbits) {
        orbitSrc.entities.suspendEvents();
        orbitSrc.entities.removeAll();
        lastOrbitDrawMs.current = Date.now();
      }

      let drawn = 0;
      const MAX_ORBITS = 50;

      for (const { name, rec } of satCache) {
        try {
          const pv = satellite.propagate(rec, now);
          if (!pv || !pv.position || typeof pv.position === 'boolean') continue;
          const gd = satellite.eciToGeodetic(pv.position as any, gmst);
          const lon = CMath.toDegrees(gd.longitude);
          const lat = CMath.toDegrees(gd.latitude);
          const alt = gd.height * 1000;
          if (!isFinite(lon) || !isFinite(lat) || !isFinite(alt)) continue;

          seen.add(name);
          const pos = Cartesian3.fromDegrees(lon, lat, alt);
          const pickMeta: GlobePrimitivePick = {
            kind: 'satellite',
            lon,
            lat,
            name,
            alt,
          };

          let entry = satMap.get(name);
          if (entry) {
            entry.point.position = pos;
            entry.label.position = pos;
            entry.point.id = pickMeta;
          } else {
            const point = points.add({
              position: pos,
              pixelSize: 5,
              color: Color.fromCssColorString('#00e5ff'),
              outlineColor: Color.fromCssColorString('#003a44'),
              outlineWidth: 1,
              id: pickMeta,
            });
            const label = labels.add({
              position: pos,
              text: name,
              font: '600 10px "Courier New"',
              fillColor: Color.fromCssColorString('#7df9ff'),
              outlineColor: Color.BLACK,
              outlineWidth: 2,
              style: LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: VerticalOrigin.BOTTOM,
              pixelOffset: new Cartesian2(0, -8),
              distanceDisplayCondition: new DistanceDisplayCondition(0, 6e7),
            });
            entry = { point, label };
            satMap.set(name, entry);
          }

          if (drawOrbits && orbitsActive && drawn < MAX_ORBITS) {
            drawn++;
            const periodMin = (2 * Math.PI) / rec.no;
            const pts: Cartesian3[] = [];
            for (let i = 0; i <= 80; i++) {
              const t = new Date(now.getTime() + (periodMin * 60000 * i) / 80);
              const g = satellite.gstime(t);
              const p = satellite.propagate(rec, t);
              if (!p || !p.position || typeof p.position === 'boolean') continue;
              const od = satellite.eciToGeodetic(p.position as any, g);
              pts.push(
                Cartesian3.fromDegrees(
                  CMath.toDegrees(od.longitude),
                  CMath.toDegrees(od.latitude),
                  od.height * 1000,
                ),
              );
            }
            if (pts.length > 2) {
              orbitSrc.entities.add({
                polyline: {
                  positions: pts,
                  width: 1.2,
                  material: new PolylineGlowMaterialProperty({
                    glowPower: 0.25,
                    color: Color.fromCssColorString('#00e5ff').withAlpha(0.3),
                  }),
                },
              });
            }
          }
        } catch {
          /* skip */
        }
      }

      for (const [name, entry] of satMap) {
        if (!seen.has(name)) {
          points.remove(entry.point);
          labels.remove(entry.label);
          satMap.delete(name);
        }
      }

      if (drawOrbits) orbitSrc.entities.resumeEvents();
      setStats((p: any) => ({ ...p, satellites: satMap.size }));
      requestSceneRender(viewer);
    };

    propagateSats(true);
    const timer = setInterval(() => propagateSats(false), 5000);

    return () => {
      isCancelled = true;
      clearInterval(timer);
    };
  }, [viewer, satCache, active, orbitsActive, feedActive, setStats]);
}
