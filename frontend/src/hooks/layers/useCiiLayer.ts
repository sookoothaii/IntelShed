import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Color,
  LabelStyle,
  VerticalOrigin,
  HorizontalOrigin,
  Cartesian2,
  DistanceDisplayCondition,
  Viewer,
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource, feedPos, feedPoint } from './layerUtils';
import type { Stats } from '../../lib/types';

/** ISO2 → [lat, lon] centroid lookup for all countries in the CII engine. */
const COUNTRY_CENTROIDS: Record<string, [number, number]> = {
  TH: [15.87, 100.99],
  MM: [21.91, 95.96],
  LA: [19.86, 102.5],
  KH: [12.57, 104.99],
  VN: [14.06, 108.28],
  PH: [12.88, 121.77],
  MY: [4.21, 101.98],
  SG: [1.35, 103.82],
  BN: [4.54, 114.73],
  ID: [-2.52, 117.29],
  CN: [35.86, 104.2],
  JP: [36.2, 138.25],
  KR: [35.91, 127.77],
  IN: [20.59, 78.96],
  PK: [30.38, 69.35],
  BD: [23.68, 90.36],
  LK: [7.87, 80.77],
  AF: [33.94, 67.71],
  IR: [32.43, 53.69],
  IQ: [33.22, 43.68],
  SY: [34.8, 38.9],
  YE: [15.55, 48.52],
  SA: [23.89, 45.08],
  AE: [23.42, 53.85],
  IL: [31.05, 34.85],
  PS: [31.95, 35.23],
  JO: [30.59, 36.24],
  LB: [33.85, 35.86],
  TR: [38.96, 35.24],
  EG: [26.82, 30.8],
  LY: [26.34, 17.23],
  SD: [12.86, 30.22],
  SS: [6.88, 31.31],
  ET: [9.15, 40.49],
  SO: [5.15, 46.2],
  KE: [-0.02, 37.91],
  NG: [9.08, 8.68],
  ZA: [-30.56, 22.94],
  RU: [61.52, 105.32],
  UA: [48.38, 31.17],
  BY: [53.71, 27.95],
  PL: [51.92, 19.15],
  DE: [51.17, 10.45],
  FR: [46.23, 2.21],
  GB: [55.38, -3.44],
  US: [37.09, -95.71],
  CA: [56.13, -106.35],
  MX: [23.63, -102.55],
  BR: [-14.24, -51.93],
  AR: [-38.42, -63.62],
  CO: [4.57, -74.3],
  VE: [6.42, -66.59],
  CL: [-35.68, -71.54],
  PE: [-9.19, -75.0],
  BO: [-16.29, -63.59],
  AU: [-25.27, 133.78],
  NZ: [-40.9, 174.89],
  PG: [-6.31, 143.96],
  FJ: [-16.58, 179.41],
  KP: [40.34, 127.51],
  TW: [23.7, 120.96],
  HK: [22.32, 114.17],
  MO: [22.2, 113.55],
  KZ: [48.02, 66.92],
  UZ: [41.38, 64.59],
  TM: [38.97, 59.56],
  KG: [41.2, 74.77],
  TJ: [38.86, 71.28],
  MN: [46.86, 103.85],
  NP: [28.39, 84.12],
  BT: [27.51, 90.43],
  MV: [3.2, 73.22],
  TL: [-8.87, 125.73],
  ES: [40.46, -3.75],
  IT: [41.87, 12.57],
  PT: [39.4, -8.22],
  NL: [52.13, 5.29],
  BE: [50.5, 4.47],
  CH: [46.82, 8.23],
  AT: [47.52, 14.55],
  SE: [60.13, 18.64],
  NO: [60.47, 8.47],
  DK: [56.26, 9.5],
  FI: [61.92, 25.75],
  IE: [53.41, -8.24],
  GR: [39.07, 21.82],
  CZ: [49.82, 15.47],
  SK: [48.67, 19.7],
  HU: [47.16, 19.5],
  RO: [45.94, 24.97],
  BG: [42.73, 25.49],
  RS: [44.02, 21.0],
  HR: [45.1, 15.2],
  SI: [46.15, 14.99],
  BA: [43.92, 17.68],
  MK: [41.61, 21.75],
  AL: [41.15, 20.04],
  XK: [42.6, 20.9],
  MD: [47.41, 28.37],
  GE: [42.32, 43.36],
  AM: [40.07, 45.04],
  AZ: [40.14, 47.58],
};

interface CiiCountry {
  country_code: string;
  country_name: string;
  iso3: string;
  score: number;
  risk_band: string;
  conflict: number;
  economy: number;
  climate: number;
  governance: number;
  article_count: number;
  event_count: number;
  computed_at: string;
  delta_24h?: number | null;
  trend_7d?: string;
  trend_series?: number[];
}

interface CiiRankingsResponse {
  count: number;
  updated: string;
  countries: CiiCountry[];
}

/** Map 0-100 score → color (green→yellow→orange→red). */
function scoreColor(score: number): Color {
  const t = Math.min(1, score / 100);
  const hueDeg = (1 - t) * 120; // 120=green, 0=red
  const css = `hsla(${hueDeg.toFixed(0)}, 85%, ${(40 + t * 25).toFixed(0)}%, ${(0.35 + t * 0.5).toFixed(2)})`;
  return Color.fromCssColorString(css);
}

function riskBandLabel(band: string): string {
  switch (band) {
    case 'critical':
      return 'CRITICAL';
    case 'high':
      return 'HIGH';
    case 'elevated':
      return 'ELEVATED';
    case 'moderate':
      return 'MODERATE';
    default:
      return 'STABLE';
  }
}

export function useCiiLayer({
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
    queryKey: ['cii-rankings'],
    queryFn: async () => {
      const r = await fetchApi('/api/cii/rankings?limit=100');
      return r.json() as Promise<CiiRankingsResponse>;
    },
    refetchInterval: 300000,
    enabled: active && feedActive && canFetch,
  });

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('cii');
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
    for (const c of data.countries || []) {
      const centroid = COUNTRY_CENTROIDS[c.country_code];
      if (!centroid) continue;
      const [lat, lon] = centroid;
      const score = c.score ?? 0;
      const col = scoreColor(score);
      const band = riskBandLabel(c.risk_band);
      const delta = c.delta_24h;
      const deltaStr = delta != null ? ` Δ${delta > 0 ? '+' : ''}${delta.toFixed(1)}` : '';
      const showLabel = score >= 25;

      src.entities.add({
        position: feedPos(lon, lat),
        point: feedPoint(6 + Math.min(1, score / 100) * 16, col.withAlpha(0.85), {
          outlineWidth: 2,
        }),
        label: showLabel
          ? {
              text: `${c.country_name} ${score.toFixed(0)}${deltaStr}`,
              font: '600 10px "Courier New"',
              fillColor: col,
              outlineColor: Color.BLACK,
              outlineWidth: 2,
              style: LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: VerticalOrigin.BOTTOM,
              horizontalOrigin: HorizontalOrigin.CENTER,
              pixelOffset: new Cartesian2(0, -12),
              distanceDisplayCondition: new DistanceDisplayCondition(0, 4e7),
            }
          : undefined,
        properties: {
          kind: 'cii',
          country_code: c.country_code,
          country_name: c.country_name,
          score,
          risk_band: band,
          conflict: c.conflict,
          economy: c.economy,
          climate: c.climate,
          governance: c.governance,
          article_count: c.article_count,
          event_count: c.event_count,
          delta_24h: delta,
          trend_7d: c.trend_7d,
        },
      });
      n++;
    }

    src.entities.resumeEvents();
    setStats((p: Stats) => ({ ...p, cii: n }));
  }, [viewer, data, active, setStats]);
}
