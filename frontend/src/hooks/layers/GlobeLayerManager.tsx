import React from 'react';
import { Viewer } from 'cesium';
import type { Stats, FeedHud, HeatmapMeta } from '../../lib/types';
import type { ThemeId } from '../../lib/theme';
import { useAircraftLayer } from './useAircraftLayer';
import { useSatellitesLayer } from './useSatellitesLayer';
import { useQuakesLayer } from './useQuakesLayer';
import { useEventsLayer } from './useEventsLayer';
import { useNodesLayer } from './useNodesLayer';
import { useMilitaryLayer } from './useMilitaryLayer';
import { useSpaceweatherLayer } from './useSpaceweatherLayer';
import { useWildfiresLayer } from './useWildfiresLayer';
import { useLightningLayer } from './useLightningLayer';
import { useTransitLayer } from './useTransitLayer';
import { useMaritimeLayer } from './useMaritimeLayer';
import { useGeopoliticsLayer } from './useGeopoliticsLayer';
import { useGdacsLayer } from './useGdacsLayer';
import { useHazardsLayer } from './useHazardsLayer';
import { useOutagesLayer } from './useOutagesLayer';
import { useVolcanoesLayer } from './useVolcanoesLayer';
import { useAirqualityLayer } from './useAirqualityLayer';
import { usePegelLayer } from './usePegelLayer';
import { useEnergyLayer } from './useEnergyLayer';
import { useHeatmapLayer } from './useHeatmapLayer';
import { useWeatherLayer } from './useWeatherLayer';
import { useTrafficCamsLayer } from './useTrafficCamsLayer';
import { useIntelLayer } from './useIntelLayer';
import { useDarkwebLayer } from './useDarkwebLayer';
import { useSatelliteChangeLayer } from './useSatelliteChangeLayer';
import { useDetectionBoxes } from './useDetectionBoxes';
import { usePiAisLayer } from './usePiAisLayer';
import { useAcledLayer } from './useAcledLayer';
import { useOsmLayer } from './useOsmLayer';
import { useWeatherForecastLayer } from './useWeatherForecastLayer';
import { useAgentSwarm } from './useAgentSwarm';

export function GlobeLayerManager({
  viewer,
  layers,
  feedActive,
  canFetch,
  setStats,
  setFeedHud,
  satGroup,
  orbitsActive,
  transitCity,
  scrubT,
  timelineHours,
  setAircraftSource,
  heatmapOn,
  setHeatmapMeta,
  setSanctionedMmsi,
  theme = 'cyber',
}: {
  viewer: Viewer | null;
  layers: Record<string, boolean>;
  feedActive: boolean;
  canFetch: boolean;
  setStats: React.Dispatch<React.SetStateAction<Stats>>;
  setFeedHud: React.Dispatch<React.SetStateAction<FeedHud>>;
  satGroup: string;
  orbitsActive: boolean;
  transitCity: string;
  scrubT: number;
  timelineHours: number;
  setAircraftSource: React.Dispatch<React.SetStateAction<string>>;
  heatmapOn: boolean;
  setHeatmapMeta: React.Dispatch<React.SetStateAction<HeatmapMeta | null>>;
  setSanctionedMmsi: React.Dispatch<React.SetStateAction<Set<string>>>;
  theme?: ThemeId;
}) {
  // Pass down the props to individual hooks
  useAircraftLayer({
    viewer,
    active: layers.aircraft,
    feedActive,
    canFetch,
    setStats,
    setAircraftSource,
    theme,
  });
  useSatellitesLayer({
    viewer,
    active: layers.satellites,
    orbitsActive,
    satGroup,
    feedActive,
    setStats,
  });
  useQuakesLayer({
    viewer,
    active: layers.quakes,
    feedActive,
    canFetch,
    setStats,
    scrubT,
    timelineHours,
    theme,
  });
  useEventsLayer({
    viewer,
    active: layers.events,
    feedActive,
    canFetch,
    setStats,
    scrubT,
    timelineHours,
    theme,
  });
  useNodesLayer({ viewer, active: layers.nodes, feedActive, canFetch, setStats, theme });
  useMilitaryLayer({ viewer, active: layers.military, feedActive, canFetch, setStats, theme });
  useSpaceweatherLayer({ viewer, active: layers.spaceweather, feedActive, canFetch, setStats });
  useWildfiresLayer({
    viewer,
    active: layers.wildfires,
    feedActive,
    canFetch,
    setStats,
    setFeedHud,
    theme,
  });
  useLightningLayer({
    viewer,
    active: layers.lightning,
    feedActive,
    canFetch,
    setStats,
    setFeedHud,
  });
  useTransitLayer({ viewer, active: layers.transit, feedActive, canFetch, transitCity, setStats });
  useMaritimeLayer({
    viewer,
    active: layers.maritime,
    feedActive,
    canFetch,
    setStats,
    setSanctionedMmsi,
    theme,
  });
  useGeopoliticsLayer({
    viewer,
    active: layers.geopolitics,
    feedActive,
    canFetch,
    setStats,
    theme,
  });
  useGdacsLayer({ viewer, active: layers.gdacs, feedActive, canFetch, setStats, setFeedHud });
  useHazardsLayer({ viewer, active: layers.hazards, feedActive, canFetch, setStats, setFeedHud });
  useOutagesLayer({ viewer, active: layers.outages, feedActive, canFetch, setStats, setFeedHud });
  useVolcanoesLayer({ viewer, active: layers.volcanoes, feedActive, canFetch, setStats, theme });
  useAirqualityLayer({ viewer, active: layers.airquality, feedActive, canFetch, setStats });
  usePegelLayer({ viewer, active: layers.pegel, feedActive, canFetch, setStats, setFeedHud });
  useEnergyLayer({ viewer, active: layers.energy, feedActive, canFetch, setStats, setFeedHud });
  useWeatherLayer({
    viewer,
    active: layers.weather,
    feedActive,
    canFetch,
    setStats,
    region: 'thailand',
  });
  useTrafficCamsLayer({ viewer, active: layers.trafficCams, feedActive, canFetch, setStats });
  useIntelLayer({ viewer, active: layers.intelFt, feedActive, canFetch, setStats, theme });
  useDarkwebLayer({ viewer, active: layers.darkweb, feedActive, canFetch, setStats });
  useHeatmapLayer({ viewer, active: heatmapOn, feedActive, canFetch, setHeatmapMeta });
  useSatelliteChangeLayer({ viewer, active: layers.satelliteChange ?? false });
  useDetectionBoxes({
    viewer,
    active: layers.detectionBoxes ?? false,
    feedActive,
    canFetch,
    setStats,
  });
  usePiAisLayer({ viewer, active: layers.piAis ?? false, feedActive, canFetch, setStats });
  useAcledLayer({ viewer, active: layers.acled ?? false, feedActive, canFetch, setStats });
  useOsmLayer({ viewer, active: layers.osm ?? false, feedActive, canFetch, setStats });
  useWeatherForecastLayer({
    viewer,
    active: layers.weatherForecast ?? false,
    feedActive,
    canFetch,
    setStats,
  });
  useAgentSwarm({ viewer, active: true });

  return null;
}
