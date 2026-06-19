import TrafficCamPanel, { type TrafficCamRef } from './TrafficCamPanel'
import WebcamStreamPanel, { type WebcamStreamRef } from './WebcamStreamPanel'
import { fetchApi } from '../lib/networkFetch'
import { useEffect, useState } from 'react'

export type GlobeDetailTarget = {
  kind: string
  title: string
  lines: string[]
  link?: string
  entityId?: string
  trafficCam?: TrafficCamRef
  webcam?: WebcamStreamRef
  weatherCell?: {
    lat: number
    lon: number
    temperature_c?: number | null
    wind_speed_ms?: number | null
    precip_mm_3h?: number | null
  }
}

function EntityContextCard({ entityId }: { entityId: string }) {
  const [ctx, setCtx] = useState<any>(null)
  useEffect(() => {
    let active = true
    fetchApi(`/api/entity/${entityId}/context`)
      .then((r) => r.json())
      .then((d) => active && setCtx(d))
      .catch(() => {})
    return () => { active = false }
  }, [entityId])
  if (!ctx || ctx.error) return null
  const related = ctx.related || []
  if (!related.length) return null
  return (
    <div className="globe-detail-related">
      <div className="tp-line" style={{ color: '#00ffa3', fontWeight: 'bold' }}>
        RELATED ENTITIES · {related.length}
      </div>
      {related.slice(0, 8).map((r: any) => (
        <div key={r.id} className="tp-line" style={{ paddingLeft: 6, borderLeft: '2px solid #00ffa3' }}>
          {r.label || r.id} <span style={{ opacity: 0.5 }}>({r.type})</span>
        </div>
      ))}
    </div>
  )
}

export default function GlobeDetailModal({
  target,
  onClose,
  onSelectTrafficCam,
  onOpenWindy,
  onAskAI,
}: {
  target: GlobeDetailTarget
  onClose: () => void
  onSelectTrafficCam?: (cam: TrafficCamRef) => void
  onOpenWindy?: (lat: number, lon: number) => void
  onAskAI?: (title: string, lines: string[]) => void
}) {
  const isStream =
    (target.kind === 'traffic_cam' && Boolean(target.trafficCam)) ||
    (target.kind === 'webcam' && Boolean(target.webcam))

  return (
    <div className="globe-detail-modal" role="dialog" aria-modal="true" onClick={onClose}>
      <div className="globe-detail-modal-content" onClick={(e) => e.stopPropagation()}>
        <div className="globe-detail-modal-head">
          <span className="globe-detail-modal-badge">
            {isStream ? 'LIVE FEED' : 'GLOBE INTEL'}
          </span>
          <button type="button" className="globe-detail-close" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <h3 className="globe-detail-title">{target.title}</h3>

        {target.kind === 'traffic_cam' && target.trafficCam && (
          <TrafficCamPanel
            cam={target.trafficCam}
            onSelectCam={onSelectTrafficCam}
            streamMode
          />
        )}

        {target.kind === 'webcam' && target.webcam && (
          <WebcamStreamPanel cam={{ ...target.webcam, name: target.title }} />
        )}

        {target.kind === 'weather' && target.weatherCell && (
          <div className="globe-detail-weather">
            <div className="globe-detail-weather-grid">
              <div>
                <span className="globe-detail-k">TEMP</span>
                <span className="globe-detail-v">
                  {target.weatherCell.temperature_c != null
                    ? `${Math.round(target.weatherCell.temperature_c)}°C`
                    : '—'}
                </span>
              </div>
              <div>
                <span className="globe-detail-k">WIND</span>
                <span className="globe-detail-v">
                  {target.weatherCell.wind_speed_ms != null
                    ? `${target.weatherCell.wind_speed_ms} m/s`
                    : '—'}
                </span>
              </div>
              <div>
                <span className="globe-detail-k">RAIN 3H</span>
                <span className="globe-detail-v">
                  {target.weatherCell.precip_mm_3h != null
                    ? `${target.weatherCell.precip_mm_3h.toFixed(1)} mm`
                    : '—'}
                </span>
              </div>
            </div>
            <p className="globe-detail-hint">
              Weather grid cell — not a traffic camera. Enable TRAFFIC CAMS layer and zoom to Singapore
              for live road feeds, or open Windy for forecast at this point.
            </p>
            {onOpenWindy && (
              <button
                type="button"
                className="refresh-btn"
                onClick={() =>
                  onOpenWindy(target.weatherCell!.lat, target.weatherCell!.lon)
                }
              >
                OPEN WINDY AT POINT
              </button>
            )}
          </div>
        )}

        {target.lines.length > 0 && (
          <div className="globe-detail-lines">
            {target.lines.map((l, i) => (
              <div key={i} className="tp-line">{l}</div>
            ))}
          </div>
        )}

        {target.link && target.kind !== 'traffic_cam' && target.kind !== 'webcam' && (
          <a className="tp-link" href={target.link} target="_blank" rel="noreferrer">
            OPEN SOURCE ↗
          </a>
        )}

        {target.entityId && <EntityContextCard entityId={target.entityId} />}

        {onAskAI && (
          <button
            type="button"
            className="tp-ask-ai"
            style={{ marginTop: 10 }}
            onClick={() => onAskAI(target.title, target.lines)}
          >
            ✦ ASK AI
          </button>
        )}
      </div>
    </div>
  )
}
