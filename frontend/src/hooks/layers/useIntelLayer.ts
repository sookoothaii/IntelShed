import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Color,
  LabelStyle,
  VerticalOrigin,
  Cartesian2,
  DistanceDisplayCondition,
  Viewer,
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';
import { feedPos, feedPoint } from './layerUtils';

const SCHEMA_COLORS: Record<string, string> = {
  Person: '#00ffa3',
  Organization: '#22d3ee',
  Company: '#4fc3f7',
  Vessel: '#ffd23f',
  Event: '#ff6b35',
  Airplane: '#ffd23f',
  default: '#b794f6',
};

function schemaColor(schema: string | undefined): Color {
  const hex = SCHEMA_COLORS[schema || ''] || SCHEMA_COLORS.default;
  return Color.fromCssColorString(hex);
}

export function useIntelLayer({
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
  setStats: React.Dispatch<React.SetStateAction<any>>;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);

  const { data } = useQuery({
    queryKey: ['intel-entities-geo'],
    queryFn: async () => {
      const r = await fetchApi('/api/intel/entities?geolocated=1&limit=250&window_hours=24');
      return r.json();
    },
    refetchInterval: 120000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('intel-ftm');
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
    if (!srcRef.current || !active) return;
    const src = srcRef.current;
    src.entities.suspendEvents();
    src.entities.removeAll();

    let plotted = 0;
    for (const ent of data?.entities || []) {
      const lat = ent.lat;
      const lon = ent.lon;
      if (lat == null || lon == null) continue;
      const caption = (ent.caption || ent.id || 'Entity').slice(0, 48);
      const schema = ent.schema || 'Entity';
      src.entities.add({
        position: feedPos(lon, lat),
        point: feedPoint(9, schemaColor(schema), { outlineWidth: 1 }),
        label: {
          text: caption,
          font: '600 9px "Courier New"',
          fillColor: schemaColor(schema),
          outlineColor: Color.BLACK,
          outlineWidth: 2,
          style: LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: VerticalOrigin.BOTTOM,
          pixelOffset: new Cartesian2(0, -10),
          distanceDisplayCondition: new DistanceDisplayCondition(0, 4e6),
        },
        properties: {
          kind: 'intel_ftm',
          id: ent.id,
          schema,
          caption,
          datasets: ent.datasets || [],
          last_seen: ent.last_seen,
        } as any,
      });
      plotted += 1;
    }

    src.entities.resumeEvents();
    setStats((p: any) => ({ ...p, intelFt: plotted }));
  }, [data, active, setStats]);
}
