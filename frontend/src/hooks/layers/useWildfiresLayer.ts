import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Cartesian3,
  Cartographic,
  Color,
  NearFarScalar,
  PointPrimitiveCollection,
  Viewer,
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import type { GlobePrimitivePick } from '../../lib/globePick';
import { requestSceneRender, viewerAlive } from './layerUtils';

type WildfireRow = {
  lon?: number | null;
  lat?: number | null;
  confidence?: number | null;
  confidence_label?: string | null;
  brightness?: number | null;
  frp?: number | null;
  satellite?: string | null;
  zone?: string | null;
  acq_date?: string | null;
};

const CLUSTER_MIN_FIRES = 800
const CLUSTER_MIN_HEIGHT_M = 400_000

function wildfireColor(f: WildfireRow): string {
  const conf = f.confidence ?? 0;
  const isRegional = f.zone === 'regional';
  if (isRegional) {
    return conf >= 80 ? '#ff2d00' : conf >= 50 ? '#ff6b35' : '#ffd23f';
  }
  return conf >= 80 ? '#ff8c42' : conf >= 50 ? '#ffb347' : '#ffd23f';
}

function wildfirePixelSize(f: WildfireRow, clusterCount = 1): number {
  const conf = f.confidence ?? 0;
  const base = conf >= 80 ? 10 : conf >= 50 ? 8 : 6;
  if (clusterCount <= 1) return base;
  return Math.min(18, base + Math.log10(clusterCount) * 3);
}

function clusterCellDeg(cameraHeightM: number): number {
  if (cameraHeightM < CLUSTER_MIN_HEIGHT_M) return 0;
  if (cameraHeightM < 1_500_000) return 0.25;
  if (cameraHeightM < 5_000_000) return 0.75;
  if (cameraHeightM < 15_000_000) return 2;
  return 4;
}

function clusterWildfires(fires: WildfireRow[], cellDeg: number): Array<WildfireRow & { cluster_count?: number }> {
  const buckets = new Map<string, WildfireRow[]>();
  for (const f of fires) {
    if (f.lon == null || f.lat == null) continue;
    const gx = Math.floor(f.lon / cellDeg);
    const gy = Math.floor(f.lat / cellDeg);
    const key = `${gx}:${gy}`;
    const list = buckets.get(key);
    if (list) list.push(f);
    else buckets.set(key, [f]);
  }

  const out: Array<WildfireRow & { cluster_count?: number }> = [];
  for (const group of buckets.values()) {
    if (group.length === 1) {
      out.push(group[0]);
      continue;
    }
    let best = group[0];
    let bestConf = best.confidence ?? 0;
    let sumLon = 0;
    let sumLat = 0;
    for (const f of group) {
      sumLon += f.lon ?? 0;
      sumLat += f.lat ?? 0;
      const conf = f.confidence ?? 0;
      if (conf > bestConf) {
        best = f;
        bestConf = conf;
      }
    }
    out.push({
      ...best,
      lon: sumLon / group.length,
      lat: sumLat / group.length,
      cluster_count: group.length,
    });
  }
  return out;
}

function cameraHeightM(viewer: Viewer): number {
  try {
    const c = Cartographic.fromCartesian(viewer.camera.position);
    return c.height;
  } catch {
    return 0;
  }
}

function attachPointCollection(viewer: Viewer, collection: PointPrimitiveCollection): boolean {
  if (!viewerAlive(viewer)) return false;
  try {
    viewer.scene.primitives.add(collection);
    return true;
  } catch {
    return false;
  }
}

function detachPointCollection(viewer: Viewer | null, collection: PointPrimitiveCollection | null): void {
  if (!collection || !viewerAlive(viewer)) return;
  try {
    viewer.scene.primitives.remove(collection);
  } catch {
    /* viewer already destroyed */
  }
}

function renderWildfires(
  viewer: Viewer | null,
  collection: PointPrimitiveCollection,
  fires: WildfireRow[],
  cameraH: number,
) {
  collection.removeAll();
  const cellDeg = fires.length >= CLUSTER_MIN_FIRES ? clusterCellDeg(cameraH) : 0;
  const visible = cellDeg > 0 ? clusterWildfires(fires, cellDeg) : fires;

  for (const f of visible) {
    if (f.lon == null || f.lat == null) continue;
    const clusterCount = (f as WildfireRow & { cluster_count?: number }).cluster_count ?? 1;
    const color = wildfireColor(f);
    const pickMeta: GlobePrimitivePick = {
      kind: 'wildfire',
      lon: f.lon,
      lat: f.lat,
      confidence: f.confidence,
      confidence_label: f.confidence_label,
      brightness: f.brightness,
      frp: f.frp,
      satellite: f.satellite,
      zone: f.zone,
      acq_date: f.acq_date,
      cluster_count: clusterCount > 1 ? clusterCount : undefined,
    };

    collection.add({
      position: Cartesian3.fromDegrees(f.lon, f.lat, 0),
      pixelSize: wildfirePixelSize(f, clusterCount),
      color: Color.fromCssColorString(color).withAlpha(0.9),
      outlineColor: Color.WHITE,
      outlineWidth: 1,
      scaleByDistance: new NearFarScalar(1e5, 1.8, 1e7, 0.6),
      id: pickMeta,
    });
  }
  if (viewer) requestSceneRender(viewer);
}

export function useWildfiresLayer({
  viewer,
  active,
  feedActive,
  canFetch,
  setStats,
  setFeedHud
}: {
  viewer: Viewer | null;
  active: boolean;
  feedActive: boolean;
  canFetch: boolean;
  setStats: React.Dispatch<React.SetStateAction<any>>;
  setFeedHud: React.Dispatch<React.SetStateAction<any>>;
}) {
  const collectionRef = useRef<PointPrimitiveCollection | null>(null);
  const dataRef = useRef<any>(null);
  const cameraHRef = useRef(0);

  const { data } = useQuery({
    queryKey: ['wildfires'],
    queryFn: async () => {
      const r = await fetchApi('/api/wildfires');
      return r.json();
    },
    refetchInterval: 600000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const collection = new PointPrimitiveCollection();
    attachPointCollection(viewer, collection);
    collectionRef.current = collection;

    return () => {
      detachPointCollection(viewer, collection);
      collectionRef.current = null;
    };
  }, [viewer]);

  useEffect(() => {
    if (!collectionRef.current) return;
    collectionRef.current.show = active;
  }, [active]);

  useEffect(() => {
    if (!data || !collectionRef.current || !active) return;
    dataRef.current = data;
    const fires: WildfireRow[] = data.fires || [];
    const h = viewer ? cameraHeightM(viewer) : 0;
    cameraHRef.current = h;
    renderWildfires(viewer, collectionRef.current, fires, h);

    const mapped = fires.filter((f) => f.lon != null && f.lat != null).length;
    setStats((p: any) => ({ ...p, wildfires: data.count ?? mapped }));
    const source = data.source === 'eonet_fallback' ? 'eonet' : (data.source || '');
    setFeedHud((p: any) => ({ ...p, wildfires: source || (data.errors ? 'degraded' : '') }));
  }, [viewer, data, active, setStats, setFeedHud]);

  // Re-cluster when camera altitude crosses cluster thresholds.
  useEffect(() => {
    if (!viewer || !active || !collectionRef.current || !dataRef.current) return;
    const fires: WildfireRow[] = dataRef.current.fires || [];
    if (fires.length < CLUSTER_MIN_FIRES) return;

    let lastCellDeg = clusterCellDeg(cameraHRef.current);
    const onCamera = () => {
      if (!collectionRef.current || !dataRef.current) return;
      const h = cameraHeightM(viewer);
      const nextCell = clusterCellDeg(h);
      if (nextCell === lastCellDeg && Math.abs(h - cameraHRef.current) < 50_000) return;
      lastCellDeg = nextCell;
      cameraHRef.current = h;
      renderWildfires(viewer, collectionRef.current, fires, h);
    };
    viewer.camera.changed.addEventListener(onCamera);
    return () => {
      try { viewer.camera.changed.removeEventListener(onCamera) } catch { /* teardown */ }
    };
  }, [viewer, active]);
}
