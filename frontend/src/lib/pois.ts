// Points of interest for cinematic camera fly-to presets.

export type POI = {
  name: string;
  lon: number;
  lat: number;
  height: number; // camera height in meters
  heading?: number;
  pitch?: number; // degrees
};

export const POIS: POI[] = [
  { name: 'Earth', lon: 0, lat: 20, height: 20000000, pitch: -90 },
  { name: 'New York', lon: -74.006, lat: 40.7128, height: 4000, pitch: -30 },
  { name: 'Grand Canyon', lon: -112.112, lat: 36.106, height: 6000, pitch: -25 },
  { name: 'Mount Everest', lon: 86.925, lat: 27.988, height: 9000, pitch: -20 },
  { name: 'Dubai', lon: 55.274, lat: 25.197, height: 2500, pitch: -35 },
  { name: 'Hong Kong', lon: 114.158, lat: 22.283, height: 3500, pitch: -30 },
  { name: 'San Francisco', lon: -122.4783, lat: 37.8199, height: 3000, pitch: -30 },
  { name: 'Tokyo', lon: 139.6917, lat: 35.6895, height: 4000, pitch: -35 },
  { name: 'Paris', lon: 2.2945, lat: 48.8584, height: 2000, pitch: -30 },
  { name: 'Area 51', lon: -115.812, lat: 37.235, height: 12000, pitch: -35 },
  { name: 'Berlin', lon: 13.405, lat: 52.52, height: 3000, pitch: -30 },
  { name: 'Sydney', lon: 151.2153, lat: -33.8568, height: 3000, pitch: -30 },
];
