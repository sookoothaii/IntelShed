import type { POI } from './pois';

export type LayerKey =
  | 'aircraft'
  | 'satellites'
  | 'orbits'
  | 'quakes'
  | 'events'
  | 'nodes'
  | 'military'
  | 'spaceweather'
  | 'geopolitics'
  | 'wildfires'
  | 'lightning'
  | 'transit'
  | 'trafficCams'
  | 'maritime'
  | 'gdacs'
  | 'hazards'
  | 'outages'
  | 'volcanoes'
  | 'airquality'
  | 'weather'
  | 'pegel'
  | 'energy'
  | 'osint'
  | 'intelFt'
  | 'darkweb'
  | 'satelliteChange'
  | 'detectionBoxes'
  | 'piAis'
  | 'cii';

export type GlobeAction =
  | { type: 'fly_to'; lat: number; lon: number; height: number; title: string; lines?: string[] }
  | { type: 'toggle_layer'; layer: LayerKey; enabled: boolean }
  | { type: 'toggle_heatmap'; enabled: boolean }
  | { type: 'set_vision'; mode: string };

export type ActionExecutor = {
  flyTo: (poi: POI) => void;
  toggleLayer: (layer: LayerKey, enabled: boolean) => void;
  setHeatmap: (on: boolean) => void;
  setVision: (mode: string) => void;
};

export function executeActions(actions: GlobeAction[], exec: ActionExecutor): void {
  for (const action of actions) {
    switch (action.type) {
      case 'fly_to':
        exec.flyTo({
          name: action.title,
          lon: action.lon,
          lat: action.lat,
          height: action.height,
        });
        break;
      case 'toggle_layer':
        exec.toggleLayer(action.layer, action.enabled);
        break;
      case 'toggle_heatmap':
        exec.setHeatmap(action.enabled);
        break;
      case 'set_vision':
        exec.setVision(action.mode);
        break;
    }
  }
}
