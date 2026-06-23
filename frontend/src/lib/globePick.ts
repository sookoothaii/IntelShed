import type { Entity } from 'cesium'

/** Metadata attached to PointPrimitive.id (non-Entity globe picks). */
export type GlobePrimitivePick = {
  kind: string
  lon: number
  lat: number
  [key: string]: unknown
}

export type GlobePick = {
  entity?: Entity
  meta: Record<string, unknown>
  prop: (key: string) => unknown
}

function entityPropReader(props: Entity['properties']): (key: string) => unknown {
  return (k: string) => {
    const p = (props as Record<string, { getValue?: () => unknown }> | undefined)?.[k]
    return typeof p?.getValue === 'function' ? p.getValue() : p
  }
}

/** Resolve hover/click metadata from scene.pick() — Entity or PointPrimitive.id. */
export function resolveGlobePick(picked: { id?: unknown } | undefined): GlobePick | null {
  if (!picked?.id) return null

  const id = picked.id
  if (typeof id === 'object' && id !== null && 'properties' in id) {
    const ent = id as Entity
    const props = ent.properties
    if (!props) return null
    const prop = entityPropReader(props)
    const kind = prop('kind')
    if (!kind) return null
    return { entity: ent, meta: { kind: String(kind) }, prop }
  }

  if (typeof id === 'object' && id !== null && 'kind' in id) {
    const meta = id as GlobePrimitivePick
    return {
      meta,
      prop: (k: string) => meta[k],
    }
  }

  return null
}
