/**
 * HUD Store — lightweight global state for cross-tab concerns (I10).
 *
 * NOTE: This is intentionally a custom pub/sub store, not Zustand. The
 * roadmap item I10 originally mentioned Zustand, but a zero-dependency
 * implementation is sufficient for the current scope (active tab, split view,
 * WS connection state, camera sync). If the state surface grows significantly,
 * Zustand can be introduced later without changing the public interface.
 *
 * Replaces prop drilling for globe camera sync between GLOBE and SPLIT tabs.
 */

export type TabKey =
  | 'globe'
  | 'map'
  | 'data'
  | 'chat'
  | 'news'
  | 'osint'
  | 'situations'
  | 'analysis';

export interface GlobeCameraState {
  lon: number;
  lat: number;
  height: number;
  pitch?: number;
  heading?: number;
}

export interface LayerVisibility {
  [key: string]: boolean;
}

export interface SatelliteChangeData {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    geometry: { type: 'Polygon'; coordinates: number[][][] };
    properties: {
      class: 'increase' | 'decrease';
      mean_delta: number;
      max_delta: number;
      min_delta: number;
      pixel_count: number;
      confidence: number;
    };
  }>;
  properties?: Record<string, unknown>;
  cached?: boolean;
}

interface HUDState {
  activeTab: TabKey;
  splitView: boolean;
  splitTab: TabKey | null;
  darkMode: boolean;
  globeCamera: GlobeCameraState | null;
  layerVisibility: LayerVisibility;
  wsConnected: boolean;
  agentBusConnected: boolean;
  satelliteChangeData: SatelliteChangeData | null;
}

type StateListener = (state: HUDState) => void;

class HUDStore {
  private state: HUDState;
  private listeners = new Set<StateListener>();

  constructor() {
    this.state = {
      activeTab: 'globe',
      splitView: false,
      splitTab: null,
      darkMode: true,
      globeCamera: null,
      layerVisibility: {},
      wsConnected: false,
      agentBusConnected: false,
      satelliteChangeData: null,
    };
  }

  getState(): HUDState {
    return { ...this.state };
  }

  subscribe(listener: StateListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  setState(partial: Partial<HUDState>): void {
    this.state = { ...this.state, ...partial };
    this.notify();
  }

  setActiveTab(tab: TabKey): void {
    this.setState({ activeTab: tab });
  }

  toggleSplitView(): void {
    this.setState({ splitView: !this.state.splitView });
  }

  setSplitTab(tab: TabKey | null): void {
    this.setState({ splitTab: tab });
  }

  toggleDarkMode(): void {
    this.setState({ darkMode: !this.state.darkMode });
  }

  setGlobeCamera(camera: GlobeCameraState): void {
    this.setState({ globeCamera: camera });
  }

  setLayerVisibility(layer: string, visible: boolean): void {
    this.setState({
      layerVisibility: { ...this.state.layerVisibility, [layer]: visible },
    });
  }

  setWSConnected(connected: boolean): void {
    this.setState({ wsConnected: connected });
  }

  setAgentBusConnected(connected: boolean): void {
    this.setState({ agentBusConnected: connected });
  }

  setSatelliteChangeData(data: SatelliteChangeData | null): void {
    this.setState({ satelliteChangeData: data });
  }

  private notify(): void {
    this.listeners.forEach((l) => {
      try {
        l(this.state);
      } catch {
        // listener errors are non-fatal
      }
    });
  }
}

export const hudStore = new HUDStore();
export type { HUDState, StateListener };
