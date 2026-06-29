export type ContextMenuAction = {
  id: string
  label: string
  icon: string
  disabled?: boolean
  separatorAfter?: boolean
  handler: () => void
}

export type ContextMenuContext = {
  kind: string
  title: string
  lon?: number
  lat?: number
  entityId?: string
  link?: string
  rawProps: Record<string, unknown>
}

function num(v: unknown): number | undefined {
  if (v == null) return undefined
  const n = Number(v)
  return Number.isFinite(n) ? n : undefined
}

function str(v: unknown): string | undefined {
  if (v == null) return undefined
  return String(v)
}

export function buildContextMenuActions(
  ctx: ContextMenuContext,
  callbacks: {
    onFocus: (lon: number, lat: number) => void
    onCopyCoords: (lon: number, lat: number) => void
    onAddPin: (lon: number, lat: number, title: string) => void
    onViewDetails: () => void
    onTrackFlight: () => void
    onFetchTrail: () => void
    onOpenLink: (url: string) => void
    onOpenWindy: (lat: number, lon: number) => void
    onAskAI: (title: string, lines: string[]) => void
  },
): ContextMenuAction[] {
  const actions: ContextMenuAction[] = []
  const lon = ctx.lon ?? num(ctx.rawProps.lon)
  const lat = ctx.lat ?? num(ctx.rawProps.lat)
  const hasCoords = lon != null && lat != null

  // --- Universal actions ---
  if (hasCoords) {
    actions.push({
      id: 'focus',
      label: 'Focus Camera',
      icon: '◎',
      handler: () => callbacks.onFocus(lon!, lat!),
    })
    actions.push({
      id: 'copy-coords',
      label: 'Copy Coordinates',
      icon: '⎘',
      handler: () => callbacks.onCopyCoords(lon!, lat!),
    })
  }

  // --- Entity-specific actions ---
  const kind = ctx.kind

  if (kind === 'aircraft') {
    actions.push({
      id: 'track',
      label: 'Track Flight',
      icon: '✈',
      handler: callbacks.onTrackFlight,
      separatorAfter: true,
    })
    const icao = str(ctx.rawProps.icao)
    if (icao) {
      actions.push({
        id: 'trail',
        label: 'Fetch Trail',
        icon: '⟿',
        handler: callbacks.onFetchTrail,
      })
    }
  }

  if (kind === 'intel_ftm') {
    actions.push({
      id: 'details',
      label: 'View Details',
      icon: '📋',
      handler: callbacks.onViewDetails,
      separatorAfter: true,
    })
  }

  if (kind === 'fusion_cell') {
    actions.push({
      id: 'analyze',
      label: 'Analyze Cell',
      icon: '⛶',
      handler: () => callbacks.onAskAI(ctx.title, [
        `INTENSITY: ${str(ctx.rawProps.intensity) ?? '—'}`,
        `SCORE: ${num(ctx.rawProps.score) ?? 0}`,
        `SOURCES: ${str(ctx.rawProps.sources) ?? '—'}`,
      ]),
      separatorAfter: true,
    })
  }

  if (kind === 'maritime') {
    const mmsi = str(ctx.rawProps.mmsi)
    actions.push({
      id: 'maritime-details',
      label: 'View Vessel',
      icon: '🚢',
      handler: callbacks.onViewDetails,
      separatorAfter: true,
    })
    if (mmsi) {
      actions.push({
        id: 'web-search',
        label: `Search MMSI ${mmsi}`,
        icon: '🔍',
        handler: () => callbacks.onOpenLink(`https://www.marinetraffic.com/en/ais/details/ships/${mmsi}`),
      })
    }
  }

  if (ctx.link) {
    actions.push({
      id: 'open-link',
      label: 'Open Link',
      icon: '↗',
      handler: () => callbacks.onOpenLink(ctx.link!),
    })
  }

  // --- Windy for weather-sensitive entities ---
  if (hasCoords && ['wildfire', 'quake', 'hazard', 'gdelt_geo', 'weather', 'volcano', 'geopolitics', 'event', 'gdacs'].includes(kind)) {
    actions.push({
      id: 'windy',
      label: 'Open in Windy',
      icon: '🌬',
      handler: () => callbacks.onOpenWindy(lat!, lon!),
    })
  }

  // --- OSINT Pin ---
  if (hasCoords) {
    actions.push({
      id: 'add-pin',
      label: 'Add OSINT Pin',
      icon: '📌',
      handler: () => callbacks.onAddPin(lon!, lat!, ctx.title),
      separatorAfter: true,
    })
  }

  // --- Ask AI (always last) ---
  actions.push({
    id: 'ask-ai',
    label: 'Ask AI',
    icon: '🤖',
    handler: () => {
      const lines: string[] = []
      for (const [k, v] of Object.entries(ctx.rawProps)) {
        if (k === 'kind') continue
        if (v == null) continue
        const s = Array.isArray(v) ? v.join(', ') : String(v)
        if (s) lines.push(`${k.toUpperCase()}: ${s.slice(0, 120)}`)
      }
      callbacks.onAskAI(ctx.title, lines.slice(0, 8))
    },
  })

  return actions
}
