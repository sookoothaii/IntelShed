export type EntityPropReader = (key: string) => unknown;

export type EntityHoverTip = {
  title: string;
  lines: string[];
};

function str(v: unknown, fallback = '—'): string {
  if (v == null || v === '') return fallback;
  return String(v);
}

function clip(text: unknown, max = 72): string {
  const s = str(text, '');
  if (!s) return '—';
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

/** One-line hover summary for Cesium feed entities (globe dots). */
export function buildEntityHoverTip(kind: string, prop: EntityPropReader): EntityHoverTip | null {
  if (!kind) return null;

  switch (kind) {
    case 'aircraft':
      return {
        title: `✈ ${str(prop('callsign'), 'Aircraft')}`,
        lines: [
          `ICAO ${str(prop('icao'))} · ${Math.round(Number(prop('alt') ?? 0))} m`,
          `Heading ${Math.round(Number(prop('heading') ?? 0))}° · ${Math.round(Number(prop('vel') ?? 0))} m/s`,
        ],
      };
    case 'satellite':
      return {
        title: `🛰 ${str(prop('name'), 'Satellite')}`,
        lines: [`Altitude ${Math.round(Number(prop('alt') ?? 0))} m`],
      };
    case 'quake':
      return {
        title: `⊕ M${str(prop('mag'))} · ${clip(prop('place'), 48)}`,
        lines: [
          `Depth ${str(prop('depth'))} km`,
          prop('time') ? new Date(String(prop('time'))).toLocaleString() : '—',
        ],
      };
    case 'event':
      return {
        title: `⚠ ${clip(prop('title'), 56)}`,
        lines: [
          prop('category') ? `Category: ${str(prop('category'))}` : '',
          prop('date') ? new Date(String(prop('date'))).toLocaleString() : '—',
        ].filter(Boolean),
      };
    case 'military':
      return {
        title: `🎖 ${str(prop('flight') || prop('hex'), 'Military')}`,
        lines: [
          `Type ${str(prop('type'))} · ${Math.round(Number(prop('alt') ?? 0))} m`,
          prop('squawk') ? `Squawk ${str(prop('squawk'))}` : '',
        ].filter(Boolean),
      };
    case 'transit':
      return {
        title: `🚌 Route ${str(prop('route_id'))}`,
        lines: [
          `ID ${clip(prop('id'), 24)}`,
          `Bearing ${str(prop('bearing'))}° · ${str(prop('speed'))} m/s`,
        ],
      };
    case 'maritime':
      return {
        title: `🚢 ${clip(prop('name'), 40)}`,
        lines: [
          `MMSI ${str(prop('mmsi'))} · ${str(prop('type'))}`,
          `Speed ${str(prop('speed'))} kn · ${str(prop('flag'))}`,
        ],
      };
    case 'wildfire': {
      const zone =
        prop('zone') === 'regional' ? 'ASEAN' : prop('zone') === 'global' ? 'Global' : null;
      return {
        title: `🔥 Wildfire · ${str(prop('confidence_label'), 'unknown').toUpperCase()}`,
        lines: [
          [zone, `Conf ${str(prop('confidence'))}%`, `FRP ${str(prop('frp'))} MW`]
            .filter(Boolean)
            .join(' · '),
          `Date ${str(prop('acq_date'))}${prop('satellite') ? ` · ${str(prop('satellite'))}` : ''}`,
        ],
      };
    }
    case 'lightning':
      return {
        title: '⚡ Lightning strike',
        lines: [
          `Time ${str(prop('time'))}`,
          `Stations ${str(prop('stations'))} · participants ${str(prop('participants'))}`,
        ],
      };
    case 'node':
      return {
        title: `📡 ${str(prop('name'), 'Edge node')}`,
        lines: [
          `${prop('online') ? 'ONLINE' : 'OFFLINE'} · CPU ${str(prop('temp'))}°C`,
          `Mesh nodes ${str(prop('mesh_count'))}`,
        ],
      };
    case 'mesh_node':
      return {
        title: `📻 ${str(prop('name'), 'Mesh node')}`,
        lines: [
          `ID ${str(prop('id'))} · SNR ${str(prop('snr'))} dB`,
          `Last seen ${str(prop('last_seen'))}`,
        ],
      };
    case 'gdacs':
      return {
        title: `🆘 ${clip(prop('title'), 56)}`,
        lines: [clip(prop('description'), 80), `Published ${str(prop('published'))}`],
      };
    case 'outage':
      return {
        title: `📡 ${clip(prop('title'), 56)}`,
        lines: [
          `${str(prop('source'))} · level ${str(prop('level'))}`,
          prop('duration_h') != null ? `Duration ${str(prop('duration_h'))} h` : '',
        ].filter(Boolean),
      };
    case 'volcano':
      return {
        title: `🌋 ${str(prop('name'), 'Volcano')}`,
        lines: [
          `${str(prop('country'))} · ${str(prop('type'))}`,
          `Elev ${str(prop('elevation_m'))} m · active ${prop('active') ? 'yes' : 'no'}`,
        ],
      };
    case 'hazard':
      return {
        title: `⛈ ${clip(prop('event') || prop('headline'), 56)}`,
        lines: [
          `Severity ${str(prop('severity'))} · ${str(prop('urgency'))}`,
          clip(prop('area_desc'), 64),
        ],
      };
    case 'gdelt_geo':
      return {
        title: `📰 ${clip(prop('title'), 56)}`,
        lines: [prop('date') ? String(prop('date')) : 'GDELT geo pulse'],
      };
    case 'airquality':
      return {
        title: `💨 ${str(prop('city'), 'Air quality')}`,
        lines: [
          `PM2.5 ${str(prop('pm25'))} µg/m³ · PM10 ${str(prop('pm10'))} µg/m³`,
          str(prop('time')),
        ],
      };
    case 'energy':
      return {
        title: `⚡ ${str(prop('label'), 'Energy')}`,
        lines: [
          `Output ${str(prop('mw'))} MW · load ${str(prop('load_mw'))} MW`,
          `Price ${str(prop('price'))} €/MWh`,
        ],
      };
    case 'pegel':
      return {
        title: `🌊 ${str(prop('name'))} (${str(prop('water'))})`,
        lines: [
          `Level ${str(prop('value'))} ${str(prop('unit'))}`,
          `Status ${str(prop('severity'))}`,
        ],
      };
    case 'geopolitics':
      return {
        title: `🌍 ${clip(prop('name'), 56)}`,
        lines: [`Status ${str(prop('status'))}`, `Source ${str(prop('source'))}`],
      };
    case 'weather':
      return {
        title: '🌡 Weather cell',
        lines: [
          `${Number(prop('lat')).toFixed(2)}°, ${Number(prop('lon')).toFixed(2)}°`,
          `Temp ${prop('temperature_c') != null ? `${Math.round(Number(prop('temperature_c')))}°C` : '—'} · wind ${str(prop('wind_speed_ms'))} m/s`,
        ],
      };
    case 'traffic_cam':
      return {
        title: `🚦 ${clip(prop('name'), 48)}`,
        lines: [
          `${str(prop('country'))} · ${str(prop('source'))}`,
          `${Number(prop('lat')).toFixed(3)}°, ${Number(prop('lon')).toFixed(3)}°`,
        ],
      };
    case 'fusion_cell':
      return {
        title: '⛶ Fusion heat cell',
        lines: [
          `Score ${Number(prop('score') ?? 0).toFixed(2)} · intensity ${str(prop('intensity'))}`,
          clip(prop('sources'), 64),
        ],
      };
    case 'osint':
      return {
        title: `📌 ${clip(prop('title'), 48)}`,
        lines: [`Tool ${str(prop('tool'))}`, clip(prop('query'), 64)],
      };
    case 'detection_box': {
      const conf = Number(prop('confidence') ?? 0);
      const confPct = Math.round(conf * 100);
      const typeStr = str(prop('type'));
      const typeIcon =
        typeStr === 'disaster'
          ? '🆘'
          : typeStr === 'conflict'
            ? '⚠'
            : typeStr === 'vessel'
              ? '🚢'
              : '🏗';
      return {
        title: `${typeIcon} ${clip(prop('label'), 48)}`,
        lines: [
          `Confidence ${confPct}% · ${typeStr}`,
          `Source ${str(prop('source'))}${prop('schema') ? ` · ${str(prop('schema'))}` : ''}`,
        ],
      };
    }
    default:
      return null;
  }
}
