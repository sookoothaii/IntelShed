/**
 * Operator OSINT toolkit — external deep-links + reference catalog.
 * intelshed native feeds stay in-app; these open vetted third-party UIs in a new tab.
 */

import { OSINT_TOOLS_EXTENDED } from './osintToolkitCatalog';

export type OsintContext = {
  kind?: string;
  lat?: number;
  lon?: number;
  title?: string;
  lines?: string[];
  callsign?: string;
  icao?: string;
  hex?: string;
  mmsi?: string;
  domain?: string;
  ip?: string;
  username?: string;
  email?: string;
  url?: string;
  query?: string;
  zoom?: number;
};

export type OsintStackRelation = 'native' | 'complement' | 'link-only' | 'reference';

export type OsintToolDef = {
  id: string;
  label: string;
  category: OsintCategoryId;
  description: string;
  stackNote: string;
  stackRelation: OsintStackRelation;
  homeUrl: string;
  tags: string[];
  /** Entity kinds where this tool gets a relevance boost in the modal. */
  kinds?: string[];
  buildUrl?: (ctx: OsintContext) => string | null;
};

export type OsintCategoryId =
  | 'air'
  | 'sea'
  | 'conflict'
  | 'imagery'
  | 'infra'
  | 'comms'
  | 'identity'
  | 'native'
  | 'cyber'
  | 'meta';

export type OsintCategory = {
  id: OsintCategoryId;
  label: string;
  blurb: string;
};

export type OsintToolLink = {
  id: string;
  label: string;
  category: OsintCategoryId;
  description: string;
  stackNote: string;
  url: string;
  contextual: boolean;
  relevance: number;
};

export const OSINT_CATEGORIES: OsintCategory[] = [
  {
    id: 'native',
    label: 'INTELSHED NATIVE',
    blurb: 'Already in your stack — API + globe layers. Use DATA / telemetry toggles first.',
  },
  {
    id: 'air',
    label: 'AIR / ADS-B',
    blurb:
      'Aircraft detail UIs. Live positions come from adsb.lol / adsb.fi / OpenSky in intelshed.',
  },
  {
    id: 'sea',
    label: 'MARITIME / AIS',
    blurb: 'Vessel detail. Globe MARITIME layer uses AISstream (+ MyShipTracking fallback).',
  },
  {
    id: 'conflict',
    label: 'CONFLICT / SITUATION',
    blurb: 'Curated conflict maps. Briefing uses GDELT, Situations, fusion hotspots.',
  },
  {
    id: 'imagery',
    label: 'IMAGERY / 3D',
    blurb: 'Satellite browse + 3D context. STAC search is built-in (DATA → STAC).',
  },
  {
    id: 'infra',
    label: 'INFRA / OUTAGES',
    blurb: 'Power, internet, transport, ALPR. Internet macro outages = IODA in DATA → OUTAGES.',
  },
  {
    id: 'comms',
    label: 'COMMS / RF',
    blurb: 'Scanner audio, WebSDR, military HF, signal ID wiki.',
  },
  {
    id: 'identity',
    label: 'IDENTITY / GRAPH',
    blurb: 'Usernames, domains, breaches, genealogy. Quick lookups in OSINT → TOOLS.',
  },
  {
    id: 'cyber',
    label: 'CYBER / INFRA RECON',
    blurb: 'Certs, exposed services, web archives — link-out; crt.sh also via /api/osint/domain.',
  },
  {
    id: 'meta',
    label: 'META / FRAMEWORKS',
    blurb: 'Curated indexes and methodology — OSINT Framework, Bellingcat, IntelTechniques.',
  },
];

const S2U_MAP_URL =
  (import.meta.env.VITE_S2U_MAP_URL as string | undefined)?.replace(/\/$/, '') || '';

function fmtCoord(n: number, digits = 4): string {
  return Number.isFinite(n) ? n.toFixed(digits) : '';
}

function geoCtx(ctx: OsintContext): { lat: number; lon: number; zoom: number } | null {
  const lat = ctx.lat;
  const lon = ctx.lon;
  if (lat == null || lon == null || !Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return { lat, lon, zoom: ctx.zoom ?? 11 };
}

export const OSINT_TOOLS: OsintToolDef[] = [
  // --- native (in-app anchors) ---
  {
    id: 'wb-aircraft',
    label: 'WorldBase Aircraft API',
    category: 'native',
    description: 'Live ADS-B states JSON — same feed as the globe AIRCRAFT layer.',
    stackNote: 'GET /api/aircraft · globe layer AIRCRAFT · military via /api/military',
    stackRelation: 'native',
    homeUrl: '/api/aircraft',
    tags: ['ads-b', 'api'],
    kinds: ['aircraft', 'military'],
  },
  {
    id: 'wb-maritime',
    label: 'WorldBase Maritime API',
    category: 'native',
    description:
      'AIS vessel positions for Thailand corridor + Malacca when AISSTREAM_API_KEY is set.',
    stackNote: 'GET /api/maritime · globe MARITIME · sanctions cross-check on MMSI',
    stackRelation: 'native',
    homeUrl: '/api/maritime',
    tags: ['ais', 'api'],
    kinds: ['maritime'],
  },
  {
    id: 'wb-stac',
    label: 'WorldBase STAC / Sentinel-2',
    category: 'native',
    description: 'Search Sentinel-2 L2A scenes by bbox — Element84 EarthSearch, no key.',
    stackNote: 'DATA → STAC · GET /api/stac/search · thumbnails via /api/stac/thumbnail',
    stackRelation: 'native',
    homeUrl: '/api/stac/collections',
    tags: ['sentinel', 'imagery', 'api'],
    kinds: ['event', 'wildfire', 'gdacs', 'situation', 'fusion_cell'],
  },
  {
    id: 'wb-outages',
    label: 'WorldBase Internet Outages',
    category: 'native',
    description: 'IODA alerts + optional Cloudflare Radar anomalies — not consumer Downdetector.',
    stackNote: 'DATA → OUTAGES · GET /api/outages · fusion + briefing digest',
    stackRelation: 'native',
    homeUrl: '/api/outages',
    tags: ['outage', 'ioda', 'api'],
    kinds: ['outage'],
  },
  {
    id: 'wb-gdelt',
    label: 'WorldBase GDELT Pulse',
    category: 'native',
    description: 'Local + global media/geo pulse for operator region.',
    stackNote: 'NEWS tab · GET /api/gdelt/pulse/local · briefing LOCAL/REGION',
    stackRelation: 'native',
    homeUrl: '/api/gdelt/pulse/local',
    tags: ['gdelt', 'news', 'api'],
    kinds: ['gdelt_geo', 'hazard', 'geopolitics', 'situation'],
  },
  {
    id: 'wb-insights',
    label: 'WorldBase Insight Cards',
    category: 'native',
    description: 'Ranked fusion + subgraph synthesis in briefing and Situations board.',
    stackNote: 'GET /api/insights · FULL SITUATION · Pi pull payload',
    stackRelation: 'native',
    homeUrl: '/api/insights',
    tags: ['fusion', 'briefing', 'api'],
    kinds: ['fusion_cell', 'situation', 'intel_ftm'],
  },
  // --- air ---
  {
    id: 'adsb-exchange',
    label: 'ADS-B Exchange Globe',
    category: 'air',
    description:
      'Community ADS-B map — compare tracks, filters, historical context (separate license from WorldBase feeds).',
    stackNote: 'Complement to adsb.lol/fi — use for visual cross-check, not ingest.',
    stackRelation: 'complement',
    homeUrl: 'https://globe.adsbexchange.com/',
    tags: ['ads-b', 'aircraft'],
    kinds: ['aircraft', 'military'],
    buildUrl: (ctx) => {
      const hex = (ctx.icao || ctx.hex || '').toLowerCase();
      if (hex) return `https://globe.adsbexchange.com/?icao=${encodeURIComponent(hex)}`;
      const g = geoCtx(ctx);
      if (!g) return null;
      return `https://globe.adsbexchange.com/?lat=${fmtCoord(g.lat)}&lon=${fmtCoord(g.lon)}&zoom=${g.zoom}`;
    },
  },
  {
    id: 'odin-weg',
    label: 'ODIN WEG (TRADOC)',
    category: 'air',
    description:
      'US Army equipment guide — identify platforms from observations or intel mentions.',
    stackNote: 'Reference when MILITARY layer or intel entities mention equipment.',
    stackRelation: 'reference',
    homeUrl: 'https://odin.tradoc.army.mil/WEG',
    tags: ['military', 'equipment'],
    kinds: ['military'],
    buildUrl: (ctx) => {
      const q = ctx.query || ctx.title?.replace(/^🎖\s*/, '').trim();
      if (!q || q.length < 2) return null;
      return `https://odin.tradoc.army.mil/WEG/Search?q=${encodeURIComponent(q)}`;
    },
  },
  // --- sea ---
  {
    id: 'marinetraffic',
    label: 'MarineTraffic',
    category: 'sea',
    description:
      'Commercial AIS UI — photos, port calls, voyage history (WorldBase stays on open AIS feeds).',
    stackNote: 'Deep-link MMSI from globe vessel modal or DATA → MARITIME row.',
    stackRelation: 'complement',
    homeUrl: 'https://www.marinetraffic.com/en/ais/home/centerx:100.5/centery:13.7/zoom:10',
    tags: ['ais', 'vessel'],
    kinds: ['maritime'],
    buildUrl: (ctx) => {
      if (ctx.mmsi) {
        return `https://www.marinetraffic.com/en/ais/details/ships/mmsi:${encodeURIComponent(ctx.mmsi)}`;
      }
      const g = geoCtx(ctx);
      if (!g) return null;
      return `https://www.marinetraffic.com/en/ais/home/centerx:${fmtCoord(g.lon, 5)}/centery:${fmtCoord(g.lat, 5)}/zoom:${g.zoom}`;
    },
  },
  // --- conflict ---
  {
    id: 'liveuamap',
    label: 'LiveUAMap',
    category: 'conflict',
    description: 'Crowdsourced conflict timeline map — useful for Ukraine/Middle East context.',
    stackNote: 'No official API — link-out only. GDELT + Situations cover automated digest.',
    stackRelation: 'link-only',
    homeUrl: 'https://liveuamap.com/',
    tags: ['conflict', 'map'],
    kinds: ['geopolitics', 'gdelt_geo', 'hazard', 'situation', 'military', 'event'],
    buildUrl: (ctx) => {
      const g = geoCtx(ctx);
      if (!g) return null;
      return `https://liveuamap.com/#zoom=${g.zoom}&lat=${fmtCoord(g.lat, 5)}&lng=${fmtCoord(g.lon, 5)}`;
    },
  },
  {
    id: 'liveuamap-usa',
    label: 'LiveUAMap USA',
    category: 'conflict',
    description: 'US-focused LiveUAMap instance.',
    stackNote: 'Regional variant — same link-out pattern.',
    stackRelation: 'link-only',
    homeUrl: 'https://usa.liveuamap.com/',
    tags: ['conflict', 'usa'],
    kinds: ['geopolitics', 'event'],
    buildUrl: (ctx) => {
      const g = geoCtx(ctx);
      if (!g) return null;
      return `https://usa.liveuamap.com/#zoom=${g.zoom}&lat=${fmtCoord(g.lat, 5)}&lng=${fmtCoord(g.lon, 5)}`;
    },
  },
  ...(S2U_MAP_URL
    ? [
        {
          id: 's2u-map',
          label: 'S2U Map (ArcGIS)',
          category: 'conflict' as const,
          description: 'Operator-configured ArcGIS Experience — situational map.',
          stackNote: 'Set VITE_S2U_MAP_URL in frontend/.env for your Experience URL.',
          stackRelation: 'link-only' as const,
          homeUrl: S2U_MAP_URL,
          tags: ['arcgis', 'situation'],
          kinds: ['situation', 'geopolitics', 'gdelt_geo'],
          buildUrl: (ctx: OsintContext) => {
            const g = geoCtx(ctx);
            if (!g) return S2U_MAP_URL;
            const sep = S2U_MAP_URL.includes('?') ? '&' : '?';
            return `${S2U_MAP_URL}${sep}center=${fmtCoord(g.lon, 5)},${fmtCoord(g.lat, 5)}&level=${g.zoom}`;
          },
        },
      ]
    : [
        {
          id: 's2u-map',
          label: 'S2U Map (ArcGIS)',
          category: 'conflict' as const,
          description:
            'ArcGIS Experience Builder situational map — URL not configured in this build.',
          stackNote:
            'Add VITE_S2U_MAP_URL=https://experience.arcgis.com/experience/… to frontend/.env',
          stackRelation: 'link-only' as const,
          homeUrl: 'https://experience.arcgis.com/experience/',
          tags: ['arcgis', 'situation'],
          kinds: ['situation'],
        },
      ]),
  // --- imagery ---
  {
    id: 'copernicus-browser',
    label: 'Copernicus Data Space Browser',
    category: 'imagery',
    description: 'Browse Sentinel missions — band selection, download, visual analysis.',
    stackNote: 'Complements DATA → STAC (WorldBase uses EarthSearch API programmatically).',
    stackRelation: 'complement',
    homeUrl: 'https://browser.dataspace.copernicus.eu/',
    tags: ['sentinel', 'imagery'],
    kinds: ['wildfire', 'event', 'gdacs', 'fusion_cell', 'situation'],
    buildUrl: (ctx) => {
      const g = geoCtx(ctx);
      if (!g) return null;
      return `https://browser.dataspace.copernicus.eu/?lat=${fmtCoord(g.lat, 5)}&lng=${fmtCoord(g.lon, 5)}&zoom=${g.zoom}`;
    },
  },
  {
    id: 'google-earth',
    label: 'Google Earth Web',
    category: 'imagery',
    description: 'Photorealistic 3D + familiar navigation — share points with non-WorldBase users.',
    stackNote: 'WorldBase globe = Cesium + Ion; Earth = quick external 3D check.',
    stackRelation: 'complement',
    homeUrl: 'https://earth.google.com/web/',
    tags: ['3d', 'globe'],
    buildUrl: (ctx) => {
      const g = geoCtx(ctx);
      if (!g) return null;
      return `https://earth.google.com/web/@${fmtCoord(g.lat, 5)},${fmtCoord(g.lon, 5)},${Math.max(500, 120000 - g.zoom * 8000)}a,${1000 + g.zoom * 100}d,35y,0h,0t,0r`;
    },
  },
  {
    id: 'youtube-geofind',
    label: 'Geotagged YouTube (mattw.io)',
    category: 'imagery',
    description:
      'Find YouTube videos geotagged near a coordinate — useful for protests, disasters, travel OSINT.',
    stackNote: 'Passive open search — radius + lookback in URL.',
    stackRelation: 'link-only',
    homeUrl: 'https://mattw.io/youtube-geofind/location',
    tags: ['video', 'geo'],
    kinds: ['event', 'gdelt_geo', 'hazard', 'situation', 'osint', 'traffic_cam', 'webcam'],
    buildUrl: (ctx) => {
      const g = geoCtx(ctx);
      if (!g) return null;
      return `https://mattw.io/youtube-geofind/location?lat=${fmtCoord(g.lat, 5)}&lon=${fmtCoord(g.lon, 5)}&radius=25&lookback=365&keywords=`;
    },
  },
  // --- infra ---
  {
    id: 'openrailwaymap',
    label: 'Open Railway Map',
    category: 'infra',
    description: 'OpenStreetMap-based rail infrastructure — lines, stations, electrification.',
    stackNote: 'Complements TRANSIT layer (GTFS realtime vehicles ≠ rail network map).',
    stackRelation: 'complement',
    homeUrl: 'https://www.openrailwaymap.org/',
    tags: ['rail', 'transport'],
    kinds: ['transit', 'energy', 'node'],
    buildUrl: (ctx) => {
      const g = geoCtx(ctx);
      if (!g) return null;
      return `https://www.openrailwaymap.org/?lat=${fmtCoord(g.lat, 5)}&lon=${fmtCoord(g.lon, 5)}&zoom=${Math.min(18, g.zoom + 2)}`;
    },
  },
  {
    id: 'poweroutage-us',
    label: 'PowerOutage.us',
    category: 'infra',
    description: 'US electric grid outage map — county/state level power status.',
    stackNote: 'US-only; not merged into WorldBase outages (IODA = internet backbone).',
    stackRelation: 'link-only',
    homeUrl: 'https://poweroutage.us/map',
    tags: ['power', 'usa', 'outage'],
    kinds: ['outage', 'energy'],
  },
  {
    id: 'downdetector',
    label: 'Downdetector',
    category: 'infra',
    description: 'Consumer service status — ISP, apps, banks (crowdsourced, not macro IODA).',
    stackNote: 'Different signal class than DATA → OUTAGES.',
    stackRelation: 'link-only',
    homeUrl: 'https://downdetector.com/',
    tags: ['outage', 'consumer'],
    kinds: ['outage'],
  },
  {
    id: 'deflock',
    label: 'DeFlock Me',
    category: 'infra',
    description: 'ALPR / flock camera map — US privacy & surveillance awareness.',
    stackNote: 'Link-out; no ingest. Useful for domestic travel OPSEC.',
    stackRelation: 'link-only',
    homeUrl: 'https://deflock.me/map',
    tags: ['alpr', 'privacy', 'usa'],
    buildUrl: (ctx) => {
      const g = geoCtx(ctx);
      if (!g) return 'https://deflock.me/map';
      return `https://deflock.me/map#${g.zoom}/${fmtCoord(g.lat, 5)}/${fmtCoord(g.lon, 5)}`;
    },
  },
  // --- comms ---
  {
    id: 'broadcastify',
    label: 'Broadcastify',
    category: 'comms',
    description: 'Live public safety radio streams — fire, police, EMS (region directory).',
    stackNote: 'Audio link-out; not embedded in WorldBase (licensing + autoplay).',
    stackRelation: 'link-only',
    homeUrl: 'https://www.broadcastify.com/listen/',
    tags: ['scanner', 'audio'],
    kinds: ['situation', 'event', 'hazard'],
  },
  {
    id: 'websdr',
    label: 'WebSDR.org',
    category: 'comms',
    description: 'Global list of web-accessible software-defined radios.',
    stackNote: 'HF/VHF listening — pick a receiver near your AOI manually.',
    stackRelation: 'reference',
    homeUrl: 'http://websdr.org/',
    tags: ['sdr', 'hf'],
  },
  {
    id: 'hfgcs',
    label: 'HFGCS',
    category: 'comms',
    description: 'High Frequency Global Communications System — military HF reference.',
    stackNote: 'Context for MILITARY + SIGINT workflows.',
    stackRelation: 'reference',
    homeUrl: 'https://hfgcs.com',
    tags: ['military', 'hf'],
    kinds: ['military'],
  },
  {
    id: 'sigidwiki',
    label: 'SIGID Wiki',
    category: 'comms',
    description: 'Signal identification wiki — modulations, digital modes, military signals.',
    stackNote: 'Reference when analyzing RF captures or WebSDR sessions.',
    stackRelation: 'reference',
    homeUrl: 'https://www.sigidwiki.com/wiki/Main_Page',
    tags: ['sigint', 'wiki'],
  },
  // --- identity ---
  {
    id: 'whatsmyname',
    label: 'WhatsMyName',
    category: 'identity',
    description: 'Username enumeration across hundreds of sites — web UI + optional JSON workflow.',
    stackNote: 'WorldBase /api/osint/username does basic checks; WMY is exhaustive link-out.',
    stackRelation: 'complement',
    homeUrl: 'https://whatsmyname.app/',
    tags: ['username', 'osint'],
    kinds: ['osint'],
    buildUrl: (ctx) => {
      if (!ctx.username) return null;
      return `https://whatsmyname.app/#/${encodeURIComponent(ctx.username)}`;
    },
  },
  {
    id: 'icann-lookup',
    label: 'ICANN Lookup',
    category: 'identity',
    description: 'Registration data lookup (RDAP/WHOIS) via ICANN.',
    stackNote: 'Extends OSINT → DOMAIN (WorldBase returns DNS A/MX only today).',
    stackRelation: 'complement',
    homeUrl: 'https://lookup.icann.org/en',
    tags: ['domain', 'whois'],
    kinds: ['osint'],
    buildUrl: (ctx) => {
      if (!ctx.domain) return null;
      return `https://lookup.icann.org/en/lookup?name=${encodeURIComponent(ctx.domain)}`;
    },
  },
  {
    id: 'maltego',
    label: 'Maltego',
    category: 'identity',
    description: 'Commercial link-analysis desktop/cloud — transforms and OSINT integrations.',
    stackNote: 'WorldBase graph = Flowsint + FtM INTEL; Maltego stays external.',
    stackRelation: 'link-only',
    homeUrl: 'https://app.maltego.com/',
    tags: ['graph', 'commercial'],
  },
  {
    id: 'forebears',
    label: 'Forebears',
    category: 'identity',
    description: 'Surname distribution and genealogy reference — contextual for identity research.',
    stackNote: 'Interest / background only — not operational feed.',
    stackRelation: 'reference',
    homeUrl: 'https://forebears.io/',
    tags: ['genealogy'],
  },
  ...(OSINT_TOOLS_EXTENDED as OsintToolDef[]),
];

const LINE_ICAO = /(?:ICAO24|ICAO|HEX):\s*([a-f0-9]{3,6})/i;
const LINE_MMSI = /MMSI:\s*(\d{6,9})/i;
const LINE_LATLON = /LAT\/LON:\s*([-\d.]+)\s*,\s*([-\d.]+)/i;
const LINE_QUERY = /QUERY:\s*(.+)/i;
const LINE_TOOL = /TOOL:\s*(\w+)/i;
const LINE_IP = /^IP:\s*(\d{1,3}(?:\.\d{1,3}){3})$/i;

function parseLineValue(lines: string[] | undefined, re: RegExp): string | undefined {
  if (!lines?.length) return undefined;
  for (const line of lines) {
    const m = line.match(re);
    if (m?.[1]) return m[1].trim();
  }
  return undefined;
}

function parseDomainFromLines(lines: string[] | undefined): string | undefined {
  const q = parseLineValue(lines, LINE_QUERY);
  if (!q) return undefined;
  if (q.includes('@')) return undefined;
  if (q.includes('.') && !q.includes(' ')) return q.replace(/^https?:\/\//, '').split('/')[0];
  return undefined;
}

function parseUsernameFromLines(lines: string[] | undefined, tool?: string): string | undefined {
  if (tool === 'username') return parseLineValue(lines, LINE_QUERY);
  const q = parseLineValue(lines, LINE_QUERY);
  if (q && !q.includes('@') && !q.includes('.') && q.length >= 2) return q;
  return undefined;
}

function parseEmailFromLines(lines: string[] | undefined, tool?: string): string | undefined {
  const q = parseLineValue(lines, LINE_QUERY);
  if (tool === 'email' && q?.includes('@')) return q.trim().toLowerCase();
  if (q?.includes('@')) return q.trim().toLowerCase();
  return undefined;
}

function parseIpFromLines(lines: string[] | undefined, tool?: string): string | undefined {
  const fromLine = parseLineValue(lines, LINE_IP);
  if (fromLine) return fromLine;
  if (tool === 'ip') {
    const q = parseLineValue(lines, LINE_QUERY);
    if (q && /^\d{1,3}(\.\d{1,3}){3}$/.test(q.trim())) return q.trim();
  }
  return undefined;
}

function parseUrlFromQuery(lines: string[] | undefined): string | undefined {
  const q = parseLineValue(lines, LINE_QUERY);
  if (q?.startsWith('http://') || q?.startsWith('https://')) return q.trim();
  return undefined;
}

/** Build context from a globe detail target or focus payload. */
export function parseOsintContext(input: {
  kind?: string;
  title?: string;
  lines?: string[];
  lat?: number;
  lon?: number;
}): OsintContext {
  const lines = input.lines || [];
  let lat = input.lat;
  let lon = input.lon;
  if (lat == null || lon == null) {
    const m = parseLineValue(lines, LINE_LATLON);
    if (m) {
      const parts = m.split(',').map((s) => s.trim());
      if (parts.length >= 2) {
        lat = Number(parts[0]);
        lon = Number(parts[1]);
      }
    }
  }
  const tool = parseLineValue(lines, LINE_TOOL);
  const icao = parseLineValue(lines, LINE_ICAO)?.toLowerCase();
  const callsign = input.title?.replace(/^✈\s*/, '').trim();
  const email = parseEmailFromLines(lines, tool);
  const domainFromLines = parseDomainFromLines(lines);
  return {
    kind: input.kind,
    lat: Number.isFinite(lat!) ? lat : undefined,
    lon: Number.isFinite(lon!) ? lon : undefined,
    title: input.title,
    lines,
    icao,
    hex: icao,
    callsign: callsign && callsign !== 'undefined' ? callsign : undefined,
    mmsi: parseLineValue(lines, LINE_MMSI),
    domain: domainFromLines || (email ? email.split('@')[1] : undefined),
    ip: parseIpFromLines(lines, tool),
    email,
    url: parseUrlFromQuery(lines),
    username: parseUsernameFromLines(lines, tool),
    query: parseLineValue(lines, LINE_QUERY),
    zoom: 11,
  };
}

function relevanceForTool(tool: OsintToolDef, ctx: OsintContext): number {
  let score = 0;
  if (ctx.kind && tool.kinds?.includes(ctx.kind)) score += 40;
  if (tool.buildUrl) {
    const built = tool.buildUrl(ctx);
    if (built && built !== tool.homeUrl) score += 35;
  }
  if (tool.stackRelation === 'native' && ctx.kind && tool.kinds?.includes(ctx.kind)) score += 25;
  if (tool.id === 'adsb-exchange' && (ctx.icao || ctx.hex)) score += 30;
  if (tool.id === 'marinetraffic' && ctx.mmsi) score += 30;
  if (tool.id === 'whatsmyname' && ctx.username) score += 30;
  if (tool.id === 'icann-lookup' && ctx.domain) score += 30;
  if (tool.id === 'crt-sh' && ctx.domain) score += 28;
  if (tool.id === 'shodan' && (ctx.ip || ctx.domain)) score += 28;
  if (tool.id === 'censys' && (ctx.ip || ctx.domain)) score += 28;
  if (tool.id === 'hibp' && ctx.email) score += 28;
  if (tool.id === 'flightradar24' && (ctx.icao || ctx.hex)) score += 25;
  if (tool.id === 'vesselfinder' && ctx.mmsi) score += 25;
  if (tool.id === 'nasa-worldview' && ctx.kind === 'wildfire') score += 22;
  if (tool.id === 'nasa-firms-web' && ctx.kind === 'wildfire') score += 22;
  if (tool.id === 'odin-weg' && ctx.kind === 'military') score += 20;
  if (ctx.lat != null && ctx.lon != null && tool.buildUrl) score += 10;
  return score;
}

export function buildOsintToolLinks(
  ctx: OsintContext,
  opts?: { includeNative?: boolean },
): OsintToolLink[] {
  const includeNative = opts?.includeNative !== false;
  const out: OsintToolLink[] = [];

  for (const tool of OSINT_TOOLS) {
    if (!includeNative && tool.stackRelation === 'native') continue;
    let url = tool.homeUrl;
    let contextual = false;
    if (tool.buildUrl) {
      const built = tool.buildUrl(ctx);
      if (built) {
        url = built;
        contextual = built !== tool.homeUrl;
      }
    }
    out.push({
      id: tool.id,
      label: tool.label,
      category: tool.category,
      description: tool.description,
      stackNote: tool.stackNote,
      url,
      contextual,
      relevance: relevanceForTool(tool, ctx),
    });
  }

  return out.sort((a, b) => b.relevance - a.relevance || a.label.localeCompare(b.label));
}

export function toolsByCategory(): Map<OsintCategoryId, OsintToolDef[]> {
  const map = new Map<OsintCategoryId, OsintToolDef[]>();
  for (const cat of OSINT_CATEGORIES) map.set(cat.id, []);
  for (const tool of OSINT_TOOLS) {
    map.get(tool.category)?.push(tool);
  }
  return map;
}

export function categoryMeta(id: OsintCategoryId): OsintCategory | undefined {
  return OSINT_CATEGORIES.find((c) => c.id === id);
}
