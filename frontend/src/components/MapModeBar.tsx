import type { BasemapMode, MapViewMode } from '../lib/mapView';
import { BASEMAP_LABELS, hasCesiumIonToken } from '../lib/mapView';

type Props = {
  mode: MapViewMode;
  onChange: (next: MapViewMode) => void;
  /** When user enables 3D while on flat map tab, jump to globe */
  onRequestGlobe?: () => void;
  compact?: boolean;
};

const BASEMAPS: BasemapMode[] = ['streets', 'satellite', 'hybrid', 'terrain'];

export default function MapModeBar({ mode, onChange, onRequestGlobe, compact }: Props) {
  const ionOk = hasCesiumIonToken();

  const setBasemap = (basemap: BasemapMode) => onChange({ ...mode, basemap });

  const setRender3d = (render3d: boolean) => {
    if (render3d) onRequestGlobe?.();
    onChange({ ...mode, render3d });
  };

  return (
    <div
      className={`map-mode-bar${compact ? ' compact' : ''}`}
      role="toolbar"
      aria-label="Map mode"
    >
      <div className="map-mode-group">
        {BASEMAPS.map((b) => (
          <button
            key={b}
            type="button"
            className={mode.basemap === b ? 'active' : ''}
            onClick={() => setBasemap(b)}
            title={BASEMAP_LABELS[b]}
          >
            {BASEMAP_LABELS[b]}
          </button>
        ))}
      </div>

      <div className="map-mode-divider" />

      <div className="map-mode-group">
        <button
          type="button"
          className={!mode.render3d ? 'active' : ''}
          onClick={() => setRender3d(false)}
        >
          2D
        </button>
        <button
          type="button"
          className={mode.render3d ? 'active' : ''}
          onClick={() => setRender3d(true)}
        >
          3D
        </button>
      </div>

      <div className="map-mode-divider" />

      <label className={`map-mode-toggle${mode.buildings ? ' on' : ''}`} title="3D buildings (OSM)">
        <input
          type="checkbox"
          checked={mode.buildings}
          onChange={(e) => onChange({ ...mode, buildings: e.target.checked })}
        />
        BUILDINGS
      </label>

      <label
        className={`map-mode-toggle${mode.labels ? ' on' : ''}`}
        title="Place & city name labels (Esri World Boundaries & Places)"
      >
        <input
          type="checkbox"
          checked={mode.labels}
          onChange={(e) => onChange({ ...mode, labels: e.target.checked })}
        />
        LABELS
      </label>

      {ionOk && (
        <label
          className={`map-mode-toggle photoreal${mode.photorealistic ? ' on' : ''}`}
          title="Google Photorealistic 3D via Cesium Ion (GPU-intensiv)"
        >
          <input
            type="checkbox"
            checked={mode.photorealistic}
            onChange={(e) => {
              if (e.target.checked) onRequestGlobe?.();
              onChange({
                ...mode,
                photorealistic: e.target.checked,
                render3d: true,
                buildings: false,
              });
            }}
          />
          PHOTO 3D
        </label>
      )}
    </div>
  );
}
