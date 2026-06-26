import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Color,
  LabelStyle,
  VerticalOrigin,
  HorizontalOrigin,
  DistanceDisplayCondition,
  Viewer
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';
import { feedPos, feedPoint } from './layerUtils';
import type { HeatmapMeta, HeatmapCell, HeatmapSample, HeatmapApiResponse } from '../../lib/types';

export function useHeatmapLayer({
  viewer,
  active,
  feedActive,
  canFetch,
  setHeatmapMeta
}: {
  viewer: Viewer | null;
  active: boolean;
  feedActive: boolean;
  canFetch: boolean;
  setHeatmapMeta: React.Dispatch<React.SetStateAction<HeatmapMeta | null>>;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);

  const { data } = useQuery({
    queryKey: ['heatmap'],
    queryFn: async () => {
      const r = await fetchApi('/api/fusion/heatmap?cell_deg=2&top=80&include_geojson=0');
      return r.json();
    },
    refetchInterval: 120000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('fusion-heatmap');
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
    if (!active) setHeatmapMeta(null);
  }, [active, setHeatmapMeta]);

  useEffect(() => {
    if (!data || !srcRef.current || !active) return;
    const src = srcRef.current;
    
    src.entities.suspendEvents();
    src.entities.removeAll();
    
    const cells: HeatmapCell[] = (data as HeatmapApiResponse)?.cells || [];
    for (const c of cells) {
      const t = Math.min(1, c.score || 0);
      const hueDeg = (1 - t) * 180;
      const cssColor = `hsla(${hueDeg.toFixed(0)}, 90%, ${(45 + t * 25).toFixed(0)}%, ${(0.18 + t * 0.55).toFixed(2)})`;
      
      src.entities.add({
        id: `fusion-${c.lat}-${c.lon}`,
        position: feedPos(c.lon, c.lat),
        point: feedPoint(8 + t * 14, Color.fromCssColorString(cssColor), {
          outlineWidth: 1,
          outline: Color.fromCssColorString('#ffffff').withAlpha(0.35),
        }),
        label: t > 0.5 ? {
          text: `${Math.round(c.intensity)}`,
          font: '700 11px "Courier New"',
          fillColor: Color.fromCssColorString('#ffffff'),
          outlineColor: Color.BLACK,
          outlineWidth: 2,
          style: LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: VerticalOrigin.CENTER,
          horizontalOrigin: HorizontalOrigin.CENTER,
          distanceDisplayCondition: new DistanceDisplayCondition(0, 8e7),
        } : undefined,
        properties: {
          kind: 'fusion_cell',
          intensity: c.intensity,
          score: c.score,
          sources: c.sources?.join(', '),
          samples: (c.samples || []).map((s: HeatmapSample) => `${s.source}: ${s.label}`).join(' | '),
        },
      });
    }
    
    src.entities.resumeEvents();
    setHeatmapMeta({ cells: cells.length, max: (data as HeatmapApiResponse)?.max_intensity || 0, contrib: (data as HeatmapApiResponse)?.contributors || {} });
  }, [viewer, data, active, setHeatmapMeta]);
}
