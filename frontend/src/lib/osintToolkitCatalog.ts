/**
 * Extended OSINT reference catalog (Tier A + B) — merged into osintToolkit.ts.
 */

type Ctx = {
  lat?: number;
  lon?: number;
  zoom?: number;
  icao?: string;
  hex?: string;
  mmsi?: string;
  domain?: string;
  ip?: string;
  email?: string;
  url?: string;
  query?: string;
};

function fmtCoord(n: number, digits = 4): string {
  return Number.isFinite(n) ? n.toFixed(digits) : '';
}

function geoCtx(ctx: Ctx): { lat: number; lon: number; zoom: number } | null {
  const { lat, lon } = ctx;
  if (lat == null || lon == null || !Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return { lat, lon, zoom: ctx.zoom ?? 11 };
}

function bboxAround(ctx: Ctx, pad = 0.45): string | null {
  const g = geoCtx(ctx);
  if (!g) return null;
  return `${fmtCoord(g.lon - pad, 5)},${fmtCoord(g.lat - pad, 5)},${fmtCoord(g.lon + pad, 5)},${fmtCoord(g.lat + pad, 5)}`;
}

export const OSINT_TOOLS_EXTENDED = [
  // --- native complements ---
  {
    id: 'wb-wildfires',
    label: 'intelshed NASA FIRMS',
    category: 'native',
    description: 'VIIRS/MODIS thermal hotspots — globe WILDFIRES layer + DATA tab.',
    stackNote: 'GET /api/wildfires · FIRMS_MAP_KEY in backend/.env · EONET fallback',
    stackRelation: 'native',
    homeUrl: '/api/wildfires',
    tags: ['firms', 'fire', 'api'],
    kinds: ['wildfire', 'event'],
  },
  {
    id: 'wb-gibs',
    label: 'intelshed NASA GIBS Overlays',
    category: 'native',
    description: 'MODIS thermal, GOES color, VIIRS reflectance WMTS on the globe LAYERS panel.',
    stackNote: 'GET /api/gibs/layers · telemetry GIBS toggles',
    stackRelation: 'native',
    homeUrl: '/api/gibs/layers',
    tags: ['nasa', 'gibs', 'api'],
    kinds: ['wildfire', 'event', 'weather'],
  },
  // --- air extended ---
  {
    id: 'opensky-network',
    label: 'OpenSky Network',
    category: 'air',
    description: 'Research ADS-B portal — same family as optional intelshed OpenSky OAuth feed.',
    stackNote: 'Native when OPENSKY_CLIENT_ID set; website for track history + research.',
    stackRelation: 'complement',
    homeUrl: 'https://opensky-network.org/',
    tags: ['ads-b', 'research'],
    kinds: ['aircraft', 'military'],
    buildUrl: (ctx: Ctx) => {
      const hex = (ctx.icao || ctx.hex || '').toLowerCase();
      if (hex) return `https://opensky-network.org/network/tracks?icao=${encodeURIComponent(hex)}`;
      const g = geoCtx(ctx);
      if (!g) return null;
      return `https://opensky-network.org/network/explorer?lat=${fmtCoord(g.lat, 5)}&lng=${fmtCoord(g.lon, 5)}&zoom=${g.zoom}`;
    },
  },
  {
    id: 'flightradar24',
    label: 'Flightradar24',
    category: 'air',
    description: 'Mainstream flight tracker — photos, schedules, airport status.',
    stackNote: 'Complement to ADS-B Exchange; free tier limits history.',
    stackRelation: 'complement',
    homeUrl: 'https://www.flightradar24.com/',
    tags: ['ads-b', 'flight'],
    kinds: ['aircraft', 'military'],
    buildUrl: (ctx: Ctx) => {
      const hex = (ctx.icao || ctx.hex || '').toLowerCase();
      if (hex) return `https://www.flightradar24.com/data/aircraft/${encodeURIComponent(hex)}`;
      const g = geoCtx(ctx);
      if (!g) return null;
      return `https://www.flightradar24.com/${fmtCoord(g.lat, 5)},${fmtCoord(g.lon, 5)},${g.zoom}`;
    },
  },
  {
    id: 'flightaware',
    label: 'FlightAware',
    category: 'air',
    description: 'Flight tracking with airport delays and historical data.',
    stackNote: 'Link-out for airport status cross-check.',
    stackRelation: 'link-only',
    homeUrl: 'https://flightaware.com/',
    tags: ['ads-b', 'airport'],
    kinds: ['aircraft'],
    buildUrl: (ctx: Ctx) => {
      const hex = (ctx.icao || ctx.hex || '').toLowerCase();
      if (hex) return `https://flightaware.com/live/flight/id/${encodeURIComponent(hex)}`;
      return null;
    },
  },
  {
    id: 'flightconnections',
    label: 'FlightConnections',
    category: 'air',
    description: 'Global route network map — connection analysis between airports.',
    stackNote: 'Useful for logistics / travel OSINT; not live positions.',
    stackRelation: 'reference',
    homeUrl: 'https://www.flightconnections.com/',
    tags: ['routes', 'airport'],
  },
  // --- sea extended ---
  {
    id: 'vesselfinder',
    label: 'VesselFinder',
    category: 'sea',
    description: 'AIS map with free tier — alternative UI to MarineTraffic.',
    stackNote: 'Deep-link MMSI from intelshed maritime layer.',
    stackRelation: 'complement',
    homeUrl: 'https://www.vesselfinder.com/',
    tags: ['ais', 'vessel'],
    kinds: ['maritime'],
    buildUrl: (ctx: Ctx) => {
      if (ctx.mmsi)
        return `https://www.vesselfinder.com/vessels/details/${encodeURIComponent(ctx.mmsi)}`;
      const g = geoCtx(ctx);
      if (!g) return null;
      return `https://www.vesselfinder.com/?lat=${fmtCoord(g.lat, 5)}&lon=${fmtCoord(g.lon, 5)}&zoom=${g.zoom}`;
    },
  },
  {
    id: 'equasis',
    label: 'Equasis',
    category: 'sea',
    description: 'Free ship safety / management database (IMO-centric).',
    stackNote: 'Complement AIS position with classification & safety records.',
    stackRelation: 'complement',
    homeUrl: 'https://www.equasis.org/EquasisWeb/public/HomePage',
    tags: ['imo', 'safety', 'vessel'],
    kinds: ['maritime'],
  },
  {
    id: 'shipspotting',
    label: 'ShipSpotting',
    category: 'sea',
    description: 'Community ship photo database — identify vessels by appearance.',
    stackNote: 'Search by name after AIS gives identity.',
    stackRelation: 'reference',
    homeUrl: 'https://www.shipspotting.com/',
    tags: ['photos', 'vessel'],
    kinds: ['maritime'],
  },
  // --- conflict extended ---
  {
    id: 'acled',
    label: 'ACLED',
    category: 'conflict',
    description: 'Armed Conflict Location & Event Data — structured conflict events.',
    stackNote: 'Not ingested yet — link-out; GDELT/Situations cover media-side digest.',
    stackRelation: 'link-only',
    homeUrl: 'https://acleddata.com/monitor/',
    tags: ['conflict', 'events', 'data'],
    kinds: ['geopolitics', 'gdelt_geo', 'situation', 'hazard', 'event'],
    buildUrl: (ctx: Ctx) => {
      const g = geoCtx(ctx);
      if (!g) return 'https://acleddata.com/monitor/';
      return `https://acleddata.com/monitor/#map/${g.zoom}/${fmtCoord(g.lat, 5)}/${fmtCoord(g.lon, 5)}`;
    },
  },
  {
    id: 'isw',
    label: 'ISW (Understanding War)',
    category: 'conflict',
    description: 'Daily operational maps and analysis — Ukraine, Middle East focus.',
    stackNote: 'Human-curated; complements automated briefing.',
    stackRelation: 'link-only',
    homeUrl: 'https://www.understandingwar.org/',
    tags: ['analysis', 'ukraine'],
    kinds: ['geopolitics', 'situation', 'military'],
  },
  {
    id: 'crisis24',
    label: 'Crisis24 (GardaWorld)',
    category: 'conflict',
    description: 'Global security risk and travel intelligence dashboard.',
    stackNote: 'Commercial risk lens — link-out for travel/security context.',
    stackRelation: 'link-only',
    homeUrl: 'https://crisis24.garda.com/',
    tags: ['risk', 'travel'],
    kinds: ['geopolitics', 'situation'],
  },
  // --- imagery extended ---
  {
    id: 'nasa-worldview',
    label: 'NASA Worldview',
    category: 'imagery',
    description:
      'Near-real-time satellite layers with timeline animation — disasters, fires, storms.',
    stackNote: 'Same NASA family as GIBS overlays on intelshed globe.',
    stackRelation: 'complement',
    homeUrl: 'https://worldview.earthdata.nasa.gov/',
    tags: ['nasa', 'timeline', 'disaster'],
    kinds: ['wildfire', 'event', 'gdacs', 'weather', 'quake'],
    buildUrl: (ctx: Ctx) => {
      const bb = bboxAround(ctx);
      if (!bb) return null;
      return `https://worldview.earthdata.nasa.gov/?v=${bb}`;
    },
  },
  {
    id: 'nasa-firms-web',
    label: 'NASA FIRMS Map',
    category: 'imagery',
    description: 'Interactive FIRMS fire map — same data family as /api/wildfires.',
    stackNote: 'Use when globe layer empty but FIRMS_MAP_KEY not set on PC.',
    stackRelation: 'complement',
    homeUrl: 'https://firms.modaps.eosdis.nasa.gov/map/',
    tags: ['firms', 'fire'],
    kinds: ['wildfire'],
    buildUrl: (ctx: Ctx) => {
      const g = geoCtx(ctx);
      if (!g) return null;
      return `https://firms.modaps.eosdis.nasa.gov/map/#v:${fmtCoord(g.lat, 5)}:${fmtCoord(g.lon, 5)}:${g.zoom}`;
    },
  },
  {
    id: 'zoom-earth',
    label: 'Zoom Earth',
    category: 'imagery',
    description: 'Weather satellite imagery updated every 10–15 minutes.',
    stackNote: 'Quick weather satellite view; no programmatic ingest.',
    stackRelation: 'link-only',
    homeUrl: 'https://zoom.earth/',
    tags: ['weather', 'satellite'],
    kinds: ['weather', 'wildfire', 'gdacs'],
    buildUrl: (ctx: Ctx) => {
      const g = geoCtx(ctx);
      if (!g) return null;
      return `https://zoom.earth/#${fmtCoord(g.lat, 5)},${fmtCoord(g.lon, 5)},${g.zoom}`;
    },
  },
  {
    id: 'sentinel-hub-eo',
    label: 'Sentinel Hub EO Browser',
    category: 'imagery',
    description: 'Sentinel, Landsat, MODIS with analysis tools in browser.',
    stackNote: 'Alternative to Copernicus Browser + intelshed STAC.',
    stackRelation: 'complement',
    homeUrl: 'https://apps.sentinel-hub.com/eo-browser/',
    tags: ['sentinel', 'landsat'],
    kinds: ['wildfire', 'event', 'situation'],
    buildUrl: (ctx: Ctx) => {
      const g = geoCtx(ctx);
      if (!g) return null;
      return `https://apps.sentinel-hub.com/eo-browser/?lat=${fmtCoord(g.lat, 5)}&lng=${fmtCoord(g.lon, 5)}&zoom=${g.zoom}`;
    },
  },
  {
    id: 'maxar-open-data',
    label: 'Maxar Open Data',
    category: 'imagery',
    description: 'High-resolution before/after imagery for humanitarian disasters.',
    stackNote: 'Event-driven — check after major quakes/floods/conflicts.',
    stackRelation: 'link-only',
    homeUrl: 'https://xpress.maxar.com/',
    tags: ['maxar', 'humanitarian'],
    kinds: ['gdacs', 'event', 'quake', 'wildfire'],
  },
  {
    id: 'usgs-earthexplorer',
    label: 'USGS EarthExplorer',
    category: 'imagery',
    description:
      'Historical aerial and declassified satellite archives — free account for download.',
    stackNote: 'Heavy workflow; desktop GIS follow-up with QGIS.',
    stackRelation: 'reference',
    homeUrl: 'https://earthexplorer.usgs.gov/',
    tags: ['usgs', 'archive'],
  },
  {
    id: 'openstreetmap',
    label: 'OpenStreetMap',
    category: 'imagery',
    description: 'Base map used by intelshed MapLibre pane and many overlays.',
    stackNote: 'Native basemap — external editor/view for POI checks.',
    stackRelation: 'complement',
    homeUrl: 'https://www.openstreetmap.org/',
    tags: ['osm', 'map'],
    buildUrl: (ctx: Ctx) => {
      const g = geoCtx(ctx);
      if (!g) return null;
      return `https://www.openstreetmap.org/#map=${Math.min(18, g.zoom + 2)}/${fmtCoord(g.lat, 5)}/${fmtCoord(g.lon, 5)}`;
    },
  },
  {
    id: 'qgis',
    label: 'QGIS',
    category: 'imagery',
    description: 'Open-source desktop GIS — import intelshed STAC exports and shapefiles.',
    stackNote: 'Desktop app — not browser; pairs with STAC panel exports.',
    stackRelation: 'reference',
    homeUrl: 'https://qgis.org/',
    tags: ['gis', 'desktop'],
  },
  {
    id: 'kepler-gl',
    label: 'Kepler.gl',
    category: 'imagery',
    description: 'Uber open-source geovisualization for large point datasets in browser.',
    stackNote: 'Use for CSV exports from DATA tables or FtM entity dumps.',
    stackRelation: 'reference',
    homeUrl: 'https://kepler.gl/',
    tags: ['viz', 'points'],
  },
  {
    id: 'tineye',
    label: 'TinEye',
    category: 'imagery',
    description: 'Reverse image search — find older copies and sources of photos.',
    stackNote: 'Investigative chain after social/video OSINT.',
    stackRelation: 'link-only',
    homeUrl: 'https://tineye.com/',
    tags: ['image', 'reverse'],
  },
  {
    id: 'yandex-images',
    label: 'Yandex Images',
    category: 'imagery',
    description: 'Reverse image search — often better for non-Western sources than Google.',
    stackNote: 'Upload or URL search in browser UI.',
    stackRelation: 'link-only',
    homeUrl: 'https://yandex.com/images/',
    tags: ['image', 'reverse'],
  },
  // --- infra extended ---
  {
    id: 'ioda-dashboard',
    label: 'IODA Dashboard',
    category: 'infra',
    description: 'Georgia Tech internet outage maps — same source family as intelshed OUTAGES.',
    stackNote: 'Visual ASN/country view of /api/outages upstream.',
    stackRelation: 'complement',
    homeUrl: 'https://ioda.inetintel.cc.gatech.edu/',
    tags: ['ioda', 'outage'],
    kinds: ['outage'],
  },
  {
    id: 'cloudflare-radar',
    label: 'Cloudflare Radar',
    category: 'infra',
    description:
      'Traffic trends, attacks, and anomalies — optional token enhances intelshed outages.',
    stackNote: 'Set CLOUDFLARE_API_TOKEN in backend/.env for /api/outages CF rows.',
    stackRelation: 'complement',
    homeUrl: 'https://radar.cloudflare.com/',
    tags: ['cloudflare', 'traffic'],
    kinds: ['outage'],
  },
  {
    id: 'thousandeyes-outages',
    label: 'ThousandEyes Outages',
    category: 'infra',
    description: 'Public internet outage dashboard (commercial vendor).',
    stackNote: 'Third-party macro view — not merged into briefing.',
    stackRelation: 'link-only',
    homeUrl: 'https://www.thousandeyes.com/outages/',
    tags: ['outage'],
    kinds: ['outage'],
  },
  // --- comms extended ---
  {
    id: 'kiwisdr',
    label: 'KiwiSDR Network',
    category: 'comms',
    description: 'Worldwide network of shared HF/VLF receivers in browser.',
    stackNote: 'Pick a receiver near AOI after checking map.',
    stackRelation: 'link-only',
    homeUrl: 'http://kiwisdr.com/',
    tags: ['sdr', 'hf'],
  },
  {
    id: 'radiogarden',
    label: 'Radio Garden',
    category: 'comms',
    description: 'Live radio stations on an interactive globe.',
    stackNote: 'Local media tone near a coordinate.',
    stackRelation: 'link-only',
    homeUrl: 'http://radio.garden/',
    tags: ['radio', 'audio'],
    buildUrl: (ctx: Ctx) => {
      const g = geoCtx(ctx);
      if (!g) return null;
      return `http://radio.garden/visit/${fmtCoord(g.lat, 5)}/${fmtCoord(g.lon, 5)}`;
    },
  },
  {
    id: 'openwebrx',
    label: 'OpenWebRX',
    category: 'comms',
    description: 'Open-source WebSDR software — directory of public instances.',
    stackNote: 'Self-host or use public instances listed on openwebrx.de.',
    stackRelation: 'reference',
    homeUrl: 'https://www.openwebrx.de/',
    tags: ['sdr', 'open-source'],
  },
  // --- cyber (new category) ---
  {
    id: 'crt-sh',
    label: 'crt.sh',
    category: 'cyber',
    description: 'Certificate transparency search — subdomains and infrastructure mapping.',
    stackNote: 'intelshed /api/osint/domain now includes cert_names when crt.sh responds.',
    stackRelation: 'complement',
    homeUrl: 'https://crt.sh/',
    tags: ['tls', 'subdomain'],
    kinds: ['osint'],
    buildUrl: (ctx: Ctx) => {
      if (!ctx.domain) return null;
      return `https://crt.sh/?q=${encodeURIComponent(`%.${ctx.domain}`)}`;
    },
  },
  {
    id: 'shodan',
    label: 'Shodan',
    category: 'cyber',
    description: 'IoT and exposed service search engine — free tier with limits.',
    stackNote: 'Link-out from IP/domain context; no API key in intelshed by default.',
    stackRelation: 'link-only',
    homeUrl: 'https://www.shodan.io/',
    tags: ['iot', 'infra'],
    kinds: ['osint'],
    buildUrl: (ctx: Ctx) => {
      if (ctx.ip) return `https://www.shodan.io/host/${encodeURIComponent(ctx.ip)}`;
      if (ctx.domain)
        return `https://www.shodan.io/search?query=hostname:${encodeURIComponent(ctx.domain)}`;
      return null;
    },
  },
  {
    id: 'censys',
    label: 'Censys Search',
    category: 'cyber',
    description: 'Internet-wide scan data and certificate transparency search.',
    stackNote: 'Complement to Shodan for cert/host pivoting.',
    stackRelation: 'link-only',
    homeUrl: 'https://search.censys.io/',
    tags: ['scan', 'certs'],
    kinds: ['osint'],
    buildUrl: (ctx: Ctx) => {
      if (ctx.ip) return `https://search.censys.io/hosts/${encodeURIComponent(ctx.ip)}`;
      if (ctx.domain)
        return `https://search.censys.io/search?resource=hosts&q=${encodeURIComponent(ctx.domain)}`;
      return null;
    },
  },
  {
    id: 'urlscan',
    label: 'URLScan.io',
    category: 'cyber',
    description: 'Scan websites — technologies, redirects, DOM snapshot.',
    stackNote: 'Use on suspicious links from GDELT/news OSINT.',
    stackRelation: 'link-only',
    homeUrl: 'https://urlscan.io/',
    tags: ['web', 'scan'],
    kinds: ['osint'],
    buildUrl: (ctx: Ctx) => {
      if (ctx.domain) return `https://urlscan.io/domain/${encodeURIComponent(ctx.domain)}`;
      const u = ctx.url || ctx.query;
      if (u?.startsWith('http')) return `https://urlscan.io/search/#${encodeURIComponent(u)}`;
      return null;
    },
  },
  {
    id: 'securitytrails',
    label: 'SecurityTrails',
    category: 'cyber',
    description: 'DNS, WHOIS, and IP history — free tier available.',
    stackNote: 'Historical DNS pivoting beyond live resolver checks.',
    stackRelation: 'link-only',
    homeUrl: 'https://securitytrails.com/',
    tags: ['dns', 'history'],
    kinds: ['osint'],
    buildUrl: (ctx: Ctx) => {
      if (!ctx.domain) return null;
      return `https://securitytrails.com/domain/${encodeURIComponent(ctx.domain)}/dns`;
    },
  },
  {
    id: 'wayback',
    label: 'Wayback Machine',
    category: 'cyber',
    description: 'Internet Archive — historical snapshots of websites.',
    stackNote: 'Investigative chain with URLScan and domain OSINT.',
    stackRelation: 'link-only',
    homeUrl: 'https://web.archive.org/',
    tags: ['archive', 'web'],
    kinds: ['osint'],
    buildUrl: (ctx: Ctx) => {
      const host = ctx.domain || ctx.url?.replace(/^https?:\/\//, '').split('/')[0];
      if (!host) return null;
      return `https://web.archive.org/web/*/${encodeURIComponent(`https://${host}`)}`;
    },
  },
  {
    id: 'wigle',
    label: 'WiGLE',
    category: 'cyber',
    description: 'Geotagged Wi-Fi network database from wardriving crowdsourcing.',
    stackNote: 'Niche — wireless infrastructure near a coordinate.',
    stackRelation: 'link-only',
    homeUrl: 'https://wigle.net/',
    tags: ['wifi', 'geo'],
    buildUrl: (ctx: Ctx) => {
      const g = geoCtx(ctx);
      if (!g) return null;
      return `https://wigle.net/map?maplat=${fmtCoord(g.lat, 5)}&maplon=${fmtCoord(g.lon, 5)}&mapzoom=${g.zoom}`;
    },
  },
  // --- identity extended ---
  {
    id: 'hibp',
    label: 'Have I Been Pwned',
    category: 'identity',
    description: 'Check emails/passwords against known breaches.',
    stackNote:
      'intelshed /api/osint/email returns breach_check_url + optional HIBP_API_KEY lookup.',
    stackRelation: 'complement',
    homeUrl: 'https://haveibeenpwned.com/',
    tags: ['breach', 'email'],
    kinds: ['osint'],
    buildUrl: (ctx: Ctx) => {
      if (!ctx.email) return null;
      return `https://haveibeenpwned.com/account/${encodeURIComponent(ctx.email)}`;
    },
  },
  {
    id: 'sherlock',
    label: 'Sherlock (GitHub)',
    category: 'identity',
    description: 'CLI username search across 400+ sites — self-run on PC.',
    stackNote: 'Complements WhatsMyName; not proxied through intelshed API.',
    stackRelation: 'reference',
    homeUrl: 'https://github.com/sherlock-project/sherlock',
    tags: ['username', 'cli'],
  },
  {
    id: 'inteltechniques',
    label: 'IntelTechniques Tools',
    category: 'meta',
    description: 'Michael Bazzell curated OSINT tool collection by investigation type.',
    stackNote: 'Meta-index — use when REFERENCE filter is not enough.',
    stackRelation: 'reference',
    homeUrl: 'https://inteltechniques.com/tools/',
    tags: ['meta', 'bookmarks'],
  },
  {
    id: 'osint-framework',
    label: 'OSINT Framework',
    category: 'meta',
    description: 'Community tree of OSINT tools sorted by investigation methodology.',
    stackNote: 'Starting point for tools not yet in intelshed REFERENCE.',
    stackRelation: 'reference',
    homeUrl: 'https://osintframework.com/',
    tags: ['meta', 'index'],
  },
  {
    id: 'bellingcat-toolkit',
    label: 'Bellingcat Resources',
    category: 'meta',
    description: 'Investigative methods and tool guides from Bellingcat.',
    stackNote: 'Methodology reference for geolocation and verification.',
    stackRelation: 'reference',
    homeUrl: 'https://www.bellingcat.com/resources/',
    tags: ['meta', 'investigation'],
  },
  {
    id: 'osint-combine',
    label: 'OSINT Combine',
    category: 'meta',
    description: 'Curated free OSINT tool bookmark lists by topic.',
    stackNote: 'External list — overlap with this REFERENCE tab is intentional.',
    stackRelation: 'reference',
    homeUrl: 'https://www.osintcombine.com/free-osint-tools',
    tags: ['meta', 'bookmarks'],
  },
  {
    id: 'spiderfoot',
    label: 'SpiderFoot',
    category: 'meta',
    description: 'Automated OSINT recon — open-source HX version self-hosted.',
    stackNote: 'Heavy automation; Flowsint/WhatsMyName cover lighter graph paths first.',
    stackRelation: 'reference',
    homeUrl: 'https://www.spiderfoot.net/',
    tags: ['automation', 'self-host'],
  },
];
