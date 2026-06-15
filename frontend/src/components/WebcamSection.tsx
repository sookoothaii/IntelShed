import { useState } from 'react';
import type { FocusTarget } from '../lib/focus';

export default function WebcamSection({
  webcams,
  webcamCategory,
  setWebcamCategory,
  onLoad,
  loading,
  onFocus,
}: {
  webcams: { count: number; categories: string[]; webcams: any[]; cached_at: string } | null
  webcamCategory: string
  setWebcamCategory: (c: string) => void
  onLoad: () => void
  loading: boolean | undefined
  onFocus: (f: Omit<FocusTarget, 'ts'>) => void
}) {
  const [activeCam, setActiveCam] = useState<any>(null)
  const cats = ['all', ...(webcams?.categories || [])]

  return (
    <div className="webcam-section">
      <div className="webcam-controls">
        <button onClick={onLoad} disabled={loading} className="refresh-btn">
          {loading ? 'LOADING...' : 'LOAD WEBCAMS'}
        </button>
        {webcams && (
          <select value={webcamCategory} onChange={(e) => setWebcamCategory(e.target.value)}>
            {cats.map((c) => (
              <option key={c} value={c}>
                {c.toUpperCase()}
              </option>
            ))}
          </select>
        )}
      </div>

      {webcams && (
        <div className="webcam-grid">
          {webcams.webcams.map((cam: any) => (
            <div key={cam.id} className="webcam-card" onClick={() => setActiveCam(cam)}>
              <div className="webcam-thumb-container">
                <img src={cam.image?.current?.preview} alt={cam.title} loading="lazy" />
              </div>
              <div className="webcam-label">{cam.title}</div>
            </div>
          ))}
        </div>
      )}

      {activeCam && (
        <div className="webcam-modal" onClick={() => setActiveCam(null)}>
          <div className="webcam-modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>{activeCam.title}</h3>
            {activeCam.location && (
              <p>
                {activeCam.location.city}, {activeCam.location.country}
                <button
                  className="locate-mini"
                  onClick={() => {
                    setActiveCam(null)
                    onFocus({
                      kind: 'webcam',
                      lat: activeCam.location.latitude,
                      lon: activeCam.location.longitude,
                      title: activeCam.title,
                      height: 5000,
                      lines: []
                    })
                  }}
                  style={{ marginLeft: 10 }}
                >
                  ◎ LOCATE
                </button>
              </p>
            )}
            <img src={activeCam.image?.current?.preview} alt={activeCam.title} />
            <button onClick={() => setActiveCam(null)} className="close-btn">CLOSE</button>
          </div>
        </div>
      )}
    </div>
  )
}
