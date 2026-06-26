import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  CustomDataSource,
  Color,
  LabelStyle,
  VerticalOrigin,
  Cartesian2,
  DistanceDisplayCondition,
  Viewer,
} from 'cesium'
import { fetchApi } from '../../lib/networkFetch'
import { attachDataSource, detachDataSource, feedPos, feedPoint } from './layerUtils'
import type { Stats } from '../../lib/types'

const DARKWEB_COLOR = '#9d4edd';

export function useDarkwebLayer({
  viewer,
  active,
  feedActive,
  canFetch,
  setStats,
  center,
}: {
  viewer: Viewer | null;
  active: boolean;
  feedActive: boolean;
  canFetch: boolean;
  setStats: React.Dispatch<React.SetStateAction<Stats>>;
  center?: { lat: number; lon: number };
}) {
  const srcRef = useRef<CustomDataSource | null>(null);

  const { data } = useQuery({
    queryKey: ['darkweb-mentions'],
    queryFn: async () => {
      const r = await fetchApi('/api/darkweb/mentions?limit=100');
      return r.json();
    },
    refetchInterval: 300000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('darkweb');
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

    const mentions = data?.mentions || [];
    const count = Math.min(mentions.length, 100);
    if (count === 0) {
      src.entities.resumeEvents();
      setStats((p: Stats) => ({ ...p, darkweb: 0 }));
      return;
    }

    const baseLat = center?.lat ?? 13.7;
    const baseLon = center?.lon ?? 100.5;

    // Place a cluster of points around the operator region with a jitter so they
    // do not stack. Dark web mentions usually have no geolocation.
    const plotted = Math.min(count, 50);
    for (let i = 0; i < plotted; i += 1) {
      const angle = (i / plotted) * Math.PI * 2;
      const radius = 0.5 + (i % 5) * 0.15;
      const lat = baseLat + Math.sin(angle) * radius;
      const lon = baseLon + Math.cos(angle) * radius;
      const m = mentions[i];
      const p = m.properties || {};
      const title = (p.name || ['Dark web mention'])[0].slice(0, 40);
      const engine = (p.source || ['darkweb'])[0];
      const url = (p.url || [''])[0];
      src.entities.add({
        position: feedPos(lon, lat),
        point: feedPoint(7, Color.fromCssColorString(DARKWEB_COLOR), { outlineWidth: 1 }),
        label: {
          text: title,
          font: '600 9px "Courier New"',
          fillColor: Color.fromCssColorString(DARKWEB_COLOR),
          outlineColor: Color.BLACK,
          outlineWidth: 2,
          style: LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: VerticalOrigin.BOTTOM,
          pixelOffset: new Cartesian2(0, -10),
          distanceDisplayCondition: new DistanceDisplayCondition(0, 8e6),
        },
        properties: {
          kind: 'darkweb',
          id: m.id,
          title,
          engine,
          url,
          datasets: m.datasets || [],
        },
      });
    }

    // Add a central summary label
    src.entities.add({
      position: feedPos(baseLon, baseLat),
      point: feedPoint(14, Color.fromCssColorString(DARKWEB_COLOR), { outlineWidth: 2 }),
      label: {
        text: `DARK WEB: ${count}`,
        font: '700 11px "Courier New"',
        fillColor: Color.fromCssColorString(DARKWEB_COLOR),
        outlineColor: Color.BLACK,
        outlineWidth: 2,
        style: LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: VerticalOrigin.TOP,
        pixelOffset: new Cartesian2(0, 10),
        distanceDisplayCondition: new DistanceDisplayCondition(0, 2e7),
      },
      properties: {
        kind: 'darkweb',
        summary: true,
        count,
      },
    });

    src.entities.resumeEvents();
    setStats((p: Stats) => ({ ...p, darkweb: count }));
  }, [data, active, setStats, center]);
}
