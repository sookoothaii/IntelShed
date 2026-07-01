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
import type { Stats } from '../../lib/types';

const FLOWSINT_COLOR = Color.fromCssColorString('#ff6b35');

const SCHEMA_COLORS: Record<string, Color> = {
  IpAddress: Color.fromCssColorString('#ff6b35'),
  Ip: Color.fromCssColorString('#ff6b35'),
  Domain: Color.fromCssColorString('#4fc3f7'),
  Organization: Color.fromCssColorString('#00e5a0'),
  Person: Color.fromCssColorString('#ffd23f'),
  HyperText: Color.fromCssColorString('#e040fb'),
  default: FLOWSINT_COLOR,
};

export function useFlowsintLayer({
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
    queryKey: ['flowsint-enriched-graph'],
    queryFn: async () => {
      const r = await fetchApi('/api/flowsint/enriched-graph');
      return r.json();
    },
    refetchInterval: 120000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('flowsint');
    attachDataSource(viewer, src);
    srcRef.current = src;
    return () => {
      detachDataSource(viewer, src);
      srcRef.current = null;
    };
  }, [viewer]);

  useEffect(() => {
    if (srcRef.current) srcRef.current.show = active;
  }, [active]);

  useEffect(() => {
    if (!viewer || !active) return;
    const pins: Array<{ lat: number; lon: number; label: string; type: string }> =
      data?.pins || [];
    const valid = pins.filter((p) => p.lat != null && p.lon != null);

    const src = srcRef.current;
    if (!src) return;
    src.entities.suspendEvents();
    src.entities.removeAll();

    let plotted = 0;
    for (const pin of valid) {
      const color = SCHEMA_COLORS[pin.type] || SCHEMA_COLORS.default;
      src.entities.add({
        position: feedPos(pin.lon, pin.lat),
        point: feedPoint(8, color, { outlineWidth: 1, outline: Color.WHITE }),
        label: {
          text: pin.label.slice(0, 40),
          font: '600 8px "Courier New"',
          fillColor: color,
          outlineColor: Color.BLACK,
          outlineWidth: 2,
          style: LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: VerticalOrigin.BOTTOM,
          pixelOffset: new Cartesian2(0, -8),
          distanceDisplayCondition: new DistanceDisplayCondition(0, 3e6),
        },
        properties: {
          kind: 'flowsint',
          label: pin.label,
          type: pin.type,
        },
      });
      plotted += 1;
    }

    src.entities.resumeEvents();
    setStats((p: Stats) => ({ ...p, osint: plotted }));
  }, [viewer, data, active, setStats]);
}
