import type { GlobeAction, LayerKey } from './globeActions';

export type IntentResult = {
  actions: GlobeAction[];
  explanation: string;
  matched: string[];
};

type LayerRule = {
  keywords: string[];
  layer: LayerKey;
  label: string;
};

const LAYER_RULES: LayerRule[] = [
  {
    keywords: ['quake', 'seismic', 'earthquake', 'tremor'],
    layer: 'quakes',
    label: 'seismic events',
  },
  { keywords: ['wildfire', 'fire', 'burning', 'blaze'], layer: 'wildfires', label: 'wildfires' },
  { keywords: ['lightning', 'strike', 'thunder'], layer: 'lightning', label: 'lightning' },
  { keywords: ['volcano', 'eruption', 'lava', 'magma'], layer: 'volcanoes', label: 'volcanoes' },
  {
    keywords: ['storm', 'cyclone', 'hurricane', 'typhoon', 'gdacs', 'disaster'],
    layer: 'gdacs',
    label: 'disaster alerts',
  },
  {
    keywords: ['hazard', 'warning', 'cap', 'weather alert'],
    layer: 'hazards',
    label: 'weather warnings',
  },
  {
    keywords: ['ship', 'vessel', 'ais', 'maritime', 'boat', 'cargo', 'tanker'],
    layer: 'maritime',
    label: 'maritime traffic',
  },
  {
    keywords: ['aircraft', 'plane', 'flight', 'aviation', 'adsb'],
    layer: 'aircraft',
    label: 'aircraft tracking',
  },
  {
    keywords: ['military', 'war', 'conflict', 'armed'],
    layer: 'military',
    label: 'military assets',
  },
  {
    keywords: ['satellite', 'orbit', 'leo', 'gps', 'starlink'],
    layer: 'satellites',
    label: 'satellites',
  },
  {
    keywords: ['outage', 'internet', 'disconnect', 'blackout'],
    layer: 'outages',
    label: 'internet outages',
  },
  {
    keywords: ['geopolitic', 'crisis', 'tension', 'sanction'],
    layer: 'geopolitics',
    label: 'geopolitical crises',
  },
  { keywords: ['osint', 'intel', 'entity', 'ftm'], layer: 'osint', label: 'OSINT entities' },
  {
    keywords: ['darkweb', 'darknet', 'onion', 'tor'],
    layer: 'darkweb',
    label: 'darkweb intelligence',
  },
  {
    keywords: ['detection', 'box', 'anomaly', 'fusion'],
    layer: 'detectionBoxes',
    label: 'detection boxes',
  },
  {
    keywords: ['weather', 'temperature', 'wind', 'precipitation'],
    layer: 'weather',
    label: 'weather data',
  },
  {
    keywords: ['air quality', 'pollution', 'aqi', 'pm25', 'smog', 'haze'],
    layer: 'airquality',
    label: 'air quality',
  },
  { keywords: ['energy', 'power', 'electricity', 'grid'], layer: 'energy', label: 'energy data' },
  {
    keywords: ['flood', 'river', 'gauge', 'pegel', 'water level'],
    layer: 'pegel',
    label: 'river gauges',
  },
  { keywords: ['node', 'pi', 'edge', 'raspberry'], layer: 'nodes', label: 'edge nodes' },
  {
    keywords: ['transit', 'bus', 'train', 'metro', 'public transport'],
    layer: 'transit',
    label: 'transit',
  },
  { keywords: ['traffic cam', 'webcam', 'camera'], layer: 'trafficCams', label: 'traffic cameras' },
  {
    keywords: ['space weather', 'solar', 'kp index', 'geomagnetic', 'aurora'],
    layer: 'spaceweather',
    label: 'space weather',
  },
  {
    keywords: ['intel', 'ftm', 'follow the money', 'graph'],
    layer: 'intelFt',
    label: 'intel graph',
  },
  {
    keywords: ['satellite change', 'change detection', 'diff'],
    layer: 'satelliteChange',
    label: 'satellite change detection',
  },
  { keywords: ['pi ais', 'edge ais', 'raspberry ais'], layer: 'piAis', label: 'Pi AIS receiver' },
];

const VISION_RULES: { keywords: string[]; mode: string; label: string }[] = [
  { keywords: ['night vision', 'nvg', 'green mode'], mode: 'nvg', label: 'night vision' },
  { keywords: ['thermal', 'heat vision', 'ir mode'], mode: 'thermal', label: 'thermal' },
  { keywords: ['crt', 'retro', 'old screen'], mode: 'crt', label: 'CRT' },
  { keywords: ['night mode', 'dark mode', 'dim'], mode: 'night', label: 'night' },
  {
    keywords: ['normal', 'optical', 'default vision', 'clear'],
    mode: 'normal',
    label: 'normal optics',
  },
];

const HEATMAP_KEYWORDS = ['heatmap', 'heat map', 'fusion', 'hotspot', 'hot spot'];

const TOGGLE_OFF = ['hide', 'disable', 'turn off', 'deactivate', 'remove'];
const FLY_KEYWORDS = [
  'fly to',
  'go to',
  'zoom to',
  'focus on',
  'show me',
  'navigate to',
  'look at',
  'center on',
];
const RESET_KEYWORDS = ['reset', 'clear all', 'start over', 'default view'];
const OVERVIEW_KEYWORDS = ['overview', 'global view', 'world view', 'zoom out', 'earth'];

const BUILTIN_PLACES: Record<string, { lat: number; lon: number; height: number }> = {
  bangkok: { lat: 13.7563, lon: 100.5018, height: 200000 },
  thailand: { lat: 15.87, lon: 100.9925, height: 800000 },
  phuket: { lat: 7.8804, lon: 98.3923, height: 50000 },
  'chiang mai': { lat: 18.7883, lon: 98.9853, height: 50000 },
  pattaya: { lat: 12.9236, lon: 100.8825, height: 30000 },
  'koh samui': { lat: 9.5018, lon: 99.9363, height: 40000 },
  iran: { lat: 32.4279, lon: 53.688, height: 800000 },
  tehran: { lat: 35.6892, lon: 51.389, height: 100000 },
  israel: { lat: 31.0461, lon: 34.8516, height: 400000 },
  'tel aviv': { lat: 32.0853, lon: 34.7818, height: 50000 },
  gaza: { lat: 31.3547, lon: 34.3088, height: 30000 },
  'strait of hormuz': { lat: 26.5707, lon: 56.2417, height: 100000 },
  'persian gulf': { lat: 26.5, lon: 52.5, height: 500000 },
  'red sea': { lat: 22.0, lon: 38.0, height: 800000 },
  'suez canal': { lat: 30.0, lon: 32.5, height: 100000 },
  ukraine: { lat: 48.3794, lon: 31.1656, height: 600000 },
  kyiv: { lat: 50.4501, lon: 30.5234, height: 80000 },
  taiwan: { lat: 23.6978, lon: 120.9605, height: 300000 },
  taipei: { lat: 25.033, lon: 121.5654, height: 50000 },
  'south china sea': { lat: 15.0, lon: 115.0, height: 800000 },
  malacca: { lat: 2.5, lon: 101.0, height: 300000 },
  'strait of malacca': { lat: 2.5, lon: 101.0, height: 300000 },
  myanmar: { lat: 21.9139, lon: 95.956, height: 500000 },
  yangon: { lat: 16.8409, lon: 96.1735, height: 80000 },
  singapore: { lat: 1.3521, lon: 103.8198, height: 50000 },
  'hong kong': { lat: 22.3193, lon: 114.1694, height: 50000 },
  tokyo: { lat: 35.6762, lon: 139.6503, height: 50000 },
  seoul: { lat: 37.5665, lon: 126.978, height: 50000 },
  beijing: { lat: 39.9042, lon: 116.4074, height: 100000 },
  shanghai: { lat: 31.2304, lon: 121.4737, height: 80000 },
  'new york': { lat: 40.7128, lon: -74.006, height: 4000 },
  london: { lat: 51.5074, lon: -0.1278, height: 30000 },
  paris: { lat: 48.8566, lon: 2.3522, height: 20000 },
  berlin: { lat: 52.52, lon: 13.405, height: 30000 },
  dubai: { lat: 25.197, lon: 55.274, height: 25000 },
  sydney: { lat: -33.8568, lon: 151.2153, height: 30000 },
  'san francisco': { lat: 37.8199, lon: -122.4783, height: 30000 },
  washington: { lat: 38.8977, lon: -77.0365, height: 30000 },
  moscow: { lat: 55.7558, lon: 37.6173, height: 80000 },
  beirut: { lat: 33.8938, lon: 35.5018, height: 30000 },
  damascus: { lat: 33.5138, lon: 36.2765, height: 30000 },
  yemen: { lat: 15.5527, lon: 48.5165, height: 300000 },
  sanaa: { lat: 15.3694, lon: 44.191, height: 40000 },
  houthi: { lat: 15.5527, lon: 48.5165, height: 300000 },
  'bab el-mandeb': { lat: 12.6, lon: 43.3, height: 100000 },
};

function normalizeQuery(q: string): string {
  return q.toLowerCase().trim();
}

function matchPlace(
  query: string,
): { lat: number; lon: number; height: number; name: string } | null {
  for (const [name, coords] of Object.entries(BUILTIN_PLACES)) {
    if (query.includes(name)) {
      return { ...coords, name };
    }
  }
  return null;
}

function extractPlaceAfterFly(query: string): string | null {
  for (const kw of FLY_KEYWORDS) {
    const idx = query.indexOf(kw);
    if (idx >= 0) {
      const after = query.slice(idx + kw.length).trim();
      const place = after.replace(/[?.!]+$/, '').trim();
      if (place.length > 1) return place;
    }
  }
  return null;
}

export function mapIntent(query: string): IntentResult {
  const q = normalizeQuery(query);
  const actions: GlobeAction[] = [];
  const matched: string[] = [];

  if (!q) {
    return { actions, explanation: 'Empty query.', matched };
  }

  // Reset / overview
  if (RESET_KEYWORDS.some((k) => q.includes(k)) || OVERVIEW_KEYWORDS.some((k) => q.includes(k))) {
    actions.push({ type: 'fly_to', lat: 20, lon: 0, height: 20000000, title: 'Earth' });
    matched.push('reset/overview');
    return {
      actions,
      explanation: 'Resetting to global overview.',
      matched,
    };
  }

  // Vision mode
  for (const rule of VISION_RULES) {
    if (rule.keywords.some((k) => q.includes(k))) {
      actions.push({ type: 'set_vision', mode: rule.mode });
      matched.push(`vision:${rule.mode}`);
      break;
    }
  }

  // Heatmap
  if (HEATMAP_KEYWORDS.some((k) => q.includes(k))) {
    const enable = !TOGGLE_OFF.some((k) => q.includes(k));
    actions.push({ type: 'toggle_heatmap', enabled: enable });
    matched.push(`heatmap:${enable ? 'on' : 'off'}`);
  }

  // Layer toggles
  const wantOff = TOGGLE_OFF.some((k) => q.includes(k));
  const layerEnable = wantOff ? false : true;

  for (const rule of LAYER_RULES) {
    if (rule.keywords.some((k) => q.includes(k))) {
      actions.push({ type: 'toggle_layer', layer: rule.layer, enabled: layerEnable });
      matched.push(`layer:${rule.layer}:${layerEnable ? 'on' : 'off'}`);
    }
  }

  // Fly-to: check builtin places first, then extract place after fly keyword
  const place = matchPlace(q);
  if (place) {
    actions.push({
      type: 'fly_to',
      lat: place.lat,
      lon: place.lon,
      height: place.height,
      title: place.name.charAt(0).toUpperCase() + place.name.slice(1),
    });
    matched.push(`fly_to:${place.name}`);
  } else {
    const extracted = extractPlaceAfterFly(q);
    if (extracted) {
      const builtin = BUILTIN_PLACES[extracted];
      if (builtin) {
        actions.push({
          type: 'fly_to',
          lat: builtin.lat,
          lon: builtin.lon,
          height: builtin.height,
          title: extracted.charAt(0).toUpperCase() + extracted.slice(1),
        });
        matched.push(`fly_to:${extracted}`);
      } else {
        // Needs geocoding — caller handles
        matched.push(`geocode:${extracted}`);
      }
    }
  }

  // Build explanation
  if (actions.length === 0 && !matched.some((m) => m.startsWith('geocode:'))) {
    return {
      actions,
      explanation:
        'No globe actions matched. Try: "show me earthquakes near Thailand", "fly to Tehran", "enable thermal vision", "show wildfires and maritime".',
      matched,
    };
  }

  const parts: string[] = [];
  const flyActions = actions.filter((a) => a.type === 'fly_to');
  const layerActions = actions.filter((a) => a.type === 'toggle_layer');
  const visionActions = actions.filter((a) => a.type === 'set_vision');
  const heatmapActions = actions.filter((a) => a.type === 'toggle_heatmap');

  if (flyActions.length)
    parts.push(`Flying to ${(flyActions[0] as Extract<GlobeAction, { type: 'fly_to' }>).title}`);
  if (layerActions.length) {
    const labels = layerActions.map((a) => {
      const la = a as Extract<GlobeAction, { type: 'toggle_layer' }>;
      return `${la.enabled ? 'enabling' : 'disabling'} ${la.layer}`;
    });
    parts.push(labels.join(', '));
  }
  if (visionActions.length)
    parts.push(
      `Switching to ${(visionActions[0] as Extract<GlobeAction, { type: 'set_vision' }>).mode} vision`,
    );
  if (heatmapActions.length)
    parts.push(
      `${(heatmapActions[0] as Extract<GlobeAction, { type: 'toggle_heatmap' }>).enabled ? 'Enabling' : 'Disabling'} fusion heatmap`,
    );

  return {
    actions,
    explanation: parts.join('. ') + '.',
    matched,
  };
}

export async function geocodePlace(
  place: string,
): Promise<{ lat: number; lon: number; display_name: string } | null> {
  try {
    const r = await fetch(
      `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(place)}&format=json&limit=1`,
      { headers: { 'User-Agent': 'WorldBase/1.0' } },
    );
    if (!r.ok) return null;
    const d = await r.json();
    if (Array.isArray(d) && d.length > 0) {
      return {
        lat: parseFloat(d[0].lat),
        lon: parseFloat(d[0].lon),
        display_name: d[0].display_name || place,
      };
    }
  } catch {
    // fail-soft
  }
  return null;
}

export function needsGeocoding(matched: string[]): string | null {
  const m = matched.find((m) => m.startsWith('geocode:'));
  return m ? m.slice('geocode:'.length) : null;
}
