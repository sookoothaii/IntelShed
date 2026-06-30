/// <reference lib="webworker" />
/**
 * intelshed Service Worker — offline app-shell caching.
 *
 * Strategy:
 *  - Precache app shell (HTML, CSS, JS bundles) on install
 *  - Network-first for API calls (/api/*) — fall back to cache when offline
 *  - Stale-while-revalidate for static assets (JS, CSS, fonts, images)
 *  - Cache-first for Cesium terrain/tiles (large, immutable)
 */

const SW_VERSION = 'intelshed-sw-v1';
const SHELL_CACHE = `${SW_VERSION}-shell`;
const API_CACHE = `${SW_VERSION}-api`;
const ASSET_CACHE = `${SW_VERSION}-assets`;

// App-shell routes (HTML + core bundles)
const SHELL_ROUTES = ['/', '/index.html', '/favicon.svg', '/manifest.webmanifest'];

// Static asset extensions for stale-while-revalidate
const ASSET_EXTENSIONS = ['.js', '.css', '.woff', '.woff2', '.ttf', '.png', '.jpg', '.svg', '.webp', '.ico'];

// Cesium / terrain tile patterns (cache-first, large immutable resources)
const CESIUM_PATTERNS = [/\.terrain$/, /\.pmtiles$/, /\/terrain\//, /\/tiles\//, /cesium\.com/, /ion\.cesium\.com/];

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL_CACHE);
      // Cache the app shell — ignore failures for individual resources
      await Promise.allSettled(
        SHELL_ROUTES.map((url) => cache.add(new Request(url, { cache: 'reload' })))
      );
      await self.skipWaiting();
    })()
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      // Clean up old caches
      const keys = await caches.keys();
      await Promise.all(
        keys
          .filter((key) => !key.startsWith(SW_VERSION))
          .map((key) => caches.delete(key))
      );
      await self.clients.claim();
    })()
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;

  // Only handle GET requests
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // Skip cross-origin requests (except Cesium CDN)
  if (url.origin !== self.location.origin && !CESIUM_PATTERNS.some((p) => p.test(url.href))) {
    return;
  }

  // API calls: network-first, fall back to cache
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirst(request, API_CACHE, 5000));
    return;
  }

  // Cesium terrain/tiles: cache-first (large, immutable)
  if (CESIUM_PATTERNS.some((p) => p.test(url.href))) {
    event.respondWith(cacheFirst(request, ASSET_CACHE));
    return;
  }

  // Navigation requests: serve app shell from cache when offline
  if (request.mode === 'navigate') {
    event.respondWith(networkFirstNavigation(request, SHELL_CACHE));
    return;
  }

  // Static assets: stale-while-revalidate
  const ext = url.pathname.substring(url.pathname.lastIndexOf('.'));
  if (ASSET_EXTENSIONS.includes(ext)) {
    event.respondWith(staleWhileRevalidate(request, ASSET_CACHE));
    return;
  }

  // Default: try network, fall back to cache
  event.respondWith(networkFirst(request, ASSET_CACHE, 8000));
});

// --- Cache strategies ---

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch {
    return new Response('Offline', { status: 503, statusText: 'Offline' });
  }
}

async function networkFirst(request, cacheName, timeoutMs) {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetchWithTimeout(request, timeoutMs);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch {
    const cached = await cache.match(request);
    if (cached) return cached;
    return new Response('Offline', { status: 503, statusText: 'Offline' });
  }
}

async function networkFirstNavigation(request, cacheName) {
  const cache = await caches.open(cacheName);
  try {
    const response = await fetch(request);
    if (response.ok) cache.put(request, response.clone());
    return response;
  } catch {
    // Serve cached app shell for offline navigation
    const cached = await cache.match(request);
    if (cached) return cached;
    const shell = await cache.match('/index.html');
    if (shell) return shell;
    return new Response('Offline — app shell not cached', {
      status: 503,
      headers: { 'Content-Type': 'text/html' },
    });
  }
}

async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  const fetchPromise = fetch(request)
    .then((response) => {
      if (response.ok) cache.put(request, response.clone());
      return response;
    })
    .catch(() => cached || new Response('Offline', { status: 503 }));
  return cached || fetchPromise;
}

function fetchWithTimeout(request, timeoutMs) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timeout')), timeoutMs);
    fetch(request)
      .then((response) => {
        clearTimeout(timer);
        resolve(response);
      })
      .catch((err) => {
        clearTimeout(timer);
        reject(err);
      });
  });
}

// Handle messages from the page (e.g., manual update trigger)
self.addEventListener('message', (event) => {
  if (event.data === 'skipWaiting') {
    self.skipWaiting();
  }
  if (event.data === 'getVersion') {
    event.source?.postMessage({ version: SW_VERSION });
  }
});
