import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Cartesian3,
  Color,
  NearFarScalar,
  PointPrimitiveCollection,
  Viewer,
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import type { GlobePrimitivePick } from '../../lib/globePick';
import { viewerAlive } from './layerUtils';

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

function wildfireColor(f: WildfireRow): string {
  const conf = f.confidence ?? 0;
  const isRegional = f.zone === 'regional';
  if (isRegional) {
    return conf >= 80 ? '#ff2d00' : conf >= 50 ? '#ff6b35' : '#ffd23f';
  }
  return conf >= 80 ? '#ff8c42' : conf >= 50 ? '#ffb347' : '#ffd23f';
}

function wildfirePixelSize(f: WildfireRow): number {
  const conf = f.confidence ?? 0;
  return conf >= 80 ? 10 : conf >= 50 ? 8 : 6;
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
    const collection = collectionRef.current;
    const fires: WildfireRow[] = data.fires || [];

    collection.removeAll();

    for (const f of fires) {
      if (f.lon == null || f.lat == null) continue;
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
      };

      collection.add({
        position: Cartesian3.fromDegrees(f.lon, f.lat, 0),
        pixelSize: wildfirePixelSize(f),
        color: Color.fromCssColorString(color).withAlpha(0.9),
        outlineColor: Color.WHITE,
        outlineWidth: 1,
        scaleByDistance: new NearFarScalar(1e5, 1.8, 1e7, 0.6),
        id: pickMeta,
      });
    }

    const mapped = fires.filter((f) => f.lon != null && f.lat != null).length;
    setStats((p: any) => ({ ...p, wildfires: data.count ?? mapped }));
    const source = data.source === 'eonet_fallback' ? 'eonet' : (data.source || '');
    setFeedHud((p: any) => ({ ...p, wildfires: source || (data.errors ? 'degraded' : '') }));
  }, [viewer, data, active, setStats, setFeedHud]);
}
