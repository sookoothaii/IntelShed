import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CustomDataSource,
  Entity,
  Cartesian3,
  ConstantPositionProperty,
  Color,
  NearFarScalar,
  LabelStyle,
  VerticalOrigin,
  HorizontalOrigin,
  Cartesian2,
  DistanceDisplayCondition,
  Viewer
} from 'cesium';
import { fetchApi } from '../../lib/networkFetch';
import { attachDataSource, detachDataSource, requestSceneRender } from './layerUtils';
import { attachPulseEllipse } from './pulseAnimation';
import type { Stats, WbNode } from '../../lib/types';
import { feedMarkerColor, isMssTheme } from './markerPalette';
import type { ThemeId } from '../../lib/theme';

export function useNodesLayer({
  viewer,
  active,
  feedActive,
  canFetch,
  setStats,
  theme: _theme = 'cyber',
}: {
  viewer: Viewer | null;
  active: boolean;
  feedActive: boolean;
  canFetch: boolean;
  setStats: React.Dispatch<React.SetStateAction<Stats>>;
  theme?: ThemeId;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);
  const nodeMapRef = useRef(new Map<string, Entity>());
  const pulseCleanupByNode = useRef(new Map<string, () => void>());

  const { data } = useQuery({
    queryKey: ['nodes'],
    queryFn: async () => {
      const r = await fetchApi('/api/nodes');
      return r.json();
    },
    refetchInterval: 60000,
    enabled: active && feedActive && canFetch,
  });

  const tempToColor = (t: number) => {
    if (isMssTheme()) return feedMarkerColor('nodes', Color.fromHsl(0.35, 1.0, 0.5, 0.95));
    const norm = Math.max(0, Math.min(1, (t - 40) / 30));
    return Color.fromHsl(0.35 * (1 - norm), 1.0, 0.5, 0.95);
  };

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('nodes');
    attachDataSource(viewer, src);
    srcRef.current = src;
    
    return () => {
      for (const fn of pulseCleanupByNode.current.values()) fn();
      pulseCleanupByNode.current.clear();
      detachDataSource(viewer, src);
      srcRef.current = null;
      nodeMapRef.current.clear();
    };
  }, [viewer]);

  useEffect(() => {
    if (!srcRef.current) return;
    srcRef.current.show = active;
  }, [active]);

  useEffect(() => {
    if (!data || !srcRef.current || !active) return;
    const src = srcRef.current;
    const nodeMap = nodeMapRef.current;
    const nodes: WbNode[] = data.nodes || [];
    const seen = new Set<string>();

    src.entities.suspendEvents();
    
    for (const n of nodes) {
      if (n.lon == null || n.lat == null) continue;
      const id = n.node_id;
      seen.add(id);
      const temp = n.health?.cpu_temp_c ?? 0;
      const isOnline = n.online === true;
      const pos = Cartesian3.fromDegrees(n.lon, n.lat, 0);
      
      let e = nodeMap.get(id);
      if (e) {
        (e.position as ConstantPositionProperty).setValue(pos);
      } else {
        e = src.entities.add({
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
          },
        });
        
        if (isOnline) {
          pulseCleanupByNode.current.set(
            id,
            attachPulseEllipse(e, {
              baseRadius: 15000,
              pulseScale: 40000,
              color: tempToColor(temp),
              alphaScale: 0.35,
            }),
          );
        }
        nodeMap.set(id, e);
      }
      
      // Handle mesh nodes
      for (const m of n.mesh || []) {
        if (m.lon != null && m.lat != null) {
          const mPos = Cartesian3.fromDegrees(m.lon, m.lat, 0);
          const meshKey = `mesh-${id}-${m.id}`;
          seen.add(meshKey);
          
          if (!src.entities.getById(meshKey)) {
            src.entities.add({
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
              },
            });
            
            src.entities.add({
              id: `link-${id}-${m.id}`,
              polyline: {
                positions: [pos, mPos],
                width: 1.5,
                material: Color.fromCssColorString('#00e5a0').withAlpha(0.45),
              },
            });
          }
        }
      }
    }
    
    // Cleanup removed nodes
    for (const [id, e] of nodeMap) {
      if (!seen.has(id)) {
        pulseCleanupByNode.current.get(id)?.();
        pulseCleanupByNode.current.delete(id);
        src.entities.remove(e);
        nodeMap.delete(id);
      }
    }
    
    const allMeshKeys = new Set<string>();
    src.entities.values.forEach((ent: Entity) => {
      const eid = ent.id;
      if (typeof eid === 'string' && (eid.startsWith('mesh-') || eid.startsWith('link-'))) {
        allMeshKeys.add(eid);
      }
    });
    for (const mk of allMeshKeys) {
      const rawId = mk.startsWith('link-') ? mk.replace('link-', 'mesh-') : mk;
      if (!seen.has(rawId)) {
        const ent = src.entities.getById(mk);
        if (ent) src.entities.remove(ent);
      }
    }
    
    src.entities.resumeEvents();
    setStats((p: Stats) => ({ ...p, nodes: nodeMap.size }));
    requestSceneRender(viewer);
  }, [viewer, data, active, setStats]);
}
