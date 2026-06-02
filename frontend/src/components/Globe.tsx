import { useEffect, useRef, useState } from 'react'
import {
  Viewer,
  Ion,
  Cartesian3,
  Cartesian2,
  Color,
  createWorldTerrainAsync,
  CustomDataSource,
  Entity,
  LabelStyle,
  VerticalOrigin,
  HorizontalOrigin,
  NearFarScalar,
  DistanceDisplayCondition,
  Math as CMath,
  PolylineGlowMaterialProperty,
  ScreenSpaceEventHandler,
  ScreenSpaceEventType,
  PostProcessStage,
  Cartographic,
  CallbackProperty,
  ColorMaterialProperty,
  ConstantPositionProperty,
  defined,
} from 'cesium'
import * as satellite from 'satellite.js'
import 'cesium/Build/Cesium/Widgets/widgets.css'
import {
  NVG_FRAGMENT,
  THERMAL_FRAGMENT,
  CRT_FRAGMENT,
  NIGHT_FRAGMENT,
  VISION_MODES,
  type VisionMode,
} from '../lib/visionShaders'
import { POIS } from '../lib/pois'
import type { FocusTarget } from '../lib/focus'

Ion.defaultAccessToken = import.meta.env.VITE_CESIUM_ION_TOKEN ?? ''
if (!Ion.defaultAccessToken) {
  console.warn('[WorldBase] VITE_CESIUM_ION_TOKEN is not set. Copy frontend/.env.example to frontend/.env and add your Cesium Ion token.')
}

const SAT_GROUPS = [
  { id: 'starlink', label: 'STARLINK' },
  { id: 'stations', label: 'STATIONS' },
  { id: 'gps-ops', label: 'GPS' },
  { id: 'weather', label: 'WEATHER' },
  { id: 'active', label: 'ALL' },
]

type Stats = {
  aircraft: number
  satellites: number
  quakes: number
  events: number
  nodes: number
  military: number
  spaceweather: number
  geopolitics: number
  wildfires: number
  lightning: number
  transit: number
  maritime: number
  fps: number
}

type Target = {
  kind: string
  title: string
  lines: string[]
  link?: string
} | null

type Cursor = { lon: string; lat: string; alt: string }

export default function Globe({ focus, onAskAI }: { focus?: FocusTarget | null; onAskAI?: (title: string, lines: string[]) => void }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<Viewer | null>(null)
  const apiRef = useRef<any>({})
  const focusRef = useRef<FocusTarget | null>(focus ?? null)

  const [vision, setVision] = useState<VisionMode>('normal')
  const [satGroup, setSatGroup] = useState('starlink')
  const [stats, setStats] = useState<Stats>({ aircraft: 0, satellites: 0, quakes: 0, events: 0, nodes: 0, military: 0, spaceweather: 0, geopolitics: 0, wildfires: 0, lightning: 0, transit: 0, maritime: 0, fps: 0 })
  const [target, setTarget] = useState<Target>(null)
  const [cursor, setCursor] = useState<Cursor>({ lon: '—', lat: '—', alt: '—' })
  const [layers, setLayers] = useState({
    aircraft: true,
    satellites: true,
    orbits: true,
    quakes: true,
    events: true,
    nodes: true,
    military: true,
    spaceweather: true,
    geopolitics: true,
    wildfires: true,
    lightning: true,
    transit: true,
    maritime: true,
  })

  useEffect(() => {
    if (!containerRef.current) return
    let cancelled = false
    let viewer: Viewer | null = null
    const timers: ReturnType<typeof setInterval>[] = []

    ;(async () => {
      const terrainProvider = await createWorldTerrainAsync()
      if (cancelled || !containerRef.current) return

      viewer = new Viewer(containerRef.current, {
        terrainProvider,
        baseLayerPicker: true,
        sceneModePicker: true,
        navigationHelpButton: false,
        animation: false,
        timeline: false,
        homeButton: true,
        geocoder: true,
        infoBox: false,
        selectionIndicator: false,
      })
      viewerRef.current = viewer

      const scene = viewer.scene
      scene.globe.enableLighting = true
      scene.fog.enabled = true
      if (scene.skyAtmosphere) scene.skyAtmosphere.show = true
      ;(scene.globe as any).atmosphereLightIntensity = 12.0

      const aircraftSrc = new CustomDataSource('aircraft')
      const satSrc = new CustomDataSource('satellites')
      const orbitSrc = new CustomDataSource('orbits')
      const quakeSrc = new CustomDataSource('quakes')
      const eventSrc = new CustomDataSource('events')
      const focusSrc = new CustomDataSource('focus')
      const nodesSrc = new CustomDataSource('nodes')
      const militarySrc = new CustomDataSource('military')
      const spaceweatherSrc = new CustomDataSource('spaceweather')
      const geopoliticsSrc = new CustomDataSource('geopolitics')
      const wildfireSrc = new CustomDataSource('wildfires')
      const lightningSrc = new CustomDataSource('lightning')
      const transitSrc = new CustomDataSource('transit')
      const maritimeSrc = new CustomDataSource('maritime')
      ;[orbitSrc, quakeSrc, eventSrc, satSrc, aircraftSrc, focusSrc, nodesSrc, militarySrc, spaceweatherSrc, geopoliticsSrc, wildfireSrc, lightningSrc, transitSrc, maritimeSrc].forEach((s) => viewer!.dataSources.add(s))

      const acMap = new Map<string, Entity>()
      const satMap = new Map<string, Entity>()

      // ---------- AIRCRAFT ----------
      const fetchAircraft = async () => {
        if (cancelled) return
        try {
          const r = await fetch('/api/aircraft/')
          const d = await r.json()
          const states: any[] = d.states || []
          const seen = new Set<string>()
          for (const s of states) {
            const lon = s[5], lat = s[6]
            if (lon == null || lat == null) continue
            const id = s[0]
            const alt = Math.max(s[7] ?? s[13] ?? 0, 0)
            const callsign = (s[1] || '').trim() || id
            seen.add(id)
            const pos = Cartesian3.fromDegrees(lon, lat, alt)
            let e = acMap.get(id)
            if (e) {
              ;(e.position as ConstantPositionProperty).setValue(pos)
            } else {
              e = aircraftSrc.entities.add({
                id: 'ac-' + id,
                position: new ConstantPositionProperty(pos),
                point: {
                  pixelSize: 7,
                  color: s[8] ? Color.GRAY : Color.fromCssColorString('#ffd23f'),
                  outlineColor: Color.BLACK,
                  outlineWidth: 1,
                  scaleByDistance: new NearFarScalar(1e5, 1.6, 1e7, 0.5),
                },
                label: {
                  text: callsign,
                  font: '600 11px "Courier New"',
                  fillColor: Color.fromCssColorString('#ffe98a'),
                  outlineColor: Color.BLACK,
                  outlineWidth: 2,
                  style: LabelStyle.FILL_AND_OUTLINE,
                  verticalOrigin: VerticalOrigin.BOTTOM,
                  horizontalOrigin: HorizontalOrigin.LEFT,
                  pixelOffset: new Cartesian2(8, -4),
                  distanceDisplayCondition: new DistanceDisplayCondition(0, 1.2e6),
                },
                properties: {
                  kind: 'aircraft', icao: id, callsign,
                  country: s[2], alt, vel: s[9] ?? 0, heading: s[10] ?? 0,
                } as any,
              })
              acMap.set(id, e)
            }
          }
          for (const [id, e] of acMap) {
            if (!seen.has(id)) { aircraftSrc.entities.remove(e); acMap.delete(id) }
          }
          if (!cancelled) setStats((p) => ({ ...p, aircraft: acMap.size }))
        } catch (e) {
          console.error('aircraft fetch failed', e)
        }
      }

      // ---------- SATELLITES ----------
      let satCache: { name: string; rec: any }[] = []
      const loadSatTLEs = async (group: string) => {
        try {
          const r = await fetch(`/api/satellites?group=${group}&limit=500`)
          const d = await r.json()
          satCache = []
          for (const s of d.satellites || []) {
            try {
              satCache.push({ name: s.name, rec: satellite.twoline2satrec(s.tle1, s.tle2) })
            } catch { /* skip */ }
          }
          satSrc.entities.removeAll()
          orbitSrc.entities.removeAll()
          satMap.clear()
        } catch (e) {
          console.error('sat TLE fetch failed', e)
        }
      }

      const propagateSats = () => {
        if (cancelled || satCache.length === 0) return
        const now = new Date()
        const gmst = satellite.gstime(now)
        const seen = new Set<string>()
        orbitSrc.entities.suspendEvents()
        orbitSrc.entities.removeAll()
        let drawn = 0
        const MAX_ORBITS = 50
        for (const { name, rec } of satCache) {
          try {
            const pv = satellite.propagate(rec, now)
            if (!pv || !pv.position || typeof pv.position === 'boolean') continue
            const gd = satellite.eciToGeodetic(pv.position as any, gmst)
            const lon = CMath.toDegrees(gd.longitude)
            const lat = CMath.toDegrees(gd.latitude)
            const alt = gd.height * 1000
            if (!isFinite(lon) || !isFinite(lat) || !isFinite(alt)) continue
            seen.add(name)
            const pos = Cartesian3.fromDegrees(lon, lat, alt)
            let e = satMap.get(name)
            if (e) {
              ;(e.position as ConstantPositionProperty).setValue(pos)
            } else {
              e = satSrc.entities.add({
                id: 'sat-' + name,
                position: new ConstantPositionProperty(pos),
                point: {
                  pixelSize: 5,
                  color: Color.fromCssColorString('#00e5ff'),
                  outlineColor: Color.fromCssColorString('#003a44'),
                  outlineWidth: 1,
                },
                label: {
                  text: name,
                  font: '600 10px "Courier New"',
                  fillColor: Color.fromCssColorString('#7df9ff'),
                  outlineColor: Color.BLACK,
                  outlineWidth: 2,
                  style: LabelStyle.FILL_AND_OUTLINE,
                  verticalOrigin: VerticalOrigin.BOTTOM,
                  pixelOffset: new Cartesian2(0, -8),
                  distanceDisplayCondition: new DistanceDisplayCondition(0, 6e7),
                },
                properties: { kind: 'satellite', name, alt } as any,
              })
              satMap.set(name, e)
            }
            if (drawn < MAX_ORBITS) {
              drawn++
              const periodMin = (2 * Math.PI) / rec.no
              const pts: Cartesian3[] = []
              for (let i = 0; i <= 80; i++) {
                const t = new Date(now.getTime() + (periodMin * 60000 * i) / 80)
                const g = satellite.gstime(t)
                const p = satellite.propagate(rec, t)
                if (!p || !p.position || typeof p.position === 'boolean') continue
                const od = satellite.eciToGeodetic(p.position as any, g)
                pts.push(Cartesian3.fromDegrees(CMath.toDegrees(od.longitude), CMath.toDegrees(od.latitude), od.height * 1000))
              }
              if (pts.length > 2) {
                orbitSrc.entities.add({
                  polyline: {
                    positions: pts,
                    width: 1.2,
                    material: new PolylineGlowMaterialProperty({
                      glowPower: 0.25,
                      color: Color.fromCssColorString('#00e5ff').withAlpha(0.3),
                    }),
                  },
                })
              }
            }
          } catch { /* skip */ }
        }
        for (const [name, e] of satMap) {
          if (!seen.has(name)) { satSrc.entities.remove(e); satMap.delete(name) }
        }
        orbitSrc.entities.resumeEvents()
        if (!cancelled) setStats((p) => ({ ...p, satellites: satMap.size }))
      }

      // ---------- EARTHQUAKES ----------
      const fetchQuakes = async () => {
        if (cancelled) return
        try {
          const r = await fetch('/api/earthquakes?period=day&magnitude=2.5')
          const d = await r.json()
          quakeSrc.entities.removeAll()
          for (const q of d.earthquakes || []) {
            if (q.lon == null || q.lat == null) continue
            const mag = q.mag ?? 0
            const sev = Math.min(mag / 8, 1)
            const ent = quakeSrc.entities.add({
              position: Cartesian3.fromDegrees(q.lon, q.lat, 0),
              point: {
                pixelSize: 4 + mag * 2.5,
                color: Color.fromHsl(0.02 + 0.08 * (1 - sev), 1.0, 0.5, 0.9),
                outlineColor: Color.BLACK,
                outlineWidth: 1,
              },
              properties: { kind: 'quake', place: q.place, mag, depth: q.depth, time: q.time } as any,
            })
            if (mag >= 4.5) {
              const t0 = Date.now()
              ent.ellipse = ({
                semiMajorAxis: new CallbackProperty(() => {
                  const ph = ((Date.now() - t0) % 2000) / 2000
                  return 30000 + ph * mag * 90000
                }, false) as any,
                semiMinorAxis: new CallbackProperty(() => {
                  const ph = ((Date.now() - t0) % 2000) / 2000
                  return (30000 + ph * mag * 90000) * 0.95
                }, false) as any,
                material: new ColorMaterialProperty(
                  new CallbackProperty(() => {
                    const ph = ((Date.now() - t0) % 2000) / 2000
                    return Color.fromCssColorString('#ff3b30').withAlpha(0.4 * (1 - ph))
                  }, false) as any
                ),
                height: 0,
              }) as any
            }
          }
          if (!cancelled) setStats((p) => ({ ...p, quakes: (d.earthquakes || []).length }))
        } catch (e) {
          console.error('quakes fetch failed', e)
        }
      }

      // ---------- NATURAL EVENTS ----------
      const eventColor = (cat: string) => {
        const c = (cat || '').toLowerCase()
        if (c.includes('fire')) return '#ff6b35'
        if (c.includes('volcano')) return '#ff2d00'
        if (c.includes('storm') || c.includes('cyclone')) return '#00d4ff'
        if (c.includes('ice') || c.includes('snow')) return '#e0f7ff'
        if (c.includes('flood') || c.includes('water')) return '#4dabf7'
        return '#ffd23f'
      }
      const fetchEvents = async () => {
        if (cancelled) return
        try {
          const r = await fetch('/api/events?limit=120')
          const d = await r.json()
          eventSrc.entities.removeAll()
          for (const ev of d.events || []) {
            if (ev.lon == null || ev.lat == null) continue
            const col = Color.fromCssColorString(eventColor(ev.category))
            eventSrc.entities.add({
              position: Cartesian3.fromDegrees(ev.lon, ev.lat, 0),
              point: {
                pixelSize: 9,
                color: col.withAlpha(0.9),
                outlineColor: Color.WHITE,
                outlineWidth: 1,
              },
              label: {
                text: ev.category,
                font: '600 10px "Courier New"',
                fillColor: col,
                outlineColor: Color.BLACK,
                outlineWidth: 2,
                style: LabelStyle.FILL_AND_OUTLINE,
                verticalOrigin: VerticalOrigin.BOTTOM,
                pixelOffset: new Cartesian2(0, -10),
                distanceDisplayCondition: new DistanceDisplayCondition(0, 1.5e7),
              },
              properties: { kind: 'event', title: ev.title, category: ev.category, date: ev.date } as any,
            })
          }
          if (!cancelled) setStats((p) => ({ ...p, events: (d.events || []).length }))
        } catch (e) {
          console.error('events fetch failed', e)
        }
      }

      // ---------- NODES (Pi + mesh) ----------
      const nodeMap = new Map<string, Entity>()
      const tempToColor = (t: number) => {
        // Green (40°C) → Yellow (55°C) → Red (70°C)
        const norm = Math.max(0, Math.min(1, (t - 40) / 30))
        return Color.fromHsl(0.35 * (1 - norm), 1.0, 0.5, 0.95)
      }
      const fetchNodes = async () => {
        if (cancelled) return
        try {
          const r = await fetch('/api/nodes/')
          const d = await r.json()
          const nodes: any[] = d.nodes || []
          const seen = new Set<string>()
          for (const n of nodes) {
            if (n.lon == null || n.lat == null) continue
            const id = n.node_id
            seen.add(id)
            const temp = n.health?.cpu_temp_c ?? 0
            const isOnline = n.online === true
            const pos = Cartesian3.fromDegrees(n.lon, n.lat, 0)
            let e = nodeMap.get(id)
            if (e) {
              ;(e.position as ConstantPositionProperty).setValue(pos)
            } else {
              e = nodesSrc.entities.add({
                id: 'node-' + id,
                position: new ConstantPositionProperty(pos),
                point: {
                  pixelSize: 14,
                  color: tempToColor(temp),
                  outlineColor: Color.BLACK,
                  outlineWidth: 2,
                  scaleByDistance: new NearFarScalar(1e4, 1.8, 1e7, 0.6),
                },
                label: {
                  text: n.name || id,
                  font: '600 11px "Courier New"',
                  fillColor: Color.fromCssColorString('#00e5a0'),
                  outlineColor: Color.BLACK,
                  outlineWidth: 2,
                  style: LabelStyle.FILL_AND_OUTLINE,
                  verticalOrigin: VerticalOrigin.BOTTOM,
                  horizontalOrigin: HorizontalOrigin.CENTER,
                  pixelOffset: new Cartesian2(0, -14),
                  distanceDisplayCondition: new DistanceDisplayCondition(0, 2e6),
                },
                properties: {
                  kind: 'node',
                  node_id: id,
                  name: n.name || id,
                  temp,
                  online: isOnline,
                  services: n.health?.services || {},
                  sensors: n.sensors || {},
                  mesh_count: (n.mesh || []).length,
                  pihole: n.pihole || {},
                  age_seconds: n.age_seconds ?? 0,
                } as any,
              })
              // Pulsing ring for online nodes
              if (isOnline) {
                const t0 = Date.now()
                ;(e as any).ellipse = {
                  semiMajorAxis: new CallbackProperty(() => {
                    const ph = ((Date.now() - t0) % 2000) / 2000
                    return 15000 + ph * 40000
                  }, false),
                  semiMinorAxis: new CallbackProperty(() => {
                    const ph = ((Date.now() - t0) % 2000) / 2000
                    return (15000 + ph * 40000) * 0.97
                  }, false),
                  material: new ColorMaterialProperty(
                    new CallbackProperty(() => {
                      const ph = ((Date.now() - t0) % 2000) / 2000
                      return tempToColor(temp).withAlpha(0.35 * (1 - ph))
                    }, false)
                  ),
                  height: 0,
                }
              }
              nodeMap.set(id, e)
            }
            // Mesh node points + connection lines
            for (const m of n.mesh || []) {
              if (m.lon != null && m.lat != null) {
                const mPos = Cartesian3.fromDegrees(m.lon, m.lat, 0)
                // Connection line
                nodesSrc.entities.add({
                  id: `link-${id}-${m.id}`,
                  polyline: {
                    positions: [pos, mPos],
                    width: 1.5,
                    material: new PolylineGlowMaterialProperty({
                      glowPower: 0.35,
                      color: Color.fromCssColorString('#00e5a0').withAlpha(0.45),
                    }),
                  },
                })
                // Mesh node point
                const meshKey = `mesh-${id}-${m.id}`
                seen.add(meshKey)
                const meshEnt = nodesSrc.entities.getById(meshKey)
                if (!meshEnt) {
                  nodesSrc.entities.add({
                    id: meshKey,
                    position: mPos,
                    point: {
                      pixelSize: 6,
                      color: Color.fromCssColorString('#ffd23f'),
                      outlineColor: Color.BLACK,
                      outlineWidth: 1,
                    },
                    label: {
                      text: m.name || m.id || '?',
                      font: '500 9px "Courier New"',
                      fillColor: Color.fromCssColorString('#ffd23f'),
                      outlineColor: Color.BLACK,
                      outlineWidth: 1,
                      style: LabelStyle.FILL_AND_OUTLINE,
                      verticalOrigin: VerticalOrigin.BOTTOM,
                      horizontalOrigin: HorizontalOrigin.CENTER,
                      pixelOffset: new Cartesian2(0, -6),
                      distanceDisplayCondition: new DistanceDisplayCondition(0, 5e5),
                    },
                    properties: {
                      kind: 'mesh_node',
                      id: m.id,
                      name: m.name || m.id,
                      snr: m.snr,
                      last_seen: m.last_seen,
                      pi_node: id,
                    } as any,
                  })
                }
              }
            }
          }
          for (const [id, e] of nodeMap) {
            if (!seen.has(id)) { nodesSrc.entities.remove(e); nodeMap.delete(id) }
          }
          // Cleanup stale mesh nodes
          const allMeshKeys = new Set<string>()
          nodesSrc.entities.values.forEach((ent: any) => {
            const eid = ent.id
            if (typeof eid === 'string' && eid.startsWith('mesh-')) {
              allMeshKeys.add(eid)
            }
          })
          for (const mk of allMeshKeys) {
            if (!seen.has(mk)) {
              const ent = nodesSrc.entities.getById(mk)
              if (ent) nodesSrc.entities.remove(ent)
            }
          }
          if (!cancelled) setStats((p) => ({ ...p, nodes: nodeMap.size }))
        } catch (e) {
          console.error('nodes fetch failed', e)
        }
      }

      // ---------- MILITARY AIRCRAFT ----------
      const milMap = new Map<string, Entity>()
      const fetchMilitary = async () => {
        if (cancelled) return
        try {
          const r = await fetch('/api/military/')
          const d = await r.json()
          const list: any[] = d.aircraft || []
          const seen = new Set<string>()
          for (const a of list) {
            if (a.lon == null || a.lat == null) continue
            const id = a.hex
            seen.add(id)
            const pos = Cartesian3.fromDegrees(a.lon, a.lat, Math.max(a.alt ?? 0, 0))
            let e = milMap.get(id)
            if (e) {
              ;(e.position as ConstantPositionProperty).setValue(pos)
            } else {
              const isEmergency = ['7500', '7600', '7700'].includes(a.squawk || '')
              e = militarySrc.entities.add({
                id: 'mil-' + id,
                position: new ConstantPositionProperty(pos),
                point: {
                  pixelSize: isEmergency ? 12 : 8,
                  color: isEmergency ? Color.fromCssColorString('#ff2d00') : Color.fromCssColorString('#ff6b35'),
                  outlineColor: Color.BLACK,
                  outlineWidth: 2,
                  scaleByDistance: new NearFarScalar(1e5, 1.8, 1e7, 0.5),
                },
                label: {
                  text: a.flight || a.hex,
                  font: '600 11px "Courier New"',
                  fillColor: isEmergency ? Color.fromCssColorString('#ff2d00') : Color.fromCssColorString('#ff9f7a'),
                  outlineColor: Color.BLACK,
                  outlineWidth: 2,
                  style: LabelStyle.FILL_AND_OUTLINE,
                  verticalOrigin: VerticalOrigin.BOTTOM,
                  horizontalOrigin: HorizontalOrigin.LEFT,
                  pixelOffset: new Cartesian2(8, -4),
                  distanceDisplayCondition: new DistanceDisplayCondition(0, 1.2e6),
                },
                properties: {
                  kind: 'military', hex: a.hex, flight: a.flight || '', type: a.type || '',
                  alt: a.alt ?? 0, speed: a.speed ?? 0, squawk: a.squawk || '',
                } as any,
              })
              if (isEmergency) {
                const t0 = Date.now()
                ;(e as any).ellipse = {
                  semiMajorAxis: new CallbackProperty(() => {
                    const ph = ((Date.now() - t0) % 1200) / 1200
                    return 20000 + ph * 80000
                  }, false),
                  semiMinorAxis: new CallbackProperty(() => {
                    const ph = ((Date.now() - t0) % 1200) / 1200
                    return (20000 + ph * 80000) * 0.97
                  }, false),
                  material: new ColorMaterialProperty(
                    new CallbackProperty(() => {
                      const ph = ((Date.now() - t0) % 1200) / 1200
                      return Color.fromCssColorString('#ff2d00').withAlpha(0.5 * (1 - ph))
                    }, false)
                  ),
                  height: 0,
                }
              }
              milMap.set(id, e)
            }
          }
          for (const [id, e] of milMap) {
            if (!seen.has(id)) { militarySrc.entities.remove(e); milMap.delete(id) }
          }
          if (!cancelled) setStats((p) => ({ ...p, military: milMap.size }))
        } catch (e) {
          console.error('military fetch failed', e)
        }
      }

      // ---------- SPACEWEATHER ----------
      const fetchSpaceweather = async () => {
        if (cancelled) return
        try {
          const r = await fetch('/api/spaceweather/')
          const d = await r.json()
          spaceweatherSrc.entities.removeAll()
          const kp = d.kp_index ?? 0
          // Aurora oval based on Kp (simple ring at auroral latitudes)
          const auroraLat = Math.min(55 + kp * 3, 75)
          const pts: Cartesian3[] = []
          for (let i = 0; i <= 128; i++) {
            const lon = (i / 128) * 360 - 180
            pts.push(Cartesian3.fromDegrees(lon, auroraLat, 120000))
          }
          spaceweatherSrc.entities.add({
            polyline: {
              positions: pts,
              width: 3,
              material: new PolylineGlowMaterialProperty({
                glowPower: 0.4,
                color: Color.fromHsl(0.35 - kp * 0.04, 1.0, 0.5, 0.6),
              }),
            },
          })
          // Southern hemisphere mirror
          const ptsS: Cartesian3[] = []
          for (let i = 0; i <= 128; i++) {
            const lon = (i / 128) * 360 - 180
            ptsS.push(Cartesian3.fromDegrees(lon, -auroraLat, 120000))
          }
          spaceweatherSrc.entities.add({
            polyline: {
              positions: ptsS,
              width: 3,
              material: new PolylineGlowMaterialProperty({
                glowPower: 0.4,
                color: Color.fromHsl(0.35 - kp * 0.04, 1.0, 0.5, 0.6),
              }),
            },
          })
          // Kp label at north pole
          spaceweatherSrc.entities.add({
            position: Cartesian3.fromDegrees(0, 88, 200000),
            label: {
              text: `Kp=${kp}`,
              font: '600 14px "Courier New"',
              fillColor: Color.fromCssColorString('#00e5a0'),
              outlineColor: Color.BLACK,
              outlineWidth: 2,
              style: LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: VerticalOrigin.CENTER,
              horizontalOrigin: HorizontalOrigin.CENTER,
            },
          })
          if (!cancelled) setStats((p) => ({ ...p, spaceweather: kp }))
        } catch (e) {
          console.error('spaceweather fetch failed', e)
        }
      }

      // ---------- WILDFIRES ----------
      const fetchWildfires = async () => {
        if (cancelled) return
        try {
          const r = await fetch('/api/wildfires/')
          const d = await r.json()
          wildfireSrc.entities.removeAll()
          const fires: any[] = d.fires || []
          for (const f of fires) {
            if (f.lon == null || f.lat == null) continue
            const conf = f.confidence ?? 0
            const color = conf >= 80 ? '#ff2d00' : conf >= 50 ? '#ff6b35' : '#ffd23f'
            wildfireSrc.entities.add({
              position: Cartesian3.fromDegrees(f.lon, f.lat, 0),
              point: {
                pixelSize: conf >= 80 ? 10 : conf >= 50 ? 8 : 6,
                color: Color.fromCssColorString(color).withAlpha(0.9),
                outlineColor: Color.WHITE,
                outlineWidth: 1,
                scaleByDistance: new NearFarScalar(1e5, 1.8, 1e7, 0.6),
              },
              label: {
                text: `${f.confidence_label || 'fire'} ${f.confidence ?? '?'}%`,
                font: '600 9px "Courier New"',
                fillColor: Color.fromCssColorString(color),
                outlineColor: Color.BLACK,
                outlineWidth: 2,
                style: LabelStyle.FILL_AND_OUTLINE,
                verticalOrigin: VerticalOrigin.BOTTOM,
                pixelOffset: new Cartesian2(0, -8),
                distanceDisplayCondition: new DistanceDisplayCondition(0, 2e6),
              },
              properties: {
                kind: 'wildfire',
                confidence: f.confidence,
                confidence_label: f.confidence_label,
                brightness: f.brightness,
                frp: f.frp,
                satellite: f.satellite,
                acq_date: f.acq_date,
              } as any,
            })
          }
          if (!cancelled) setStats((p) => ({ ...p, wildfires: fires.length }))
        } catch (e) {
          console.error('wildfires fetch failed', e)
        }
      }

      // ---------- LIGHTNING ----------
      const lightningMap = new Map<string, any>()
      const fetchLightning = async () => {
        if (cancelled) return
        try {
          const r = await fetch('/api/lightning/')
          const d = await r.json()
          const strikes: any[] = d.strikes || []
          const now = Date.now()
          // Remove strikes older than 10 minutes
          for (const [id, data] of lightningMap) {
            if (now - data.ts > 600000) {
              const e = data.entity
              if (e) lightningSrc.entities.remove(e)
              lightningMap.delete(id)
            }
          }
          for (const s of strikes) {
            if (s.lon == null || s.lat == null || !s.time) continue
            const ts = new Date(s.time).getTime()
            if (now - ts > 600000) continue
            const id = `${s.lat.toFixed(3)},${s.lon.toFixed(3)}`
            if (lightningMap.has(id)) continue
            const ageSec = (now - ts) / 1000
            const alpha = Math.max(0.2, 1 - ageSec / 600)
            const e = lightningSrc.entities.add({
              position: Cartesian3.fromDegrees(s.lon, s.lat, 0),
              point: {
                pixelSize: 10,
                color: Color.fromCssColorString('#22d3ee').withAlpha(alpha),
                outlineColor: Color.WHITE,
                outlineWidth: 1,
              },
              properties: {
                kind: 'lightning',
                time: s.time,
                stations: s.stations,
                participants: s.participants,
              } as any,
            })
            lightningMap.set(id, { entity: e, ts })
          }
          if (!cancelled) setStats((p) => ({ ...p, lightning: lightningMap.size }))
        } catch (e) {
          console.error('lightning fetch failed', e)
        }
      }

      // ---------- TRANSIT ----------
      const transitMap = new Map<string, Entity>()
      const fetchTransit = async () => {
        if (cancelled) return
        try {
          const r = await fetch('/api/transit/helsinki')
          const d = await r.json()
          if (d.error) {
            for (const [id, e] of transitMap) { transitSrc.entities.remove(e); transitMap.delete(id) }
            if (!cancelled) setStats((p) => ({ ...p, transit: 0 }))
            return
          }
          const vehicles: any[] = d.vehicles || []
          const seen = new Set<string>()
          for (const v of vehicles) {
            if (v.lon == null || v.lat == null) continue
            const id = v.id || `${v.lat},${v.lon}`
            seen.add(id)
            const pos = Cartesian3.fromDegrees(v.lon, v.lat, 0)
            let e = transitMap.get(id)
            if (e) {
              ;(e.position as ConstantPositionProperty).setValue(pos)
            } else {
              e = transitSrc.entities.add({
                id: 'tr-' + id,
                position: new ConstantPositionProperty(pos),
                point: {
                  pixelSize: 9,
                  color: Color.fromCssColorString('#ffd23f').withAlpha(0.9),
                  outlineColor: Color.BLACK,
                  outlineWidth: 1,
                  scaleByDistance: new NearFarScalar(1e5, 1.8, 1e7, 0.5),
                },
                label: {
                  text: v.route_id || 'BUS',
                  font: '600 9px "Courier New"',
                  fillColor: Color.fromCssColorString('#ffd23f'),
                  outlineColor: Color.BLACK,
                  outlineWidth: 2,
                  style: LabelStyle.FILL_AND_OUTLINE,
                  verticalOrigin: VerticalOrigin.BOTTOM,
                  horizontalOrigin: HorizontalOrigin.CENTER,
                  pixelOffset: new Cartesian2(0, -8),
                  distanceDisplayCondition: new DistanceDisplayCondition(0, 1.5e6),
                },
                properties: {
                  kind: 'transit',
                  id: v.id,
                  route_id: v.route_id,
                  bearing: v.bearing,
                  speed: v.speed,
                  label: v.label,
                } as any,
              })
              transitMap.set(id, e)
            }
          }
          for (const [id, e] of transitMap) {
            if (!seen.has(id)) { transitSrc.entities.remove(e); transitMap.delete(id) }
          }
          if (!cancelled) setStats((p) => ({ ...p, transit: transitMap.size }))
        } catch (e) {
          console.error('transit fetch failed', e)
        }
      }

      // ---------- MARITIME ----------
      const vesselMap = new Map<string, Entity>()
      const fetchMaritime = async () => {
        if (cancelled) return
        try {
          const r = await fetch('/api/maritime/')
          const d = await r.json()
          if (d.error) {
            for (const [id, e] of vesselMap) { maritimeSrc.entities.remove(e); vesselMap.delete(id) }
            if (!cancelled) setStats((p) => ({ ...p, maritime: 0 }))
            return
          }
          const vessels: any[] = d.vessels || []
          const seen = new Set<string>()
          for (const v of vessels) {
            if (v.lon == null || v.lat == null) continue
            const id = v.mmsi || `${v.lat},${v.lon}`
            seen.add(id)
            const pos = Cartesian3.fromDegrees(v.lon, v.lat, 0)
            let e = vesselMap.get(id)
            if (e) {
              ;(e.position as ConstantPositionProperty).setValue(pos)
            } else {
              const typeColor = v.type === 'Cargo' ? '#8B4513' : v.type === 'Tanker' ? '#000080' : v.type === 'Passenger' ? '#FF69B4' : v.type === 'Fishing' ? '#32CD32' : '#00e5ff'
              e = maritimeSrc.entities.add({
                id: 'vs-' + id,
                position: new ConstantPositionProperty(pos),
                point: {
                  pixelSize: 10,
                  color: Color.fromCssColorString(typeColor).withAlpha(0.9),
                  outlineColor: Color.WHITE,
                  outlineWidth: 1,
                  scaleByDistance: new NearFarScalar(1e5, 1.8, 1e7, 0.5),
                },
                label: {
                  text: v.name?.substring(0, 12) || v.type || 'Vessel',
                  font: '600 9px "Courier New"',
                  fillColor: Color.fromCssColorString(typeColor),
                  outlineColor: Color.BLACK,
                  outlineWidth: 2,
                  style: LabelStyle.FILL_AND_OUTLINE,
                  verticalOrigin: VerticalOrigin.BOTTOM,
                  horizontalOrigin: HorizontalOrigin.CENTER,
                  pixelOffset: new Cartesian2(0, -10),
                  distanceDisplayCondition: new DistanceDisplayCondition(0, 2e6),
                },
                properties: {
                  kind: 'maritime',
                  name: v.name,
                  mmsi: v.mmsi,
                  type: v.type,
                  course: v.course,
                  speed: v.speed,
                  destination: v.destination,
                  flag: v.flag,
                  length: v.length,
                } as any,
              })
              vesselMap.set(id, e)
            }
          }
          for (const [id, e] of vesselMap) {
            if (!seen.has(id)) { maritimeSrc.entities.remove(e); vesselMap.delete(id) }
          }
          if (!cancelled) setStats((p) => ({ ...p, maritime: vesselMap.size }))
        } catch (e) {
          console.error('maritime fetch failed', e)
        }
      }

      // ---------- GEOPOLITICS ----------
      const fetchGeopolitics = async () => {
        if (cancelled) return
        try {
          const r = await fetch('/api/geopolitics/')
          const d = await r.json()
          geopoliticsSrc.entities.removeAll()
          const disasters: any[] = d.disasters || []
          for (const dis of disasters) {
            // ReliefWeb API doesn't always include coordinates
            // We'll place markers at random offset for visibility
            // In production you'd geocode the country/region
            const lat = 0, lon = 0
            geopoliticsSrc.entities.add({
              position: Cartesian3.fromDegrees(lon, lat, 0),
              point: {
                pixelSize: 10,
                color: Color.fromCssColorString('#ff2d00'),
                outlineColor: Color.WHITE,
                outlineWidth: 1,
              },
              label: {
                text: dis.name.substring(0, 40),
                font: '600 10px "Courier New"',
                fillColor: Color.fromCssColorString('#ff6b35'),
                outlineColor: Color.BLACK,
                outlineWidth: 2,
                style: LabelStyle.FILL_AND_OUTLINE,
                verticalOrigin: VerticalOrigin.BOTTOM,
                pixelOffset: new Cartesian2(0, -10),
                distanceDisplayCondition: new DistanceDisplayCondition(0, 1.5e7),
              },
              properties: { kind: 'geopolitics', name: dis.name, status: dis.status, id: dis.id } as any,
            })
          }
          if (!cancelled) setStats((p) => ({ ...p, geopolitics: disasters.length }))
        } catch (e) {
          console.error('geopolitics fetch failed', e)
        }
      }

      // ---------- Interaction ----------
      const handler = new ScreenSpaceEventHandler(scene.canvas)
      handler.setInputAction((m: any) => {
        const ray = viewer!.camera.getPickRay(m.endPosition)
        if (ray) {
          const cart = scene.globe.pick(ray, scene)
          if (cart) {
            const c = Cartographic.fromCartesian(cart)
            setCursor({
              lon: CMath.toDegrees(c.longitude).toFixed(4),
              lat: CMath.toDegrees(c.latitude).toFixed(4),
              alt: c.height.toFixed(0),
            })
          }
        }
      }, ScreenSpaceEventType.MOUSE_MOVE)

      const selectEntity = (ent: Entity) => {
        const props = ent.properties as any
        const kind = props.kind?.getValue?.()
        if (kind === 'aircraft') {
          setTarget({
            kind, title: `✈ ${props.callsign?.getValue?.()}`,
            lines: [
              `ICAO24: ${props.icao?.getValue?.()}`,
              `COUNTRY: ${props.country?.getValue?.()}`,
              `ALTITUDE: ${Math.round(props.alt?.getValue?.() ?? 0)} m`,
              `VELOCITY: ${Math.round(props.vel?.getValue?.() ?? 0)} m/s`,
              `HEADING: ${Math.round(props.heading?.getValue?.() ?? 0)}°`,
            ],
          })
          viewer!.trackedEntity = ent
        } else if (kind === 'satellite') {
          setTarget({
            kind, title: `🛰 ${props.name?.getValue?.()}`,
            lines: [`ALTITUDE: ${Math.round(props.alt?.getValue?.() ?? 0)} m`, 'ORBIT: TRACKING'],
          })
          viewer!.trackedEntity = ent
        } else if (kind === 'quake') {
          setTarget({
            kind, title: `⊕ M${props.mag?.getValue?.()} SEISMIC`,
            lines: [
              `${props.place?.getValue?.()}`,
              `DEPTH: ${props.depth?.getValue?.()} km`,
              `TIME: ${new Date(props.time?.getValue?.()).toLocaleString()}`,
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'event') {
          setTarget({
            kind, title: `⚠ ${props.category?.getValue?.()}`,
            lines: [`${props.title?.getValue?.()}`, `DATE: ${new Date(props.date?.getValue?.()).toLocaleString()}`],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'military') {
          const sq = props.squawk?.getValue?.()
          setTarget({
            kind, title: `🎖 ${props.flight?.getValue?.() || props.hex?.getValue?.()}`,
            lines: [
              `HEX: ${props.hex?.getValue?.()}`,
              `TYPE: ${props.type?.getValue?.() || '—'}`,
              `ALTITUDE: ${Math.round(props.alt?.getValue?.() ?? 0)} m`,
              `SPEED: ${(props.speed?.getValue?.() ?? 0).toFixed(1)} m/s`,
              ...(sq ? [`SQUAWK: ${sq}${['7500', '7600', '7700'].includes(sq) ? ' ⚠ EMERGENCY' : ''}`] : []),
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'transit') {
          setTarget({
            kind, title: `🚌 TRANSIT ${props.route_id?.getValue?.() || '—'}`,
            lines: [
              `ID: ${props.id?.getValue?.() ?? '—'}`,
              `ROUTE: ${props.route_id?.getValue?.() ?? '—'}`,
              `BEARING: ${props.bearing?.getValue?.() ?? '—'}°`,
              `SPEED: ${props.speed?.getValue?.() != null ? props.speed.getValue() + ' m/s' : '—'}`,
              `LABEL: ${props.label?.getValue?.() ?? '—'}`,
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'maritime') {
          setTarget({
            kind, title: `🚢 ${props.name?.getValue?.() || 'Vessel'}`,
            lines: [
              `MMSI: ${props.mmsi?.getValue?.() ?? '—'}`,
              `TYPE: ${props.type?.getValue?.() ?? '—'}`,
              `COURSE: ${props.course?.getValue?.() ?? '—'}°`,
              `SPEED: ${props.speed?.getValue?.() != null ? props.speed.getValue() + ' kn' : '—'}`,
              `DESTINATION: ${props.destination?.getValue?.() ?? '—'}`,
              `FLAG: ${props.flag?.getValue?.() ?? '—'}`,
              `LENGTH: ${props.length?.getValue?.() != null ? props.length.getValue() + ' m' : '—'}`,
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'wildfire') {
          setTarget({
            kind, title: `🔥 WILDFIRE (${props.confidence_label?.getValue?.() || 'unknown'})`,
            lines: [
              `CONFIDENCE: ${props.confidence?.getValue?.() ?? '—'}%`,
              `BRIGHTNESS: ${props.brightness?.getValue?.() ?? '—'}K`,
              `FRP: ${props.frp?.getValue?.() ?? '—'} MW`,
              `SATELLITE: ${props.satellite?.getValue?.() ?? '—'}`,
              `DATE: ${props.acq_date?.getValue?.() ?? '—'}`,
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'lightning') {
          setTarget({
            kind, title: `⚡ LIGHTNING STRIKE`,
            lines: [
              `TIME: ${props.time?.getValue?.() ?? '—'}`,
              `STATIONS: ${props.stations?.getValue?.() ?? '—'}`,
              `PARTICIPANTS: ${props.participants?.getValue?.() ?? '—'}`,
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'node') {
          const svcs = props.services?.getValue?.() || {}
          const svcLines = Object.entries(svcs).map(([k, v]) => `  ${k}: ${v}`)
          const s = props.sensors?.getValue?.() || {}
          const sensorLines = Object.entries(s).map(([k, v]) => `  ${k}: ${v}`)
          const ph = props.pihole?.getValue?.() || {}
          setTarget({
            kind, title: `📡 ${props.name?.getValue?.()}`,
            lines: [
              `CPU TEMP: ${props.temp?.getValue?.()}°C`,
              `STATUS: ${props.online?.getValue?.() ? 'ONLINE' : 'OFFLINE'}`,
              `AGE: ${Math.round(props.age_seconds?.getValue?.() ?? 0)}s`,
              `MESH NODES: ${props.mesh_count?.getValue?.() ?? 0}`,
              ...(ph.blocked ? [`PI-HOLE: ${ph.blocked} blocked (${ph.percent}%)`] : []),
              ...(sensorLines.length ? ['SENSORS:', ...sensorLines] : []),
              ...(svcLines.length ? ['SERVICES:', ...svcLines] : []),
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        } else if (kind === 'mesh_node') {
          setTarget({
            kind, title: `📻 MESH ${props.name?.getValue?.() || 'Node'}`,
            lines: [
              `ID: ${props.id?.getValue?.() ?? '—'}`,
              `SNR: ${props.snr?.getValue?.() ?? '—'} dB`,
              `LAST SEEN: ${props.last_seen?.getValue?.() ?? '—'}`,
              `PI GATEWAY: ${props.pi_node?.getValue?.() ?? '—'}`,
            ],
          })
          viewer!.flyTo(ent, { duration: 1.5 })
        }
      }

      handler.setInputAction((click: any) => {
        const picked = scene.pick(click.position)
        if (defined(picked) && picked.id && picked.id.properties) {
          selectEntity(picked.id)
        } else {
          setTarget(null)
          if (viewer) viewer.trackedEntity = undefined
        }
      }, ScreenSpaceEventType.LEFT_CLICK)

      // ---------- FPS ----------
      let frames = 0, lastT = performance.now()
      scene.postRender.addEventListener(() => {
        frames++
        const now = performance.now()
        if (now - lastT >= 1000) {
          if (!cancelled) setStats((p) => ({ ...p, fps: frames }))
          frames = 0; lastT = now
        }
      })

      // ---------- Vision modes ----------
      let activeStage: PostProcessStage | null = null
      const applyVision = (mode: VisionMode) => {
        if (!viewer) return
        if (activeStage) { scene.postProcessStages.remove(activeStage); activeStage = null }
        let frag: string | null = null
        let uniforms: any
        if (mode === 'nvg') frag = NVG_FRAGMENT
        else if (mode === 'thermal') frag = THERMAL_FRAGMENT
        else if (mode === 'crt') { frag = CRT_FRAGMENT; uniforms = { aberration: 1.0 } }
        else if (mode === 'night') frag = NIGHT_FRAGMENT
        if (frag) {
          activeStage = scene.postProcessStages.add(new PostProcessStage({ fragmentShader: frag, uniforms })) as PostProcessStage
        }
      }

      apiRef.current = {
        applyVision,
        setSatGroup: async (g: string) => { await loadSatTLEs(g); propagateSats() },
        flyTo: (poi: typeof POIS[number]) => {
          if (!viewer) return
          viewer.trackedEntity = undefined
          viewer.camera.flyTo({
            destination: Cartesian3.fromDegrees(poi.lon, poi.lat, poi.height),
            orientation: {
              heading: CMath.toRadians(poi.heading ?? 0),
              pitch: CMath.toRadians(poi.pitch ?? -45),
              roll: 0,
            },
            duration: 2.5,
          })
        },
        unlock: () => { if (viewer) viewer.trackedEntity = undefined; focusSrc.entities.removeAll(); setTarget(null) },
        focusOn: (f: FocusTarget) => {
          if (!viewer) return
          viewer.trackedEntity = undefined
          viewer.camera.flyTo({
            destination: Cartesian3.fromDegrees(f.lon, f.lat, f.height ?? 400000),
            orientation: { heading: 0, pitch: CMath.toRadians(-55), roll: 0 },
            duration: 2.2,
          })
          setTarget({ kind: f.kind, title: f.title, lines: f.lines, link: f.link })
          focusSrc.entities.removeAll()
          const t0 = Date.now()
          const ring = () => ((Date.now() - t0) % 1600) / 1600
          focusSrc.entities.add({
            position: Cartesian3.fromDegrees(f.lon, f.lat, 0),
            point: {
              pixelSize: 11,
              color: Color.fromCssColorString('#00ffa3'),
              outlineColor: Color.WHITE,
              outlineWidth: 2,
              disableDepthTestDistance: Number.POSITIVE_INFINITY,
            },
            ellipse: {
              semiMajorAxis: new CallbackProperty(() => 20000 + ring() * 200000, false) as any,
              semiMinorAxis: new CallbackProperty(() => (20000 + ring() * 200000) * 0.97, false) as any,
              material: new ColorMaterialProperty(
                new CallbackProperty(() => Color.fromCssColorString('#00ffa3').withAlpha(0.5 * (1 - ring())), false) as any
              ),
              height: 0,
            } as any,
          })
        },
        setLayerVisibility: (l: any) => {
          aircraftSrc.show = l.aircraft
          satSrc.show = l.satellites
          orbitSrc.show = l.satellites && l.orbits
          quakeSrc.show = l.quakes
          eventSrc.show = l.events
          nodesSrc.show = l.nodes
          militarySrc.show = l.military
          spaceweatherSrc.show = l.spaceweather
          geopoliticsSrc.show = l.geopolitics
          wildfireSrc.show = l.wildfires
          lightningSrc.show = l.lightning
          transitSrc.show = l.transit
          maritimeSrc.show = l.maritime
        },
      }

      await loadSatTLEs('starlink')
      propagateSats()
      fetchAircraft()
      fetchQuakes()
      fetchEvents()
      fetchNodes()
      fetchMilitary()
      fetchSpaceweather()
      fetchGeopolitics()
      fetchWildfires()
      fetchLightning()
      fetchTransit()
      fetchMaritime()

      if (focusRef.current) apiRef.current.focusOn(focusRef.current)

      timers.push(setInterval(fetchAircraft, 10000))
      timers.push(setInterval(propagateSats, 3000))
      timers.push(setInterval(fetchQuakes, 300000))
      timers.push(setInterval(fetchEvents, 600000))
      timers.push(setInterval(fetchNodes, 30000))
      timers.push(setInterval(fetchMilitary, 15000))
      timers.push(setInterval(fetchSpaceweather, 300000))
      timers.push(setInterval(fetchGeopolitics, 600000))
      timers.push(setInterval(fetchWildfires, 300000))
      timers.push(setInterval(fetchLightning, 60000))
      timers.push(setInterval(fetchTransit, 30000))
      timers.push(setInterval(fetchMaritime, 45000))
    })()

    return () => {
      cancelled = true
      timers.forEach(clearInterval)
      if (viewer) { viewer.destroy(); viewerRef.current = null }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    focusRef.current = focus ?? null
    if (focus) apiRef.current.focusOn?.(focus)
  }, [focus])

  useEffect(() => { apiRef.current.applyVision?.(vision) }, [vision])
  useEffect(() => { apiRef.current.setSatGroup?.(satGroup) }, [satGroup])
  useEffect(() => { apiRef.current.setLayerVisibility?.(layers) }, [layers])

  const toggle = (k: keyof typeof layers) => setLayers((l) => ({ ...l, [k]: !l[k] }))

  return (
    <div className={`globe-wrap vision-${vision}`}>
      <div ref={containerRef} className="globe-canvas" />

      <div className="reticle">
        <div className="reticle-cross" />
        <span className="bracket tl" /><span className="bracket tr" />
        <span className="bracket bl" /><span className="bracket br" />
      </div>

      <div className="globe-hud">
        <div className="hud-title">LIVE TELEMETRY</div>
        <div className="hud-row"><span className="hud-dot yellow" />AIRCRAFT<span className="hud-val">{stats.aircraft}</span></div>
        <div className="hud-row"><span className="hud-dot cyan" />SATELLITES<span className="hud-val">{stats.satellites}</span></div>
        <div className="hud-row"><span className="hud-dot red" />SEISMIC<span className="hud-val">{stats.quakes}</span></div>
        <div className="hud-row"><span className="hud-dot orange" />EVENTS<span className="hud-val">{stats.events}</span></div>
        <div className="hud-row"><span className="hud-dot green" />NODES<span className="hud-val">{stats.nodes}</span></div>
        <div className="hud-row"><span className="hud-dot" style={{ background: '#ff6b35' }} />MILITARY<span className="hud-val">{stats.military}</span></div>
        <div className="hud-row"><span className="hud-dot" style={{ background: '#00e5a0' }} />KP INDEX<span className="hud-val">{stats.spaceweather}</span></div>
        <div className="hud-row"><span className="hud-dot" style={{ background: '#ff2d00' }} />CRISES<span className="hud-val">{stats.geopolitics}</span></div>
        <div className="hud-row"><span className="hud-dot" style={{ background: '#ff6b35' }} />WILDFIRES<span className="hud-val">{stats.wildfires}</span></div>
        <div className="hud-row"><span className="hud-dot" style={{ background: '#22d3ee' }} />LIGHTNING<span className="hud-val">{stats.lightning}</span></div>
        <div className="hud-row"><span className="hud-dot" style={{ background: '#ffd23f' }} />TRANSIT<span className="hud-val">{stats.transit}</span></div>
        <div className="hud-row"><span className="hud-dot" style={{ background: '#00e5ff' }} />MARITIME<span className="hud-val">{stats.maritime}</span></div>
        <div className="hud-divider" />
        <div className="hud-row">RENDER<span className="hud-val">{stats.fps} FPS</span></div>
        <div className="hud-row sub">LON {cursor.lon}  LAT {cursor.lat}</div>
        <div className="hud-row sub">ELEV {cursor.alt} m</div>
      </div>

      <div className="globe-controls">
        <div className="ctl-block">
          <div className="hud-title">OPTICS</div>
          <div className="vision-bar">
            {VISION_MODES.map((m) => (
              <button key={m.id} className={vision === m.id ? 'on' : ''} onClick={() => setVision(m.id)}>{m.label}</button>
            ))}
          </div>
        </div>

        <div className="ctl-block">
          <div className="hud-title">CONSTELLATION</div>
          <div className="vision-bar">
            {SAT_GROUPS.map((g) => (
              <button key={g.id} className={satGroup === g.id ? 'on' : ''} onClick={() => setSatGroup(g.id)}>{g.label}</button>
            ))}
          </div>
        </div>

        <div className="ctl-block">
          <div className="hud-title">LAYERS</div>
          {(['aircraft', 'satellites', 'orbits', 'quakes', 'events', 'nodes', 'military', 'spaceweather', 'geopolitics', 'wildfires', 'lightning', 'transit', 'maritime'] as const).map((k) => (
            <label key={k} className={layers[k] ? 'on' : ''}>
              <input type="checkbox" checked={layers[k]} onChange={() => toggle(k)} />{k.toUpperCase()}
            </label>
          ))}
        </div>

        <div className="ctl-block">
          <div className="hud-title">FLY TO</div>
          <select className="poi-select" defaultValue="" onChange={(e) => {
            const poi = POIS.find((p) => p.name === e.target.value)
            if (poi) apiRef.current.flyTo?.(poi)
          }}>
            <option value="">— select —</option>
            {POIS.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
          </select>
        </div>
      </div>

      {target && (
        <div className={`target-panel ${target.kind}`}>
          <div className="tp-head">
            <span>TARGET LOCK</span>
            <button onClick={() => { setTarget(null); apiRef.current.unlock?.() }}>✕</button>
          </div>
          <div className="tp-title">{target.title}</div>
          {target.lines.map((l, i) => <div key={i} className="tp-line">{l}</div>)}
          {target.link && (
            <a className="tp-link" href={target.link} target="_blank" rel="noreferrer">OPEN SOURCE ↗</a>
          )}
          {onAskAI && (
            <button className="tp-ask-ai" onClick={() => onAskAI(target.title, target.lines)}>✦ ASK AI</button>
          )}
        </div>
      )}
    </div>
  )
}
