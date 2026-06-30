export type OsintPin = {
  id: string;
  tool: string;
  query: string;
  lon: number;
  lat: number;
  title: string;
  lines: string[];
  ts: number;
  pinType?: string;
  investigationId?: string;
  entityId?: string;
};

const STORAGE_KEY = 'worldbase_osint_pins_v1';
const MAX_PINS = 24;

export function loadOsintPins(): OsintPin[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as OsintPin[];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((p) => p && typeof p.lon === 'number' && typeof p.lat === 'number')
      .slice(-MAX_PINS);
  } catch {
    return [];
  }
}

export function saveOsintPins(pins: OsintPin[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(pins.slice(-MAX_PINS)));
  } catch {
    /* quota or private mode */
  }
}

/** Merge API import response into existing pins (dedupe by id). */
export function mergeImportedPins(existing: OsintPin[], imported: OsintPin[]): OsintPin[] {
  const byId = new Map(existing.map((p) => [p.id, p]));
  for (const p of imported) {
    byId.set(p.id, p);
  }
  return Array.from(byId.values()).slice(-MAX_PINS);
}
