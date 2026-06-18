import { useEffect, useState } from 'react'

import type { FocusTarget } from '../lib/focus'



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

  const u = cam.url || cam.image?.current?.preview || ''

  return u.trim()

}



function camLat(cam: WebcamCam): number | undefined {

  return cam.lat ?? cam.location?.latitude

}



function camLon(cam: WebcamCam): number | undefined {

  return cam.lon ?? cam.location?.longitude

}



function needsFreshStream(cam: WebcamCam): boolean {

  return cam.source === 'windy' || cam.id.startsWith('windy-')

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

  const [activeCam, setActiveCam] = useState<WebcamCam | null>(null)

  const [streamEmbed, setStreamEmbed] = useState<string | null>(null)

  const [streamLoading, setStreamLoading] = useState(false)

  const [streamError, setStreamError] = useState<string | null>(null)

  const cats = ['all', ...(webcams?.categories || [])]



  useEffect(() => {

    if (!activeCam) {

      setStreamEmbed(null)

      setStreamLoading(false)

      setStreamError(null)

      return

    }



    let cancelled = false



    async function loadStream() {

      setStreamError(null)

      if (activeCam!.embed) {

        setStreamEmbed(activeCam!.embed)

        setStreamLoading(false)

        return

      }



      if (needsFreshStream(activeCam!)) {

        setStreamLoading(true)

        setStreamEmbed(null)

        try {

          const r = await fetch(`/api/webcams/${encodeURIComponent(activeCam!.id)}`)

          if (!r.ok) throw new Error('Stream unavailable')

          const data = await r.json()

          const fresh = data.webcam as WebcamCam

          if (cancelled) return

          if (fresh?.embed) {

            setStreamEmbed(fresh.embed)

          } else if (fresh?.url) {

            setStreamEmbed(null)

            setStreamError('No live player for this cam — showing snapshot')

          } else {

            setStreamError('No stream URL returned')

          }

        } catch {

          if (!cancelled) setStreamError('Failed to load live stream')

        } finally {

          if (!cancelled) setStreamLoading(false)

        }

        return

      }



      setStreamEmbed(activeCam!.embed || null)

      setStreamLoading(false)

    }



    loadStream()

    return () => {

      cancelled = true

    }

  }, [activeCam])



  const openCam = (cam: WebcamCam) => {

    setActiveCam(cam)

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

            const lat = camLat(cam)

            const lon = camLon(cam)

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

                {lat != null && lon != null && (

                  <button

                    type="button"

                    className="locate-mini"

                    onClick={(e) => {

                      e.stopPropagation()

                      onFocus({

                        kind: 'webcam',

                        lat,

                        lon,

                        title,

                        height: 50000,

                        lines: [`SOURCE: ${cam.source || 'webcam'}`, `CATEGORY: ${cam.category || '—'}`],

                      })

                    }}

                  >

                    ◎ LOCATE

                  </button>

                )}

              </div>

            )

          })}

        </div>

      )}



      {activeCam && (

        <div className="webcam-modal" onClick={() => setActiveCam(null)}>

          <div className="webcam-modal-content" onClick={(e) => e.stopPropagation()}>

            <h3>{camTitle(activeCam)}</h3>

            <p className="webcam-modal-meta">

              {[activeCam.category, activeCam.country || activeCam.location?.country, activeCam.source]

                .filter(Boolean)

                .join(' · ')}

              {activeCam.live ? ' · LIVE STREAM' : activeCam.embed || streamEmbed ? ' · STREAM' : ''}

            </p>



            <div className="webcam-player-wrap">

              {streamLoading && <div className="health-status pending webcam-stream-loading">LOADING STREAM…</div>}

              {!streamLoading && streamEmbed && (

                <iframe

                  src={streamEmbed}

                  title={camTitle(activeCam)}

                  className="webcam-embed"

                  allow="autoplay; encrypted-media; fullscreen; picture-in-picture"

                  allowFullScreen

                />

              )}

              {!streamLoading && !streamEmbed && camThumb(activeCam) && (

                <img src={camThumb(activeCam)} alt={camTitle(activeCam)} className="webcam-modal-img" />

              )}

              {!streamLoading && !streamEmbed && !camThumb(activeCam) && (

                <div className="health-status pending">No preview available</div>

              )}

              {streamError && !streamEmbed && (

                <div className="health-status pending">{streamError}</div>

              )}

            </div>



            {camLat(activeCam) != null && camLon(activeCam) != null && (

              <p className="webcam-modal-coords">

                {camLat(activeCam)!.toFixed(4)}, {camLon(activeCam)!.toFixed(4)}

                <button

                  type="button"

                  className="locate-mini"

                  onClick={() => {

                    setActiveCam(null)

                    onFocus({

                      kind: 'webcam',

                      lat: camLat(activeCam)!,

                      lon: camLon(activeCam)!,

                      title: camTitle(activeCam),

                      height: 50000,

                      lines: [],

                    })

                  }}

                  style={{ marginLeft: 10 }}

                >

                  ◎ LOCATE

                </button>

              </p>

            )}



            {activeCam.detail_url && (

              <p className="webcam-modal-link">

                <a href={activeCam.detail_url} target="_blank" rel="noopener noreferrer">

                  OPEN ON WINDY.COM

                </a>

              </p>

            )}



            {activeCam.source === 'windy' && (

              <p className="webcam-powered-by">

                Webcam data via{' '}

                <a href="https://www.windy.com/webcams" target="_blank" rel="noopener noreferrer">

                  Windy.com

                </a>

              </p>

            )}



            <button type="button" onClick={() => setActiveCam(null)} className="close-btn">

              CLOSE

            </button>

          </div>

        </div>

      )}

    </div>

  )

}

