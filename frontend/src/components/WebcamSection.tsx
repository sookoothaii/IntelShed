import { useState } from 'react'
import type { FocusTarget } from '../lib/focus'
import WebcamStreamPanel from './WebcamStreamPanel'

type WebcamCam = {
  id: string
  name?: string
  title?: string
  country?: string
  lat?: number
  lon?: number
  category?: string
  url?: string
  embed?: string | null
  detail_url?: string
  live?: boolean
  source?: string
  windy_id?: number
  image?: { current?: { preview?: string } }
  location?: { city?: string; country?: string; latitude?: number; longitude?: number }
}

function camTitle(cam: WebcamCam): string {
  return cam.name || cam.title || cam.id
}

function camThumb(cam: WebcamCam): string {
  return (cam.url || cam.image?.current?.preview || '').trim()
}

function camLat(cam: WebcamCam): number | undefined {
  return cam.lat ?? cam.location?.latitude
}

function camLon(cam: WebcamCam): number | undefined {
  return cam.lon ?? cam.location?.longitude
}

function buildWebcamFocus(cam: WebcamCam): Omit<FocusTarget, 'ts'> | null {
  const lat = camLat(cam)
  const lon = camLon(cam)
  if (lat == null || lon == null) return null
  const title = camTitle(cam)
  return {
    kind: 'webcam',
    lat,
    lon,
    height: 12000,
    title,
    lines: [
      `SOURCE: ${cam.source || 'webcam'}`,
      `CATEGORY: ${cam.category || '—'}`,
      ...(cam.country || cam.location?.country
        ? [`COUNTRY: ${cam.country || cam.location?.country}`]
        : []),
    ],
    link: cam.detail_url,
    webcam: {
      id: cam.id,
      name: title,
      source: cam.source,
      embed: cam.embed,
      url: camThumb(cam) || undefined,
      detail_url: cam.detail_url,
      category: cam.category,
      country: cam.country || cam.location?.country,
    },
  }
}

export default function WebcamSection({
  webcams,
  webcamCategory,
  setWebcamCategory,
  onLoad,
  loading,
  onFocus,
}: {
  webcams: {
    count: number
    categories: string[]
    webcams: WebcamCam[]
    cached_at: string
    windy_count?: number
    static_count?: number
    windy_configured?: boolean
  } | null
  webcamCategory: string
  setWebcamCategory: (c: string) => void
  onLoad: () => void
  loading: boolean | undefined
  onFocus: (f: Omit<FocusTarget, 'ts'>) => void
}) {
  const [noGeoCam, setNoGeoCam] = useState<WebcamCam | null>(null)
  const cats = ['all', ...(webcams?.categories || [])]

  const openCam = (cam: WebcamCam) => {
    const focus = buildWebcamFocus(cam)
    if (focus) {
      onFocus(focus)
      return
    }
    setNoGeoCam(cam)
  }

  return (
    <div className="webcam-section">
      <div className="webcam-controls">
        <button type="button" onClick={onLoad} disabled={loading} className="refresh-btn">
          {loading ? 'LOADING…' : '↻ REFRESH'}
        </button>
        {webcams && (
          <>
            <span className="data-count">
              {webcams.count} cams
              {webcams.windy_count != null ? ` · ${webcams.windy_count} windy` : ''}
            </span>
            <select
              value={webcamCategory || 'all'}
              onChange={(e) => setWebcamCategory(e.target.value === 'all' ? '' : e.target.value)}
            >
              {cats.map((c) => (
                <option key={c} value={c}>
                  {c.toUpperCase()}
                </option>
              ))}
            </select>
          </>
        )}
      </div>

      {webcams && webcams.windy_configured === false && (
        <div className="health-status pending webcam-hint">
          Add WINDY_WEBCAM_API_KEY in backend/.env for thousands more live cams via Windy.com
        </div>
      )}

      {webcams && webcams.count === 0 && (
        <div className="health-status pending">No webcams in this category</div>
      )}

      {webcams && webcams.count > 0 && (
        <div className="webcam-grid">
          {webcams.webcams.map((cam) => {
            const thumb = camThumb(cam)
            const title = camTitle(cam)
            const hasStream = Boolean(cam.embed || cam.source === 'windy' || cam.source === 'youtube')
            return (
              <div key={cam.id} className="webcam-card" onClick={() => openCam(cam)}>
                <div className="webcam-thumb-container">
                  {thumb ? (
                    <img
                      src={thumb}
                      alt={title}
                      loading="lazy"
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.display = 'none'
                      }}
                    />
                  ) : (
                    <div className="webcam-thumb-placeholder">{hasStream ? 'LIVE' : 'NO PREVIEW'}</div>
                  )}
                  {hasStream && <span className="webcam-live-badge">LIVE</span>}
                </div>
                <div className="webcam-label">{title}</div>
                <div className="webcam-meta">
                  {[cam.category, cam.country, cam.source].filter(Boolean).join(' · ')}
                </div>
                {camLat(cam) != null && camLon(cam) != null && (
                  <button
                    type="button"
                    className="locate-mini"
                    onClick={(e) => {
                      e.stopPropagation()
                      const focus = buildWebcamFocus(cam)
                      if (focus) onFocus(focus)
                    }}
                  >
                    ◎ OPEN ON GLOBE
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}

      {noGeoCam && (
        <div className="webcam-modal" onClick={() => setNoGeoCam(null)}>
          <div className="webcam-modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>{camTitle(noGeoCam)}</h3>
            <p className="webcam-modal-meta">
              {[noGeoCam.category, noGeoCam.country, noGeoCam.source].filter(Boolean).join(' · ')}
            </p>
            <WebcamStreamPanel
              cam={{
                id: noGeoCam.id,
                name: camTitle(noGeoCam),
                source: noGeoCam.source,
                embed: noGeoCam.embed,
                url: camThumb(noGeoCam) || undefined,
                detail_url: noGeoCam.detail_url,
                category: noGeoCam.category,
                country: noGeoCam.country,
              }}
            />
            <button type="button" onClick={() => setNoGeoCam(null)} className="close-btn">
              CLOSE
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
