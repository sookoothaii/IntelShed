import { useEffect, useState } from 'react'
import { fetchApi } from '../lib/networkFetch'

export type WebcamStreamRef = {
  id: string
  name?: string
  source?: string
  url?: string
  embed?: string | null
  detail_url?: string
  category?: string
  country?: string
}

function needsFreshStream(cam: WebcamStreamRef): boolean {
  return cam.source === 'windy' || cam.id.startsWith('windy-')
}

export default function WebcamStreamPanel({ cam }: { cam: WebcamStreamRef }) {
  const [streamEmbed, setStreamEmbed] = useState<string | null>(cam.embed || null)
  const [streamLoading, setStreamLoading] = useState(false)
  const [streamError, setStreamError] = useState<string | null>(null)
  const thumb = (cam.url || '').trim()

  useEffect(() => {
    let cancelled = false

    async function loadStream() {
      setStreamError(null)

      if (cam.embed) {
        setStreamEmbed(cam.embed)
        setStreamLoading(false)
        return
      }

      if (needsFreshStream(cam)) {
        setStreamLoading(true)
        setStreamEmbed(null)
        try {
          const r = await fetchApi(`/api/webcams/${encodeURIComponent(cam.id)}`)
          if (!r.ok) throw new Error('Stream unavailable')
          const data = await r.json()
          const fresh = data.webcam as WebcamStreamRef
          if (cancelled) return
          if (fresh?.embed) {
            setStreamEmbed(fresh.embed)
          } else if (fresh?.url || thumb) {
            setStreamEmbed(null)
            setStreamError('No live player — showing snapshot')
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

      setStreamEmbed(cam.embed || null)
      setStreamLoading(false)
    }

    loadStream()
    return () => {
      cancelled = true
    }
  }, [cam.id, cam.embed, cam.source, thumb])

  return (
    <div className="webcam-player-wrap">
      {streamLoading && (
        <div className="health-status pending webcam-stream-loading">LOADING STREAM…</div>
      )}
      {!streamLoading && streamEmbed && (
        <iframe
          src={streamEmbed}
          title={cam.name || cam.id}
          className="webcam-embed"
          allow="autoplay; encrypted-media; fullscreen; picture-in-picture"
        />
      )}
      {!streamLoading && !streamEmbed && thumb && (
        <img src={thumb} alt={cam.name || cam.id} className="webcam-modal-img" />
      )}
      {!streamLoading && !streamEmbed && !thumb && (
        <div className="health-status pending">No preview available</div>
      )}
      {streamError && !streamEmbed && (
        <div className="health-status pending">{streamError}</div>
      )}
      {cam.detail_url && (
        <p className="webcam-modal-link">
          <a href={cam.detail_url} target="_blank" rel="noopener noreferrer">
            OPEN ON WINDY.COM ↗
          </a>
        </p>
      )}
      {cam.source === 'windy' && (
        <p className="webcam-powered-by">
          Webcam data via{' '}
          <a href="https://www.windy.com/webcams" target="_blank" rel="noopener noreferrer">
            Windy.com
          </a>
        </p>
      )}
    </div>
  )
}
