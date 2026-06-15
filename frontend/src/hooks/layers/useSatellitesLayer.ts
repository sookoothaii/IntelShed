import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Entity,
  Cartesian3,
  ConstantPositionProperty,
  Color,
  LabelStyle,
  VerticalOrigin,
  Cartesian2,
  DistanceDisplayCondition,
  PolylineGlowMaterialProperty,
  Viewer,
  Math as CMath
} from 'cesium';
import * as satellite from 'satellite.js';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';

export function useSatellitesLayer({
  viewer,
  active,
  orbitsActive,
  satGroup,
  feedActive,
  setStats
}: {
  viewer: Viewer | null;
  active: boolean;
  orbitsActive: boolean;
  satGroup: string;
  feedActive: boolean;
  setStats: React.Dispatch<React.SetStateAction<any>>;
}) {
  const satSrcRef = useRef<CustomDataSource | null>(null);
  const orbitSrcRef = useRef<CustomDataSource | null>(null);
  const satMapRef = useRef(new Map<string, Entity>());

  const { data: satCache } = useQuery({
    queryKey: ['satellites', satGroup],
    queryFn: async () => {
      const r = await fetchApi(`/api/satellites?group=${satGroup}&limit=500`);
      const d = await r.json();
      const cache: { name: string; rec: any }[] = [];
      for (const s of d.satellites || []) {
        try {
          cache.push({ name: s.name, rec: satellite.twoline2satrec(s.tle1, s.tle2) });
        } catch { /* skip */ }
      }
      // Reset maps when group changes
      satMapRef.current.clear();
      if (satSrcRef.current) satSrcRef.current.entities.removeAll();
      if (orbitSrcRef.current) orbitSrcRef.current.entities.removeAll();
      return cache;
    },
    enabled: active && feedActive,
    staleTime: 1000 * 60 * 60, // TLEs change slowly
  });

  useEffect(() => {
    if (!viewer) return;
    const satSrc = new CustomDataSource('satellites');
    const orbitSrc = new CustomDataSource('orbits');
    attachDataSource(viewer, satSrc);
    attachDataSource(viewer, orbitSrc);
    satSrcRef.current = satSrc;
    orbitSrcRef.current = orbitSrc;

    satSrc.show = active;
    orbitSrc.show = active && orbitsActive;

    return () => {
      detachDataSource(viewer, satSrc);
      detachDataSource(viewer, orbitSrc);
      satSrcRef.current = null;
      orbitSrcRef.current = null;
      satMapRef.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    if (satSrcRef.current) satSrcRef.current.show = active;
    if (orbitSrcRef.current) orbitSrcRef.current.show = active && orbitsActive;
  }, [active, orbitsActive]);

  const lastOrbitDrawMs = useRef(0);

  useEffect(() => {
    if (!active || !feedActive || !satCache || satCache.length === 0 || !satSrcRef.current || !orbitSrcRef.current) return;
    
    let isCancelled = false;

    const propagateSats = (forceOrbits = false) => {
      if (isCancelled) return;
      const now = new Date();
      const gmst = satellite.gstime(now);
      const seen = new Set<string>();
      const drawOrbits = forceOrbits || (Date.now() - lastOrbitDrawMs.current >= 45000);
      
      const orbitSrc = orbitSrcRef.current!;
      const satSrc = satSrcRef.current!;
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
          
          let e = satMap.get(name);
          if (e) {
            (e.position as ConstantPositionProperty).setValue(pos);
          } else {
            e = satSrc.entities.add({
              id: 'sat-' + name,
              position: new ConstantPositionProperty(pos),
              point: {
                pixelSize: 5,
                color: Color.fromCssColorString('#00e5ff'),
                outlineColor: Color.fromCssColorString('#003a44'),
                outlineWidth: 1,
              },
              label: {
                text: name,
                font: '600 10px "Courier New"',
                fillColor: Color.fromCssColorString('#7df9ff'),
                outlineColor: Color.BLACK,
                outlineWidth: 2,
                style: LabelStyle.FILL_AND_OUTLINE,
                verticalOrigin: VerticalOrigin.BOTTOM,
                pixelOffset: new Cartesian2(0, -8),
                distanceDisplayCondition: new DistanceDisplayCondition(0, 6e7),
              },
              properties: { kind: 'satellite', name, alt } as any,
            });
            satMap.set(name, e);
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
              pts.push(Cartesian3.fromDegrees(CMath.toDegrees(od.longitude), CMath.toDegrees(od.latitude), od.height * 1000));
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
        } catch { /* skip */ }
      }
      
      for (const [name, e] of satMap) {
        if (!seen.has(name)) { satSrc.entities.remove(e); satMap.delete(name); }
      }
      
      if (drawOrbits) orbitSrc.entities.resumeEvents();
      setStats((p: any) => ({ ...p, satellites: satMap.size }));
    };

    propagateSats(true);
    const timer = setInterval(() => propagateSats(false), 5000);

    return () => {
      isCancelled = true;
      clearInterval(timer);
    };
  }, [viewer, satCache, active, orbitsActive, feedActive, setStats]);
}
