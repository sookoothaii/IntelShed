import { useCallback, useEffect, useRef, useState } from 'react';

declare global {
  interface Window {
    windyInit?: (options: Record<string, unknown>, callback: (api: WindyApi) => void) => void;
    L?: unknown;
  }
}

type WindyStore = {
  get: (key: string) => unknown;
  getAllowed: (key: string) => string[] | string;
  set: (key: string, value: unknown) => boolean;
  on: (key: string, cb: (value: unknown) => void) => void;
};

type WindyApi = {
  map?: { setView?: (coords: [number, number], zoom: number) => void };
  store?: WindyStore;
  picker?: {
    open: (coords: { lat: number; lon: number }) => void;
    on: (
      event: string,
      cb: (data: { lat: number; lon: number; values: unknown; overlay: string }) => void,
    ) => void;
  };
};

/** Windy overlay id → HUD label (English). No "thunder" layer in Windy API — use rain / cape. */
const OVERLAY_LABELS: Record<string, string> = {
  wind: 'WIND',
  gust: 'GUSTS',
  gustAccu: 'GUST ACCU',
  rain: 'RAIN',
  rainAccu: 'RAIN ACCU',
  snowAccu: 'SNOW ACCU',
  snowcover: 'SNOW',
  ptype: 'PRECIP TYPE',
  temp: 'TEMP',
  dewpoint: 'DEW POINT',
  rh: 'HUMIDITY',
  deg0: 'FREEZING LV',
  clouds: 'CLOUDS',
  hclouds: 'HIGH CLOUDS',
  mclouds: 'MID CLOUDS',
  lclouds: 'LOW CLOUDS',
  fog: 'FOG',
  cape: 'STORMS',
  pressure: 'PRESSURE',
  satellite: 'SATELLITE',
  waves: 'WAVES',
  swell1: 'SWELL',
  currents: 'CURRENTS',
  dustsm: 'DUST',
  so2sm: 'SO2',
  cosc: 'CO',
};

const OVERLAY_ORDER = [
  'wind',
  'rain',
  'rainAccu',
  'ptype',
  'clouds',
  'cape',
  'temp',
  'pressure',
  'satellite',
  'gust',
  'rh',
  'dewpoint',
  'fog',
  'hclouds',
  'mclouds',
  'lclouds',
  'snowAccu',
  'waves',
];

function sortOverlays(allowed: string[]): string[] {
  const set = new Set(allowed);
  const ordered = OVERLAY_ORDER.filter((id) => set.has(id));
  for (const id of allowed) {
    if (!ordered.includes(id)) ordered.push(id);
  }
  return ordered;
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) {
      resolve();
      return;
    }
    const el = document.createElement('script');
    el.src = src;
    el.async = true;
    el.onload = () => resolve();
    el.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.body.appendChild(el);
  });
}

export default function WindyMapOverlay({
  open,
  onClose,
  lat,
  lon,
  mapKey,
}: {
  open: boolean;
  onClose: () => void;
  lat: number;
  lon: number;
  mapKey: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);
  const [overlays, setOverlays] = useState<string[]>([]);
  const [activeOverlay, setActiveOverlay] = useState('wind');
  const apiRef = useRef<WindyApi | null>(null);

  const applyOverlay = useCallback((overlayId: string) => {
    const store = apiRef.current?.store;
    if (!store) return;
    const ok = store.set('overlay', overlayId);
    if (ok) setActiveOverlay(overlayId);
  }, []);

  const initMap = useCallback(async () => {
    if (!open || !mapKey || !hostRef.current) return;
    setStatus('loading');
    setError(null);
    setOverlays([]);
    try {
      await loadScript('https://unpkg.com/leaflet@1.4.0/dist/leaflet.js');
      await loadScript('https://api.windy.com/assets/map-forecast/libBoot.js');
      if (!window.windyInit) throw new Error('Windy libBoot not available');

      hostRef.current.innerHTML = '<div id="windy"></div>';

      await new Promise<void>((resolve, reject) => {
        let done = false;
        const timer = window.setTimeout(() => {
          if (!done) reject(new Error('Windy init timeout'));
        }, 25000);
        window.windyInit!(
          {
            key: mapKey,
            lat,
            lon,
            zoom: 6,
            overlay: 'wind',
            hourFormat: '24h',
            favOverlays: [
              'wind',
              'rain',
              'rainAccu',
              'clouds',
              'temp',
              'cape',
              'pressure',
              'satellite',
              'ptype',
              'gust',
            ],
          },
          (api) => {
            done = true;
            window.clearTimeout(timer);
            apiRef.current = api;
            const store = api.store;
            if (store) {
              const allowed = store.getAllowed('overlay');
              const list = Array.isArray(allowed) ? sortOverlays(allowed) : ['wind'];
              setOverlays(list);
              const current = String(store.get('overlay') || 'wind');
              setActiveOverlay(list.includes(current) ? current : list[0] || 'wind');
              store.on('overlay', (ov) => {
                if (typeof ov === 'string') setActiveOverlay(ov);
              });
            }
            resolve();
          },
        );
      });

      setStatus('ready');
    } catch (e) {
      setStatus('error');
      setError((e as Error).message);
    }
  }, [open, mapKey, lat, lon]);

  useEffect(() => {
    if (!open) {
      setStatus('idle');
      apiRef.current = null;
      if (hostRef.current) hostRef.current.innerHTML = '';
      return;
    }
    initMap();
  }, [open, initMap]);

  useEffect(() => {
    if (!open || status !== 'ready' || !apiRef.current?.map?.setView) return;
    apiRef.current.map.setView([lat, lon], 6);
  }, [lat, lon, open, status]);

  if (!open) return null;

  const mapTestingTier =
    overlays.length <= 3 && overlays.every((id) => ['wind', 'temp', 'pressure'].includes(id));

  return (
    <div className="windy-map-overlay" role="dialog" aria-label="Windy weather map">
      <div className="windy-map-toolbar">
        <span className="windy-map-title">
          WINDY MAP · {lat.toFixed(2)}, {lon.toFixed(2)}
        </span>
        <button type="button" className="close-btn" onClick={onClose}>
          CLOSE
        </button>
      </div>

      {status === 'ready' && overlays.length > 0 && (
        <div className="windy-layer-bar">
          {overlays.map((id) => (
            <button
              key={id}
              type="button"
              className={activeOverlay === id ? 'windy-layer-btn active' : 'windy-layer-btn'}
              onClick={() => applyOverlay(id)}
              title={id}
            >
              {OVERLAY_LABELS[id] || id.toUpperCase()}
            </button>
          ))}
        </div>
      )}

      {status === 'ready' && (
        <p className="windy-layer-hint">
          {mapTestingTier ? (
            <>
              <strong>Map Testing key</strong> — only WIND, TEMP, PRESSURE on this map. Rain,
              clouds, and STORMS (CAPE) need{' '}
              <a
                href="https://api.windy.com/map-forecast/pricing"
                target="_blank"
                rel="noopener noreferrer"
              >
                Map Forecast Professional
              </a>
              . For rain now: enable globe layer <strong>WEATHER</strong> and use DATA → WEATHER
              (Point Forecast). Bottom slider = forecast hour.
            </>
          ) : (
            <>
              <strong>STORMS</strong> = CAPE (convection energy, not a thunder radar). Windy has no
              separate thunder layer — use <strong>RAIN</strong> or <strong>STORMS</strong>. Bottom
              slider = forecast hour.
            </>
          )}
        </p>
      )}

      {status === 'loading' && (
        <div className="health-status pending windy-map-status">LOADING WINDY MAP…</div>
      )}
      {status === 'error' && (
        <div className="health-status pending windy-map-status">
          {error || 'Windy map failed to load'}
        </div>
      )}
      <div ref={hostRef} className="windy-map-host" />
      <p className="windy-map-credit">
        Weather visualization via{' '}
        <a href="https://www.windy.com" target="_blank" rel="noopener noreferrer">
          Windy.com
        </a>
      </p>
    </div>
  );
}
