import { useEffect, useRef } from 'react';
import { CustomDataSource, Entity, Cartesian3, Color, PolylineGlowMaterialProperty, Viewer } from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';

export interface TrailsApi {
  fetchTrail: (icao: string) => Promise<void>;
  clearTrail: (icao: string) => void;
  clearAllTrails: () => void;
}

export function useTrailsLayer({
  viewer,
  active
}: {
  viewer: Viewer | null;
  active: boolean;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);
  const trailEntities = useRef(new Map<string, Entity>());

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('aircraft-trails');
    attachDataSource(viewer, src);
    srcRef.current = src;
    
    return () => {
      detachDataSource(viewer, src);
      srcRef.current = null;
      trailEntities.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    if (!srcRef.current) return;
    srcRef.current.show = active;
  }, [active]);

  const fetchTrail = async (icao: string) => {
    if (!icao || !srcRef.current || trailEntities.current.has(icao)) return;
    try {
      const r = await fetchApi(`/api/aircraft/trails?icao24=${encodeURIComponent(icao)}&minutes=30`);
      if (!r.ok) return;
      const d = await r.json();
      const pts: any[] = d.points || [];
      if (pts.length < 2) return;
      
      const positions: Cartesian3[] = pts.map(p => Cartesian3.fromDegrees(p.lon, p.lat, Math.max(p.alt ?? 0, 0)));
      const ent = srcRef.current.entities.add({
        id: `trail-${icao}`,
        polyline: {
          positions,
          width: 2.5,
          material: new PolylineGlowMaterialProperty({
            glowPower: 0.25,
            color: Color.fromCssColorString('#ffd23f').withAlpha(0.85),
          }),
          clampToGround: false,
        },
      });
      trailEntities.current.set(icao, ent);
    } catch (e) {
      // best effort
    }
  };

  const clearTrail = (icao: string) => {
    const e = trailEntities.current.get(icao);
    if (e && srcRef.current) {
      srcRef.current.entities.remove(e);
      trailEntities.current.delete(icao);
    }
  };

  const clearAllTrails = () => {
    if (srcRef.current) srcRef.current.entities.removeAll();
    trailEntities.current.clear();
  };

  return { fetchTrail, clearTrail, clearAllTrails };
}
