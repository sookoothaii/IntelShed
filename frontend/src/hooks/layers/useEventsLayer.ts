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
import { feedPos, feedPoint, timelineCutoffMs, parseEventMs } from './layerUtils';
import type { Stats } from '../../lib/types';
import { feedMarkerColor, isMssTheme } from './markerPalette';
import type { ThemeId } from '../../lib/theme';

const eventColor = (cat: string) => {
  const c = (cat || '').toLowerCase();
  if (c.includes('fire')) return '#ff6b35';
  if (c.includes('volcano')) return '#ff2d00';
  if (c.includes('storm') || c.includes('cyclone')) return '#00d4ff';
  if (c.includes('ice') || c.includes('snow')) return '#e0f7ff';
  if (c.includes('flood') || c.includes('water')) return '#4dabf7';
  return '#ffd23f';
};

function mssEventColor(cat: string): Color {
  return feedMarkerColor('events', Color.fromCssColorString(eventColor(cat)));
}

export function useEventsLayer({
  viewer,
  active,
  feedActive,
  canFetch,
  setStats,
  scrubT,
  timelineHours,
  theme: _theme = 'cyber',
}: {
  viewer: Viewer | null;
  active: boolean;
  feedActive: boolean;
  canFetch: boolean;
  setStats: React.Dispatch<React.SetStateAction<Stats>>;
  scrubT: number;
  timelineHours: number;
  theme?: ThemeId;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);

  const { data } = useQuery({
    queryKey: ['events'],
    queryFn: async () => {
      const r = await fetchApi('/api/events?limit=120');
      return r.json();
    },
    refetchInterval: 60000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('events');
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

    const cutoff = timelineCutoffMs(scrubT, timelineHours);
    const list = (data.events || []).filter(
      (ev: Record<string, unknown>) => parseEventMs(ev.date as string) <= cutoff,
    );

    src.entities.suspendEvents();
    src.entities.removeAll();

    let n = 0;
    for (const ev of list) {
      if (ev.lon == null || ev.lat == null) continue;
      n++;
      const col = isMssTheme()
        ? mssEventColor(ev.category)
        : Color.fromCssColorString(eventColor(ev.category));
      src.entities.add({
        position: feedPos(ev.lon, ev.lat),
        point: feedPoint(9, col.withAlpha(0.9), { outlineWidth: 1 }),
        label: {
          text: ev.category,
          font: '600 10px "Courier New"',
          fillColor: col,
          outlineColor: Color.BLACK,
          outlineWidth: 2,
          style: LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: VerticalOrigin.BOTTOM,
          pixelOffset: new Cartesian2(0, -10),
          distanceDisplayCondition: new DistanceDisplayCondition(0, 1.5e7),
        },
        properties: { kind: 'event', title: ev.title, category: ev.category, date: ev.date },
      });
    }

    src.entities.resumeEvents();
    setStats((p: Stats) => ({ ...p, events: n }));
  }, [viewer, data, active, scrubT, timelineHours, setStats]);
}
