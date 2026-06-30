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
import type { Stats } from '../../lib/types';

const severityColor = (sev: string | undefined) => {
  if (sev === 'high') return '#ff2d00';
  if (sev === 'medium') return '#ff6b35';
  return '#00e5a0';
};

export function useWeatherForecastLayer({
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

  const { data } = useQuery({
    queryKey: ['weather-forecast'],
    queryFn: async () => {
      const r = await fetchApi('/api/weather/forecast');
      return r.json();
    },
    refetchInterval: 3600000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('weatherForecast');
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

    for (const city of data.cities || []) {
      if (city.lon == null || city.lat == null) continue;
      const sev = city.severity || 'low';
      const col = Color.fromCssColorString(severityColor(sev));
      const label = `${city.city}: ${city.severe_count || 0} severe days`;
      src.entities.add({
        position: Cartesian3.fromDegrees(city.lon, city.lat, 0),
        point: {
          pixelSize: sev === 'high' ? 14 : 10,
          color: col.withAlpha(0.9),
          outlineColor: Color.BLACK,
          outlineWidth: 1,
        },
        label: {
          text: label,
          font: '600 9px "Courier New"',
          fillColor: col,
          outlineColor: Color.BLACK,
          outlineWidth: 2,
          style: LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: VerticalOrigin.BOTTOM,
          pixelOffset: new Cartesian2(0, -10),
          distanceDisplayCondition: new DistanceDisplayCondition(0, 1e7),
        },
        properties: {
          kind: 'weatherForecast',
          city: city.city,
          severity: sev,
          severe_count: city.severe_count,
          max_temp: city.max_temp,
          min_temp: city.min_temp,
          precipitation: city.precipitation,
        },
      });
    }
    src.entities.resumeEvents();
    setStats((p: Stats) => ({ ...p, weatherForecast: (data?.cities || []).length }));
  }, [viewer, data, active, setStats]);
}
