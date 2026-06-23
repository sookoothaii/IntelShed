import {
  UrlTemplateImageryProvider,
  createWorldImageryAsync,
  IonWorldImageryStyle,
} from 'cesium'
import { ESRI_STREET_TILES, hasCesiumIonToken } from './mapView'

/**
 * Streets basemap for the Cesium globe.
 *
 * ESRI World_Street_Map via UrlTemplate can leave level-0 tiles stuck in
 * ImageryState.TRANSITIONING (request never issued), so globe.tilesLoaded stays
 * false and Cesium renders every frame. Ion Bing ROAD uses Cesium's imagery
 * pipeline and clears tilesLoaded; ESRI UrlTemplate remains fallback without Ion.
 */
export async function createStreetsImageryProvider() {
  if (hasCesiumIonToken()) {
    return createWorldImageryAsync({ style: IonWorldImageryStyle.ROAD })
  }
  return new UrlTemplateImageryProvider({
    url: ESRI_STREET_TILES,
    credit: 'Esri, OpenStreetMap contributors',
    maximumLevel: 19,
  })
}
