import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Cartesian3,
  Color,
  PolylineGlowMaterialProperty,
  LabelStyle,
  VerticalOrigin,
  HorizontalOrigin,
  Viewer
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';

export function useSpaceweatherLayer({
  viewer,
  active,
  feedActive,
  canFetch,
  setStats
}: {
  viewer: Viewer | null;
  active: boolean;
  feedActive: boolean;
  canFetch: boolean;
  setStats: React.Dispatch<React.SetStateAction<any>>;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);

  const { data } = useQuery({
    queryKey: ['spaceweather'],
    queryFn: async () => {
      const r = await fetchApi('/api/spaceweather');
      return r.json();
    },
    refetchInterval: 600000, // 10 minutes
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('spaceweather');
    attachDataSource(viewer, src);
    srcRef.current = src;
    
    return () => {
      detachDataSource(viewer, src);
      srcRef.current = null;
    };
  }, [viewer]);

  useEffect(() => {
    if (!srcRef.current) return;
    srcRef.current.show = active;
  }, [active]);

  useEffect(() => {
    if (!data || !srcRef.current || !active) return;
    const src = srcRef.current;
    const kp = data.kp_index ?? 0;
    
    src.entities.suspendEvents();
    src.entities.removeAll();
    
    const auroraLat = Math.min(55 + kp * 3, 75);
    
    // Northern hemisphere
    const pts: Cartesian3[] = [];
    for (let i = 0; i <= 128; i++) {
      const lon = (i / 128) * 360 - 180;
      pts.push(Cartesian3.fromDegrees(lon, auroraLat, 120000));
    }
    src.entities.add({
      polyline: {
        positions: pts,
        width: 3,
        material: new PolylineGlowMaterialProperty({
          glowPower: 0.4,
          color: Color.fromHsl(0.35 - kp * 0.04, 1.0, 0.5, 0.6),
        }),
      },
    });
    
    // Southern hemisphere
    const ptsS: Cartesian3[] = [];
    for (let i = 0; i <= 128; i++) {
      const lon = (i / 128) * 360 - 180;
      ptsS.push(Cartesian3.fromDegrees(lon, -auroraLat, 120000));
    }
    src.entities.add({
      polyline: {
        positions: ptsS,
        width: 3,
        material: new PolylineGlowMaterialProperty({
          glowPower: 0.4,
          color: Color.fromHsl(0.35 - kp * 0.04, 1.0, 0.5, 0.6),
        }),
      },
    });
    
    // Kp label
    src.entities.add({
      position: Cartesian3.fromDegrees(0, 88, 200000),
      label: {
        text: `Kp=${kp}`,
        font: '600 14px "Courier New"',
        fillColor: Color.fromCssColorString('#00e5a0'),
        outlineColor: Color.BLACK,
        outlineWidth: 2,
        style: LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: VerticalOrigin.CENTER,
        horizontalOrigin: HorizontalOrigin.CENTER,
      },
    });
    
    src.entities.resumeEvents();
    setStats((p: any) => ({ ...p, spaceweather: kp }));
  }, [viewer, data, active, setStats]);
}
