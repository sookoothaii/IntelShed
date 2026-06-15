import React from 'react';
import { Viewer } from 'cesium';
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
  setSanctionedMmsi
}: {
  viewer: Viewer | null;
  layers: Record<string, boolean>;
  feedActive: boolean;
  canFetch: boolean;
  setStats: React.Dispatch<React.SetStateAction<any>>;
  setFeedHud: React.Dispatch<React.SetStateAction<any>>;
  satGroup: string;
  orbitsActive: boolean;
  transitCity: string;
  scrubT: number;
  timelineHours: number;
  setAircraftSource: React.Dispatch<React.SetStateAction<string>>;
  heatmapOn: boolean;
  setHeatmapMeta: React.Dispatch<React.SetStateAction<any>>;
  setSanctionedMmsi: React.Dispatch<React.SetStateAction<Set<string>>>;
}) {
  // Pass down the props to individual hooks
  useAircraftLayer({ viewer, active: layers.aircraft, feedActive, canFetch, setStats, setAircraftSource });
  useSatellitesLayer({ viewer, active: layers.satellites, orbitsActive, satGroup, feedActive, setStats });
  useQuakesLayer({ viewer, active: layers.quakes, feedActive, canFetch, setStats, scrubT, timelineHours });
  useEventsLayer({ viewer, active: layers.events, feedActive, canFetch, setStats, scrubT, timelineHours });
  useNodesLayer({ viewer, active: layers.nodes, feedActive, canFetch, setStats });
  useMilitaryLayer({ viewer, active: layers.military, feedActive, canFetch, setStats });
  useSpaceweatherLayer({ viewer, active: layers.spaceweather, feedActive, canFetch, setStats });
  useWildfiresLayer({ viewer, active: layers.wildfires, feedActive, canFetch, setStats, setFeedHud });
  useLightningLayer({ viewer, active: layers.lightning, feedActive, canFetch, setStats, setFeedHud });
  useTransitLayer({ viewer, active: layers.transit, feedActive, canFetch, transitCity, setStats });
  useMaritimeLayer({ viewer, active: layers.maritime, feedActive, canFetch, setStats, setSanctionedMmsi });
  useGeopoliticsLayer({ viewer, active: layers.geopolitics, feedActive, canFetch, setStats });
  useGdacsLayer({ viewer, active: layers.gdacs, feedActive, canFetch, setStats, setFeedHud });
  useHazardsLayer({ viewer, active: layers.hazards, feedActive, canFetch, setStats, setFeedHud });
  useOutagesLayer({ viewer, active: layers.outages, feedActive, canFetch, setStats, setFeedHud });
  useVolcanoesLayer({ viewer, active: layers.volcanoes, feedActive, canFetch, setStats });
  useAirqualityLayer({ viewer, active: layers.airquality, feedActive, canFetch, setStats });
  usePegelLayer({ viewer, active: layers.pegel, feedActive, canFetch, setStats, setFeedHud });
  useEnergyLayer({ viewer, active: layers.energy, feedActive, canFetch, setStats, setFeedHud });
  useHeatmapLayer({ viewer, active: heatmapOn, feedActive, canFetch, setHeatmapMeta });

  return null;
}
