import { useEffect, useRef } from 'react';
import {
  CustomDataSource,
  Cartesian3,
  ConstantPositionProperty,
  Color,
  LabelStyle,
  VerticalOrigin,
  HorizontalOrigin,
  Cartesian2,
  DistanceDisplayCondition,
  type Viewer,
  type Entity,
} from 'cesium';
import { attachDataSource, detachDataSource, requestSceneRender } from './layerUtils';
import { attachPulseEllipse } from './pulseAnimation';
import { AGENT_PHASE_EVENT, type AgentPhaseDetail } from '../../lib/agentBus';

const PHASE_COLORS: Record<string, Color> = {
  Coverage: Color.fromCssColorString('#00e5ff'),
  Retrieval: Color.fromCssColorString('#00e5a0'),
  Spatial: Color.fromCssColorString('#ffd23f'),
  Corroboration: Color.fromCssColorString('#ff6b35'),
  Synthesis: Color.fromCssColorString('#ff2d00'),
  Critique: Color.fromCssColorString('#a855f7'),
  Revise: Color.fromCssColorString('#a855f7'),
};

const DEFAULT_LAT = 13.7563;
const DEFAULT_LON = 100.5018;

const PHASE_OFFSETS: Record<string, [number, number]> = {
  Coverage: [0, 0],
  Retrieval: [1, -1],
  Spatial: [-1, 1],
  Corroboration: [1, 1],
  Synthesis: [-1, -1],
  Critique: [0, 2],
  Revise: [0, -2],
};

const EXPIRE_MS = 10_000;

type ActivePulse = {
  entity: Entity;
  cleanup: () => void;
  expireAt: number;
};

export function useAgentSwarm({ viewer, active }: { viewer: Viewer | null; active: boolean }) {
  const srcRef = useRef<CustomDataSource | null>(null);
  const pulsesRef = useRef(new Map<string, ActivePulse>());

  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('agent-swarm');
    attachDataSource(viewer, src);
    srcRef.current = src;

    const expireTimer = setInterval(() => {
      const now = Date.now();
      for (const [key, pulse] of pulsesRef.current) {
        if (now > pulse.expireAt) {
          pulse.cleanup();
          src.entities.remove(pulse.entity);
          pulsesRef.current.delete(key);
          requestSceneRender(viewer);
        }
      }
    }, 2000);

    return () => {
      clearInterval(expireTimer);
      for (const pulse of pulsesRef.current.values()) pulse.cleanup();
      pulsesRef.current.clear();
      detachDataSource(viewer, src);
      srcRef.current = null;
    };
  }, [viewer]);

  useEffect(() => {
    if (srcRef.current) srcRef.current.show = active;
  }, [active]);

  useEffect(() => {
    if (!active) return;

    const onPhase = (ev: Event) => {
      const detail = (ev as CustomEvent<AgentPhaseDetail>).detail;
      if (!detail?.title) return;
      const src = srcRef.current;
      if (!src) return;

      const title = detail.title;
      const color = PHASE_COLORS[title] ?? Color.fromCssColorString('#00e5ff');
      const [dLat, dLon] = PHASE_OFFSETS[title] ?? [0, 0];
      const lat = detail.lat ?? DEFAULT_LAT + dLat;
      const lon = detail.lon ?? DEFAULT_LON + dLon;
      const pos = Cartesian3.fromDegrees(lon, lat, 0);

      const existing = pulsesRef.current.get(title);
      if (existing) {
        (existing.entity.position as ConstantPositionProperty).setValue(pos);
        existing.expireAt = Date.now() + EXPIRE_MS;
        requestSceneRender(viewer);
        return;
      }

      const entity = src.entities.add({
        id: `agent-swarm-${title}`,
        position: new ConstantPositionProperty(pos),
        label: {
          text: title.toUpperCase(),
          font: '700 11px "Courier New"',
          fillColor: color,
          outlineColor: Color.BLACK,
          outlineWidth: 2,
          style: LabelStyle.FILL_AND_OUTLINE,
          verticalOrigin: VerticalOrigin.BOTTOM,
          horizontalOrigin: HorizontalOrigin.CENTER,
          pixelOffset: new Cartesian2(0, -8),
          distanceDisplayCondition: new DistanceDisplayCondition(0, 3e6),
        },
        properties: { kind: 'agent_swarm', phase: title },
      });

      const cleanup = attachPulseEllipse(entity, {
        baseRadius: 50000,
        pulseScale: 200000,
        color,
        alphaScale: 0.5,
        cycleMs: 1500,
      });

      pulsesRef.current.set(title, {
        entity,
        cleanup,
        expireAt: Date.now() + EXPIRE_MS,
      });
      requestSceneRender(viewer);
    };

    window.addEventListener(AGENT_PHASE_EVENT, onPhase);
    return () => window.removeEventListener(AGENT_PHASE_EVENT, onPhase);
  }, [active, viewer]);
}
