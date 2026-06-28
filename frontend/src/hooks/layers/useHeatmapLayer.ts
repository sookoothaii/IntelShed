import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Color,
  LabelStyle,
  VerticalOrigin,
  HorizontalOrigin,
  DistanceDisplayCondition,
  Viewer,
  type GeoJsonPrimitive,
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';
import { feedPos, feedPoint } from './layerUtils';
import {
  GEOJSON_PRIMITIVE_THRESHOLD,
  addGeoJsonPrimitive,
  removeGeoJsonPrimitive,
  pointsToGeoJson,
  type PointFeature,
} from './geoJsonPrimitive';
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
  const primRef = useRef<GeoJsonPrimitive | null>(null);

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
      removeGeoJsonPrimitive(viewer, primRef.current);
      srcRef.current = null;
      primRef.current = null;
    };
  }, [viewer]);

  useEffect(() => {
    if (srcRef.current) srcRef.current.show = active;
    if (primRef.current) {
      if (primRef.current.points) primRef.current.points.show = active;
      if (primRef.current.polylines) primRef.current.polylines.show = active;
      if (primRef.current.polygons) primRef.current.polygons.show = active;
    }
    if (!active) setHeatmapMeta(null);
  }, [active, setHeatmapMeta]);

  useEffect(() => {
    if (!data || !viewer || !active) return;
    const cells: HeatmapCell[] = (data as HeatmapApiResponse)?.cells || [];
    const usePrimitive = cells.length > GEOJSON_PRIMITIVE_THRESHOLD;

    // Clear previous primitive if present
    if (primRef.current) {
      removeGeoJsonPrimitive(viewer, primRef.current);
      primRef.current = null;
    }

    if (usePrimitive) {
      // --- GeoJsonPrimitive path (high-throughput, no labels) ---
      const features: PointFeature[] = cells.map((c) => ({
        lon: c.lon,
        lat: c.lat,
        properties: {
          kind: 'fusion_cell',
          intensity: c.intensity,
          score: c.score,
          sources: c.sources?.join(', '),
          samples: (c.samples || []).map((s: HeatmapSample) => `${s.source}: ${s.label}`).join(' | '),
        },
      }));
      const gj = pointsToGeoJson(features);
      primRef.current = addGeoJsonPrimitive(
        viewer,
        gj,
        (props) => {
          const t = Math.min(1, (props.score as number) || 0);
          const hueDeg = (1 - t) * 180;
          const cssColor = `hsla(${hueDeg.toFixed(0)}, 90%, ${(45 + t * 25).toFixed(0)}%, ${(0.18 + t * 0.55).toFixed(2)})`;
          return {
            color: Color.fromCssColorString(cssColor),
            outlineColor: Color.fromCssColorString('#ffffff').withAlpha(0.35),
            outlineWidth: 1,
            size: 8 + t * 14,
          };
        },
        (_idx, props) => props,
      );
      if (srcRef.current) srcRef.current.show = false;
      setHeatmapMeta({ cells: cells.length, max: (data as HeatmapApiResponse)?.max_intensity || 0, contrib: (data as HeatmapApiResponse)?.contributors || {} });
    } else {
      // --- DataSource path (with labels for high-score cells) ---
      if (srcRef.current) srcRef.current.show = true;
      const src = srcRef.current;
      if (!src) return;
      src.entities.suspendEvents();
      src.entities.removeAll();

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
    }
  }, [viewer, data, active, setHeatmapMeta]);
}
