import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Cartesian3,
  Color,
  LabelStyle,
  VerticalOrigin,
  HorizontalOrigin,
  Cartesian2,
  DistanceDisplayCondition,
  Viewer,
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource } from './layerUtils';
import type { Stats, WeatherCell } from '../../lib/types';

function tempColor(c: number | null | undefined): string {
  if (c == null) return '#6f8c84';
  if (c >= 35) return '#ff2d00';
  if (c >= 30) return '#ff6b35';
  if (c >= 22) return '#ffd23f';
  if (c >= 10) return '#00e5a0';
  return '#4fc3f7';
}

function precipColor(mm: number | null | undefined): string {
  if (mm == null || mm < 0.1) return tempColor(undefined);
  if (mm >= 10) return '#1a33cc';
  if (mm >= 3) return '#2266ff';
  if (mm >= 1) return '#4fc3f7';
  return '#00aaff';
}

function cellColor(t: number | null | undefined, precip: number | null | undefined): string {
  if (precip != null && precip >= 0.3) return precipColor(precip);
  return tempColor(t);
}

export function useWeatherLayer({
  viewer,
  active,
  feedActive,
  canFetch,
  setStats,
  region = 'thailand',
}: {
  viewer: Viewer | null;
  active: boolean;
  feedActive: boolean;
  canFetch: boolean;
  setStats: React.Dispatch<React.SetStateAction<Stats>>;
  region?: string;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);

  const { data } = useQuery({
    queryKey: ['windy-grid', region],
    queryFn: async () => {
      const r = await fetchApi(`/api/windy/grid?region=${encodeURIComponent(region)}`);
      if (!r.ok) throw new Error(`${r.status}`);
      return r.json();
    },
    refetchInterval: 900000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('weather');
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

    for (const cell of (data.cells || []) as WeatherCell[]) {
      if (cell.lon == null || cell.lat == null) continue;
      const t = cell.temperature_c as number | null | undefined;
      const precip = cell.precip_mm_3h as number | null | undefined;
      const col = Color.fromCssColorString(cellColor(t, precip));
      const lines: string[] = [];
      if (t != null) lines.push(`${Math.round(t)}°`);
      if (precip != null && precip >= 0.1) lines.push(`${precip.toFixed(1)}mm`);
      const label = lines.length ? lines.join('\n') : '—';
      const wind = cell.wind_speed_ms != null ? ` · ${cell.wind_speed_ms} m/s` : '';
      const rain = precip != null && precip >= 0.1 ? ` · rain 3h ${precip.toFixed(1)} mm` : '';
      src.entities.add({
        position: Cartesian3.fromDegrees(cell.lon, cell.lat, 0),
        point: {
          pixelSize: precip != null && precip >= 1 ? 14 : 10,
          color: col.withAlpha(0.9),
          outlineColor: Color.BLACK.withAlpha(0.5),
          outlineWidth: 1,
        },
        label: {
          text: label,
          font: '600 10px JetBrains Mono, monospace',
          fillColor: Color.WHITE,
          outlineColor: Color.BLACK,
          outlineWidth: 2,
          style: LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: VerticalOrigin.BOTTOM,
          horizontalOrigin: HorizontalOrigin.CENTER,
          pixelOffset: new Cartesian2(0, -16),
          distanceDisplayCondition: new DistanceDisplayCondition(0, 8_000_000),
        },
        description: `Temp ${t ?? '—'}°C${wind}${rain}`,
        properties: {
          kind: 'weather',
          lat: cell.lat,
          lon: cell.lon,
          temperature_c: t,
          wind_speed_ms: cell.wind_speed_ms,
          precip_mm_3h: precip,
        },
      });
    }

    src.entities.resumeEvents();
    setStats((p: Stats) => ({ ...p, weather: data.count ?? 0 }));
  }, [data, active, setStats]);
}
