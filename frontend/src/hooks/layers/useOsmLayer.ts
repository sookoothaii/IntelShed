import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Cartesian3,
  Color,
  LabelStyle,
  VerticalOrigin,
  Cartesian2,
  DistanceDisplayCondition,
  Viewer,
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';
import type { Stats } from '../../lib/types';

const infraColor = (itype: string | undefined) => {
  switch (itype) {
    case 'hospital':
      return '#ff2d00';
    case 'power':
      return '#ffd23f';
    case 'airport':
      return '#00e5ff';
    case 'bridge':
      return '#a855f7';
    case 'fire_station':
    case 'police':
      return '#ff6b35';
    default:
      return '#4fc3f7';
  }
};

export function useOsmLayer({
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

  const { data } = useQuery({
    queryKey: ['osm-infrastructure'],
    queryFn: async () => {
      const r = await fetchApi(
        '/api/osm/infrastructure?types=hospital,power,airport,bridge,fire_station,police',
      );
      return r.json();
    },
    refetchInterval: 7200000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('osm');
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
    src.entities.suspendEvents();
    src.entities.removeAll();

    for (const poi of data.pois || []) {
      if (poi.lon == null || poi.lat == null) continue;
      const col = Color.fromCssColorString(infraColor(poi.infra_type));
      src.entities.add({
        position: Cartesian3.fromDegrees(poi.lon, poi.lat, 0),
        point: {
          pixelSize: 8,
          color: col.withAlpha(0.85),
          outlineColor: Color.BLACK,
          outlineWidth: 1,
        },
        label: {
          text: poi.name || poi.infra_type || '?',
          font: '600 8px "Courier New"',
          fillColor: col,
          outlineColor: Color.BLACK,
          outlineWidth: 2,
          style: LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: VerticalOrigin.BOTTOM,
          pixelOffset: new Cartesian2(0, -8),
          distanceDisplayCondition: new DistanceDisplayCondition(0, 3e6),
        },
        properties: {
          kind: 'osm',
          name: poi.name,
          infra_type: poi.infra_type,
          osm_id: poi.osm_id,
        },
      });
    }
    src.entities.resumeEvents();
    setStats((p: Stats) => ({ ...p, osm: (data?.pois || []).length }));
  }, [viewer, data, active, setStats]);
}
