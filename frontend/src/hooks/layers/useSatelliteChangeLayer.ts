import { useEffect, useRef, useState } from 'react';
import { CustomDataSource, Color, PolygonGraphics, Cartesian3, type Viewer } from 'cesium';
import { attachDataSource, detachDataSource, requestSceneRender } from './layerUtils';
import { hudStore, type SatelliteChangeData } from '../../stores/hudStore';

/**
 * Globe layer for Sentinel-2 change detection anomalies.
 * Reads GeoJSON results from the HUDStore (written by SatellitePanel).
 * Renders polygons: green for NDVI increase, red for decrease.
 */
export function useSatelliteChangeLayer({
  viewer,
  active,
}: {
  viewer: Viewer | null;
  active: boolean;
}) {
  const srcRef = useRef<CustomDataSource | null>(null);
  const [changeData, setChangeData] = useState<SatelliteChangeData | null>(null);

  // Subscribe to HUD store for satellite change data
  useEffect(() => {
    const unsub = hudStore.subscribe((state) => {
      setChangeData(state.satelliteChangeData ?? null);
    });
    // Sync initial state
    setChangeData(hudStore.getState().satelliteChangeData ?? null);
    return unsub;
  }, []);

  // Create / destroy data source
  useEffect(() => {
    if (!viewer) return;
    const src = new CustomDataSource('satellite-change');
    attachDataSource(viewer, src);
    srcRef.current = src;
    return () => {
      detachDataSource(viewer, src);
      srcRef.current = null;
    };
  }, [viewer]);

  // Toggle visibility
  useEffect(() => {
    if (srcRef.current) srcRef.current.show = active;
    requestSceneRender(viewer);
  }, [viewer, active]);

  // Render polygons when data changes
  useEffect(() => {
    if (!viewer || !srcRef.current) return;
    const src = srcRef.current;
    src.entities.suspendEvents();
    src.entities.removeAll();

    if (!active || !changeData || !changeData.features) {
      src.entities.resumeEvents();
      requestSceneRender(viewer);
      return;
    }

    for (let i = 0; i < changeData.features.length; i++) {
      const f = changeData.features[i];
      if (!f.geometry || f.geometry.type !== 'Polygon') continue;
      const coords = f.geometry.coordinates[0];
      if (!coords || coords.length < 3) continue;

      const props = f.properties;
      const isIncrease = props.class === 'increase';
      const fillColor = isIncrease
        ? Color.fromCssColorString('#00e5a0').withAlpha(0.35)
        : Color.fromCssColorString('#ff4d5e').withAlpha(0.35);
      const outlineColor = isIncrease
        ? Color.fromCssColorString('#00e5a0')
        : Color.fromCssColorString('#ff4d5e');

      const hierarchy = coords.map(([lon, lat]) => Cartesian3.fromDegrees(lon, lat, 0));

      src.entities.add({
        id: `sat-change-${i}`,
        polygon: {
          hierarchy: hierarchy,
          material: fillColor,
          outline: true,
          outlineColor: outlineColor,
          outlineWidth: 2,
        } as unknown as PolygonGraphics.ConstructorOptions,
        properties: {
          kind: 'satellite_change',
          class: props.class,
          mean_delta: props.mean_delta,
          max_delta: props.max_delta,
          min_delta: props.min_delta,
          pixel_count: props.pixel_count,
          confidence: props.confidence,
        },
      });
    }

    src.entities.resumeEvents();
    requestSceneRender(viewer);
  }, [viewer, active, changeData]);
}
