import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Cartesian3,
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
import type { Stats, FeedHud } from '../../lib/types';

const hazardColor = (severity: string) => {
  const s = (severity || '').toLowerCase();
  if (s === 'extreme') return '#ff2d00';
  if (s === 'severe') return '#ff6b35';
  if (s === 'moderate') return '#ffd23f';
  return '#22d3ee';
};

export function useHazardsLayer({
  viewer,
  active,
  feedActive,
  canFetch,
  setStats,
  setFeedHud,
}: {
  viewer: Viewer | null;
  active: boolean;
  feedActive: boolean;
  canFetch: boolean;
  setStats: React.Dispatch<React.SetStateAction<Stats>>;
  setFeedHud: React.Dispatch<React.SetStateAction<FeedHud>>;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);

  const { data } = useQuery({
    queryKey: ['hazards'],
    queryFn: async () => {
      const r = await fetchApi('/api/hazards?limit=80');
      const d = await r.json();

      // Also fetch GDELT geo if possible
      try {
        const gr = await fetchApi('/api/gdelt/geo?timespan=1d&maxrecords=40');
        d.gdelt = await gr.json();
      } catch {
        d.gdelt = null;
      }
      return d;
    },
    refetchInterval: 300000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('hazards');
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
    if (!data || !srcRef.current || !active) return;
    const src = srcRef.current;

    src.entities.suspendEvents();
    src.entities.removeAll();

    let n = 0;
    for (const a of data.alerts || []) {
      if (a.lon == null || a.lat == null) continue;
      const col = Color.fromCssColorString(hazardColor(a.severity));
      src.entities.add({
        position: feedPos(a.lon, a.lat),
        point: feedPoint(10, col.withAlpha(0.92), { outlineWidth: 1 }),
        label: {
          text: (a.event || 'HAZARD').slice(0, 28),
          font: '600 8px "Courier New"',
          fillColor: col,
          outlineColor: Color.BLACK,
          outlineWidth: 2,
          style: LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: VerticalOrigin.BOTTOM,
          pixelOffset: new Cartesian2(0, -8),
          distanceDisplayCondition: new DistanceDisplayCondition(0, 8e6),
        },
        properties: {
          kind: 'hazard',
          event: a.event,
          headline: a.headline,
          severity: a.severity,
          urgency: a.urgency,
          area_desc: a.area_desc,
          feed: a.feed,
          effective: a.effective,
          expires: a.expires,
        },
      });
      n++;
    }

    if (data.gdelt && data.gdelt.events) {
      for (const ev of data.gdelt.events) {
        if (ev.lon == null || ev.lat == null) continue;
        src.entities.add({
          position: Cartesian3.fromDegrees(ev.lon, ev.lat, 0),
          point: {
            pixelSize: 7,
            color: Color.fromCssColorString('#c084fc').withAlpha(0.85),
            outlineColor: Color.WHITE,
            outlineWidth: 1,
          },
          properties: {
            kind: 'gdelt_geo',
            title: ev.name,
            url: ev.url,
            date: ev.date,
          },
        });
        n++;
      }
    }

    src.entities.resumeEvents();

    setStats((p: Stats) => ({ ...p, hazards: data.count ?? n }));
    setFeedHud((p: FeedHud) => ({
      ...p,
      hazards:
        data.geocoded != null && data.geocoded < (data.count ?? n) ? `${data.geocoded} map` : '',
    }));
  }, [viewer, data, active, setStats, setFeedHud]);
}
