/**
 * Docker MCP code-mode script: WorldBase ops snapshot.
 * Register once via MCP_DOCKER code-mode tool (servers: ["fetch"]).
 * Run via mcp-exec name=code-mode-ops-snapshot arguments.script=<this file contents>
 */

function extractJson(text) {
  const i = text.indexOf("{");
  if (i < 0) return null;
  return JSON.parse(text.slice(i));
}

function fetchJson(url, maxLength) {
  const raw = fetch({ url: url, max_length: maxLength || 80000 });
  return extractJson(raw);
}

const ping = fetchJson("http://host.docker.internal:8002/api/health/ping", 800);
const usgs = fetchJson(
  "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson",
  120000
);
const gdacs = fetchJson(
  "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH?eventlist=EQ&limit=5",
  60000
);
const gdacsFloods = fetchJson(
  "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH?eventlist=FL&limit=3",
  60000
);

const usgsTop = (usgs?.features || []).slice(0, 3).map((f) => ({
  mag: f.properties?.mag,
  place: f.properties?.place,
}));

const gdacsEvents = (gdacs?.features || gdacs?.results || []).slice(0, 3);
const floodEvents = (gdacsFloods?.features || gdacsFloods?.results || []).slice(0, 2);

return JSON.stringify(
  {
    fetched_at: new Date().toISOString(),
    worldbase_ping: ping,
    usgs_m25plus_24h: {
      count: usgs?.metadata?.count ?? 0,
      top3: usgsTop,
    },
    gdacs_earthquakes: gdacsEvents,
    gdacs_floods: floodEvents,
    note: "Pair with worldbase MCP: worldbase_briefing_latest, worldbase_nodes, worldbase_fusion_hotspots",
  },
  null,
  2
);
