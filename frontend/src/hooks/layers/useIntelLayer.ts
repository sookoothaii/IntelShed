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
import type { Stats } from '../../lib/types';

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
  setStats: React.Dispatch<React.SetStateAction<Stats>>;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);
  const primRef = useRef<GeoJsonPrimitive | null>(null);

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
  }, [active]);

  useEffect(() => {
    if (!viewer || !active) return;
    const entities: Array<Record<string, unknown>> = data?.entities || [];
    const valid = entities.filter((e) => e.lat != null && e.lon != null);
    const usePrimitive = valid.length > GEOJSON_PRIMITIVE_THRESHOLD;

    // Clear previous primitive if switching modes
    if (primRef.current) {
      removeGeoJsonPrimitive(viewer, primRef.current);
      primRef.current = null;
    }

    if (usePrimitive) {
      // --- GeoJsonPrimitive path (high-throughput, no labels) ---
      const features: PointFeature[] = valid.map((ent) => ({
        lon: ent.lon as number,
        lat: ent.lat as number,
        properties: {
          kind: 'intel_ftm',
          id: ent.id,
          schema: ent.schema || 'Entity',
          caption: String(ent.caption || ent.id || 'Entity').slice(0, 48),
          datasets: ent.datasets || [],
          last_seen: ent.last_seen,
        },
      }));
      const gj = pointsToGeoJson(features);
      primRef.current = addGeoJsonPrimitive(
        viewer,
        gj,
        (props) => ({
          color: schemaColor(props.schema as string | undefined),
          outlineColor: Color.WHITE,
          outlineWidth: 1,
          size: 9,
        }),
        (_idx, props) => props,
      );
      // Hide DataSource entities when using primitive path
      if (srcRef.current) srcRef.current.show = false;
      setStats((p: Stats) => ({ ...p, intelFt: valid.length }));
    } else {
      // --- DataSource path (rich styling with labels) ---
      if (srcRef.current) srcRef.current.show = true;
      const src = srcRef.current;
      if (!src) return;
      src.entities.suspendEvents();
      src.entities.removeAll();

      let plotted = 0;
      for (const ent of valid) {
        const lat = ent.lat as number;
        const lon = ent.lon as number;
        const caption = String(ent.caption || ent.id || 'Entity').slice(0, 48);
        const schema = (ent.schema || 'Entity') as string;
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
          },
        });
        plotted += 1;
      }

      src.entities.resumeEvents();
      setStats((p: Stats) => ({ ...p, intelFt: plotted }));
    }
  }, [viewer, data, active, setStats]);
}
