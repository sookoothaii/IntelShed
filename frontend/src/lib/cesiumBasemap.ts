import {
  createWorldImageryAsync,
  IonWorldImageryStyle,
  RequestScheduler,
  UrlTemplateImageryProvider,
  type ImageryProvider,
} from 'cesium'
import {
  ESRI_HILLSHADE_TILES,
  ESRI_REFERENCE_LABELS,
  ESRI_SATELLITE_TILES,
  ESRI_STREET_TILES,
  hasCesiumIonToken,
  type BasemapMode,
} from './mapView'

/** ESRI UrlTemplate fallback — used only when Ion token is missing. */
function esriImagery(url: string, credit: string) {
  return new UrlTemplateImageryProvider({
    url,
    credit,
    maximumLevel: 19,
  })
}

/** Primary basemap layer for the given mode. */
export async function createBasemapProvider(basemap: BasemapMode): Promise<ImageryProvider> {
  if (hasCesiumIonToken()) {
    switch (basemap) {
      case 'streets':
        return createWorldImageryAsync({ style: IonWorldImageryStyle.ROAD })
      case 'satellite':
        return createWorldImageryAsync({ style: IonWorldImageryStyle.AERIAL })
      case 'hybrid':
        return createWorldImageryAsync({ style: IonWorldImageryStyle.AERIAL_WITH_LABELS })
      case 'terrain':
        return esriImagery(ESRI_HILLSHADE_TILES, 'Esri World Hillshade')
    }
  }
  switch (basemap) {
    case 'streets':
      return esriImagery(ESRI_STREET_TILES, 'Esri, OpenStreetMap contributors')
    case 'satellite':
    case 'hybrid':
      return esriImagery(ESRI_SATELLITE_TILES, 'Esri, Maxar, Earthstar Geographics')
    case 'terrain':
      return esriImagery(ESRI_HILLSHADE_TILES, 'Esri World Hillshade')
  }
}

/** Streets overlay for terrain-shaded mode, or hybrid label overlay without Ion. */
export async function createBasemapOverlayProvider(
  basemap: BasemapMode,
): Promise<ImageryProvider | null> {
  if (basemap === 'terrain') {
    if (hasCesiumIonToken()) {
      return createWorldImageryAsync({ style: IonWorldImageryStyle.ROAD })
    }
    return esriImagery(ESRI_STREET_TILES, 'Esri, OpenStreetMap contributors')
  }
  if (basemap === 'hybrid' && !hasCesiumIonToken()) {
    return esriImagery(ESRI_REFERENCE_LABELS, 'Esri, OpenStreetMap contributors')
  }
  return null
}

/** Raise per-server concurrency for Ion + ArcGIS tile fetches. */
export function tuneImageryRequestScheduler(): void {
  RequestScheduler.maximumRequestsPerServer = Math.max(RequestScheduler.maximumRequestsPerServer, 24)
}
