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
import { attachPulseEllipse, clearPulseCleanups } from './pulseAnimation';
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
  const pulseCleanupsRef = useRef<Array<() => void>>([]);

  const { data } = useQuery({
    queryKey: ['heatmap'],
    queryFn: async () => {
      const r = await fetchApi('/api/fusion/heatmap?cell_deg=2&top=80&include_geojson=0');
      return r.json();
    },
    refetchInterval: 120000,
    enabled: active && feedActive && canFetch,
  });

  const { data: deltaData } = useQuery({
    queryKey: ['fusion-delta'],
    queryFn: async () => {
      const r = await fetchApi('/api/fusion/delta?compare=24h&cell_deg=2&top=20&include_geojson=0');
      return r.json();
    },
    refetchInterval: 180000,
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
      clearPulseCleanups(pulseCleanupsRef.current);
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
    if (!active) {
      clearPulseCleanups(pulseCleanupsRef.current);
    }
    if (!active) setHeatmapMeta(null);
  }, [active, setHeatmapMeta]);

  useEffect(() => {
    if (!data || !viewer || !active) return;
    const cells: HeatmapCell[] = (data as HeatmapApiResponse)?.cells || [];
    const usePrimitive = cells.length > GEOJSON_PRIMITIVE_THRESHOLD;

    // Build delta map from delta endpoint
    const deltaMap = new Map<string, number>();
    const deltaCells = (deltaData as { cells?: HeatmapCell[] })?.cells || [];
    for (const dc of deltaCells) {
      const cid = dc.cell_id || `${dc.lat.toFixed(2)},${dc.lon.toFixed(2)}`;
      if (dc.delta_score != null) deltaMap.set(cid, dc.delta_score);
    }

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

      // Clear previous pulse animations
      clearPulseCleanups(pulseCleanupsRef.current);

      for (const c of cells) {
        const t = Math.min(1, c.score || 0);
        const hueDeg = (1 - t) * 180;
        const cssColor = `hsla(${hueDeg.toFixed(0)}, 90%, ${(45 + t * 25).toFixed(0)}%, ${(0.18 + t * 0.55).toFixed(2)})`;

        // Check if this cell has a high delta score
        const cid = c.cell_id || `${c.lat.toFixed(2)},${c.lon.toFixed(2)}`;
        const delta = deltaMap.get(cid);
        const hasHighDelta = delta != null && delta > 0.12;

        const ent = src.entities.add({
          id: `fusion-${c.lat}-${c.lon}`,
          position: feedPos(c.lon, c.lat),
          point: feedPoint(8 + t * 14, Color.fromCssColorString(cssColor), {
            outlineWidth: 1,
            outline: hasHighDelta
              ? Color.fromCssColorString('#ff6b35').withAlpha(0.8)
              : Color.fromCssColorString('#ffffff').withAlpha(0.35),
          }),
          label: t > 0.5 ? {
            text: hasHighDelta ? `${Math.round(c.intensity)} Δ+${delta!.toFixed(2)}` : `${Math.round(c.intensity)}`,
            font: '700 11px "Courier New"',
            fillColor: hasHighDelta ? Color.fromCssColorString('#ff6b35') : Color.fromCssColorString('#ffffff'),
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
            delta_score: delta ?? null,
            sources: c.sources?.join(', '),
            samples: (c.samples || []).map((s: HeatmapSample) => `${s.source}: ${s.label}`).join(' | '),
          },
        });

        // Attach pulse animation for high-delta cells
        if (hasHighDelta && ent) {
          const pulseColor = Color.fromCssColorString('#ff6b35');
          const cleanup = attachPulseEllipse(ent, {
            cycleMs: 2000,
            baseRadius: 30000,
            pulseScale: 200000,
            color: pulseColor,
            alphaScale: 0.4,
          });
          pulseCleanupsRef.current.push(cleanup);
        }
      }

      src.entities.resumeEvents();
      setHeatmapMeta({ cells: cells.length, max: (data as HeatmapApiResponse)?.max_intensity || 0, contrib: (data as HeatmapApiResponse)?.contributors || {} });
    }
  }, [viewer, data, deltaData, active, setHeatmapMeta]);
}
