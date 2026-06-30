import { useEffect, useRef, useCallback } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Color,
  Rectangle as CesiumRectangle,
  LabelStyle,
  VerticalOrigin,
  Cartesian2,
  DistanceDisplayCondition,
  Viewer,
  type Entity,
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource, requestSceneRender } from './layerUtils';
import type { Stats } from '../../lib/types';

// ── Types ───────────────────────────────────────────────────────────────────────

type DetectionType = 'disaster' | 'conflict' | 'vessel' | 'infrastructure';

type DetectionItem = {
  id: string;
  lat: number;
  lon: number;
  confidence: number; // 0..1
  type: DetectionType;
  label: string;
  source: string;
  schema?: string;
  boxDeg: number; // half-extent in degrees for the rectangle
};

// ── Colour coding ────────────────────────────────────────────────────────────────

const TYPE_COLORS: Record<DetectionType, { fill: string; outline: string }> = {
  disaster: { fill: '#FACC15', outline: '#FACC15' },
  conflict: { fill: '#EF4444', outline: '#EF4444' },
  vessel: { fill: '#3B82F6', outline: '#3B82F6' },
  infrastructure: { fill: '#A855F7', outline: '#A855F7' },
};

const MAX_DETECTIONS = 50;
const PERMANENT_LABEL_COUNT = 10;

// ── Normalisation helpers ────────────────────────────────────────────────────────

function clamp01(n: number | null | undefined): number {
  if (n == null || !Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(1, n));
}

function getArr(data: unknown, key: string): Record<string, unknown>[] {
  if (!data || typeof data !== 'object') return [];
  const arr = (data as Record<string, unknown>)[key];
  return Array.isArray(arr) ? (arr as Record<string, unknown>[]) : [];
}

function normaliseFusionHotspots(raw: unknown): DetectionItem[] {
  if (!Array.isArray(raw)) return [];
  return (raw as Record<string, unknown>[])
    .filter((h) => h.lat != null && h.lon != null)
    .map((h, i) => ({
      id: `fusion-${i}-${h.lat}-${h.lon}`,
      lat: h.lat as number,
      lon: h.lon as number,
      confidence: clamp01(h.score as number),
      type: 'conflict' as DetectionType,
      label: String(
        h.label ||
          h.summary ||
          `Fusion ${(h.lat as number).toFixed(1)}, ${(h.lon as number).toFixed(1)}`,
      ),
      source: 'fusion',
      boxDeg: 0.5,
    }));
}

// ── Entity property updater (type-safe via unknown cast) ─────────────────────────

function setRectProp(
  ent: Entity,
  key: 'coordinates' | 'fill' | 'material' | 'outline' | 'outlineColor',
  value: unknown,
): void {
  const rect = ent.rectangle;
  if (!rect) return;
  const props = rect as unknown as Record<string, { setValue?: (v: unknown) => void } | undefined>;
  const p = props[key];
  if (p && typeof p.setValue === 'function') p.setValue(value);
}

function setLabelProp(ent: Entity, key: 'text' | 'show' | 'fillColor', value: unknown): void {
  const lbl = ent.label;
  if (!lbl) return;
  const props = lbl as unknown as Record<string, { setValue?: (v: unknown) => void } | undefined>;
  const p = props[key];
  if (p && typeof p.setValue === 'function') p.setValue(value);
}

function normaliseGdacs(data: unknown): DetectionItem[] {
  return getArr(data, 'alerts')
    .filter((a) => a.lat != null && a.lon != null)
    .map((a, i) => ({
      id: `gdacs-${i}-${a.lat}-${a.lon}`,
      lat: a.lat as number,
      lon: a.lon as number,
      confidence: 0.7,
      type: 'disaster' as DetectionType,
      label: String(a.title || 'GDACS Alert').slice(0, 60),
      source: 'gdacs',
      boxDeg: 1.0,
    }));
}

function normaliseWildfires(data: unknown): DetectionItem[] {
  return getArr(data, 'fires')
    .filter((f) => f.lat != null && f.lon != null)
    .map((f, i) => ({
      id: `fire-${i}-${f.lat}-${f.lon}`,
      lat: f.lat as number,
      lon: f.lon as number,
      confidence: clamp01(((f.confidence as number) ?? 0) / 100),
      type: 'disaster' as DetectionType,
      label: `Wildfire ${f.confidence ?? '?'}%`,
      source: 'firms',
      boxDeg: 0.05,
    }));
}

function normaliseAnomalies(data: unknown): DetectionItem[] {
  return getArr(data, 'anomalies')
    .filter((a) => a.lat != null && a.lon != null)
    .map((a, i) => ({
      id: `anom-${i}-${a.icao24 || a.callsign || ''}`,
      lat: a.lat as number,
      lon: a.lon as number,
      confidence: 0.6,
      type: 'vessel' as DetectionType,
      label: `Anomaly ${a.callsign || a.icao24 || '—'}`,
      source: 'ais-anomaly',
      boxDeg: 0.1,
    }));
}

function normaliseIntel(data: unknown): DetectionItem[] {
  return getArr(data, 'entities')
    .filter((e) => e.lat != null && e.lon != null)
    .map((e, i) => ({
      id: `intel-${e.id || i}`,
      lat: e.lat as number,
      lon: e.lon as number,
      confidence: 0.5,
      type: 'infrastructure' as DetectionType,
      label: String(e.caption || e.id || 'Intel entity').slice(0, 48),
      source: 'ftm',
      schema: e.schema as string | undefined,
      boxDeg: 0.1,
    }));
}

// ── Hook ─────────────────────────────────────────────────────────────────────────

export function useDetectionBoxes({
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
  const poolRef = useRef<Map<string, Entity>>(new Map());
  const hiddenPoolRef = useRef<Entity[]>([]);

  // Reuse cached queries from existing layer hooks
  const briefingQ = useQuery({
    queryKey: ['briefing'],
    queryFn: async () => {
      const r = await fetchApi('/api/briefing');
      return r.json();
    },
    refetchInterval: 60_000,
    enabled: active && feedActive && canFetch,
  });

  const gdacsQ = useQuery({
    queryKey: ['gdacs'],
    queryFn: async () => {
      const r = await fetchApi('/api/gdacs');
      return r.json();
    },
    refetchInterval: 300_000,
    enabled: active && feedActive && canFetch,
  });

  const wildfiresQ = useQuery({
    queryKey: ['wildfires'],
    queryFn: async () => {
      const r = await fetchApi('/api/wildfires');
      return r.json();
    },
    refetchInterval: 600_000,
    enabled: active && feedActive && canFetch,
  });

  const anomaliesQ = useQuery({
    queryKey: ['anomalies'],
    queryFn: async () => {
      const r = await fetchApi('/api/anomalies');
      return r.json();
    },
    refetchInterval: 120_000,
    enabled: active && feedActive && canFetch,
  });

  const intelQ = useQuery({
    queryKey: ['intel-entities-geo'],
    queryFn: async () => {
      const r = await fetchApi('/api/intel/entities?geolocated=1&limit=100&window_hours=24');
      return r.json();
    },
    refetchInterval: 120_000,
    enabled: active && feedActive && canFetch,
  });

  // Init / destroy DataSource
  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('detection-boxes');
    attachDataSource(viewer, src);
    srcRef.current = src;
    return () => {
      detachDataSource(viewer, src);
      srcRef.current = null;
      poolRef.current.clear();
      hiddenPoolRef.current = [];
    };
  }, [viewer]);

  // Toggle visibility
  useEffect(() => {
    if (srcRef.current) srcRef.current.show = active;
  }, [active]);

  // Build detection items from all sources
  const buildDetections = useCallback((): DetectionItem[] => {
    const all: DetectionItem[] = [
      ...normaliseFusionHotspots(briefingQ.data?.fusion_hotspots),
      ...normaliseGdacs(gdacsQ.data),
      ...normaliseWildfires(wildfiresQ.data),
      ...normaliseAnomalies(anomaliesQ.data),
      ...normaliseIntel(intelQ.data),
    ];
    all.sort((a, b) => b.confidence - a.confidence);
    return all.slice(0, MAX_DETECTIONS);
  }, [briefingQ.data, gdacsQ.data, wildfiresQ.data, anomaliesQ.data, intelQ.data]);

  // Render entities with pooling
  useEffect(() => {
    if (!srcRef.current || !active) return;
    const src = srcRef.current;
    const detections = buildDetections();
    const pool = poolRef.current;
    const hiddenPool = hiddenPoolRef.current;
    const usedIds = new Set<string>();

    src.entities.suspendEvents();

    for (let i = 0; i < detections.length; i++) {
      const det = detections[i];
      usedIds.add(det.id);
      const colors = TYPE_COLORS[det.type];
      const fillColor = Color.fromCssColorString(colors.fill).withAlpha(0.2);
      const outlineColor = Color.fromCssColorString(colors.outline);
      const west = det.lon - det.boxDeg;
      const east = det.lon + det.boxDeg;
      const south = det.lat - det.boxDeg;
      const north = det.lat + det.boxDeg;
      const coords = CesiumRectangle.fromDegrees(west, south, east, north);
      const isTop10 = i < PERMANENT_LABEL_COUNT;
      const labelText = `${det.label} · ${Math.round(det.confidence * 100)}%`;

      let ent = pool.get(det.id);
      if (ent) {
        // Update existing entity in place
        ent.show = true;
        setRectProp(ent, 'coordinates', coords);
        setRectProp(ent, 'material', fillColor);
        setRectProp(ent, 'outlineColor', outlineColor);
        setLabelProp(ent, 'text', labelText);
        setLabelProp(ent, 'show', isTop10);
        setLabelProp(ent, 'fillColor', outlineColor);
      } else if (hiddenPool.length > 0) {
        // Recycle a hidden entity
        ent = hiddenPool.pop()!;
        ent.show = true;
        pool.set(det.id, ent);
        setRectProp(ent, 'coordinates', coords);
        setRectProp(ent, 'material', fillColor);
        setRectProp(ent, 'outlineColor', outlineColor);
        setLabelProp(ent, 'text', labelText);
        setLabelProp(ent, 'show', isTop10);
        setLabelProp(ent, 'fillColor', outlineColor);
      } else {
        // Create new entity
        ent = src.entities.add({
          id: det.id,
          rectangle: {
            coordinates: coords,
            fill: true,
            material: fillColor,
            outline: true,
            outlineColor,
            outlineWidth: 2,
          },
          label: {
            text: labelText,
            font: '700 11px "Courier New"',
            fillColor: outlineColor,
            outlineColor: Color.BLACK,
            outlineWidth: 2,
            style: LabelStyle.FILL_AND_OUTLINE,
            verticalOrigin: VerticalOrigin.BOTTOM,
            pixelOffset: new Cartesian2(0, -8),
            distanceDisplayCondition: new DistanceDisplayCondition(0, 8e6),
            show: isTop10,
          },
          properties: {
            kind: 'detection_box',
            id: det.id,
            type: det.type,
            label: det.label,
            confidence: det.confidence,
            source: det.source,
            schema: det.schema || '',
            lat: det.lat,
            lon: det.lon,
          },
        });
        pool.set(det.id, ent);
      }
    }

    // Hide entities not in current data (recycle into hidden pool)
    for (const [id, ent] of pool) {
      if (!usedIds.has(id)) {
        ent.show = false;
        pool.delete(id);
        hiddenPool.push(ent);
      }
    }

    src.entities.resumeEvents();
    requestSceneRender(viewer);
  }, [buildDetections, active, viewer]);

  // Update stats count
  useEffect(() => {
    if (!active) return;
    const detections = buildDetections();
    // Store count in the closest existing stat slot — reuse `osint` since detection boxes
    // are an intelligence overlay. This avoids adding a new Stats key.
    setStats((p: Stats) => ({ ...p, osint: detections.length }));
  }, [buildDetections, active, setStats]);
}
