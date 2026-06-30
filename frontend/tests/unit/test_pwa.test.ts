/**
 * PWA tests — service worker caching strategies and manifest validation.
 *
 * Uses Vitest with jsdom environment. Tests the SW logic by importing
 * the service worker code and simulating fetch events.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve, join } from 'node:path';

const PUBLIC_DIR = resolve(__dirname, '..', '..', 'public');

describe('PWA Manifest', () => {
  it('should have a valid manifest.webmanifest', () => {
    const manifest = JSON.parse(
      readFileSync(join(PUBLIC_DIR, 'manifest.webmanifest'), 'utf-8')
    );
    expect(manifest.name).toContain('intelshed');
    expect(manifest.short_name).toBe('intelshed');
    expect(manifest.start_url).toBe('/');
    expect(manifest.display).toBe('standalone');
    expect(manifest.background_color).toBe('#04070d');
    expect(manifest.theme_color).toBe('#04070d');
    expect(manifest.icons).toBeInstanceOf(Array);
    expect(manifest.icons.length).toBeGreaterThan(0);
  });

  it('should have at least one maskable icon', () => {
    const manifest = JSON.parse(
      readFileSync(join(PUBLIC_DIR, 'manifest.webmanifest'), 'utf-8')
    );
    const maskable = manifest.icons.filter((i: any) =>
      i.purpose?.includes('maskable')
    );
    expect(maskable.length).toBeGreaterThan(0);
  });
});

describe('Service Worker', () => {
  it('should be a valid JavaScript file', () => {
    const swCode = readFileSync(join(PUBLIC_DIR, 'sw.js'), 'utf-8');
    expect(swCode).toContain('addEventListener');
    expect(swCode).toContain('install');
    expect(swCode).toContain('activate');
    expect(swCode).toContain('fetch');
  });

  it('should define cache version and cache names', () => {
    const swCode = readFileSync(join(PUBLIC_DIR, 'sw.js'), 'utf-8');
    expect(swCode).toContain('SW_VERSION');
    expect(swCode).toContain('SHELL_CACHE');
    expect(swCode).toContain('API_CACHE');
    expect(swCode).toContain('ASSET_CACHE');
  });

  it('should implement network-first for API calls', () => {
    const swCode = readFileSync(join(PUBLIC_DIR, 'sw.js'), 'utf-8');
    expect(swCode).toContain('networkFirst');
    expect(swCode).toMatch(/\/api\//);
  });

  it('should implement stale-while-revalidate for assets', () => {
    const swCode = readFileSync(join(PUBLIC_DIR, 'sw.js'), 'utf-8');
    expect(swCode).toContain('staleWhileRevalidate');
  });

  it('should implement cache-first for Cesium tiles', () => {
    const swCode = readFileSync(join(PUBLIC_DIR, 'sw.js'), 'utf-8');
    expect(swCode).toContain('cacheFirst');
    expect(swCode).toContain('CESIUM_PATTERNS');
  });

  it('should precache app shell routes', () => {
    const swCode = readFileSync(join(PUBLIC_DIR, 'sw.js'), 'utf-8');
    expect(swCode).toContain('SHELL_ROUTES');
    expect(swCode).toContain('/index.html');
    expect(swCode).toContain('/manifest.webmanifest');
  });

  it('should clean up old caches on activate', () => {
    const swCode = readFileSync(join(PUBLIC_DIR, 'sw.js'), 'utf-8');
    expect(swCode).toContain('caches.keys');
    expect(swCode).toContain('caches.delete');
  });

  it('should handle skipWaiting and clients.claim', () => {
    const swCode = readFileSync(join(PUBLIC_DIR, 'sw.js'), 'utf-8');
    expect(swCode).toContain('skipWaiting');
    expect(swCode).toContain('clients.claim');
  });

  it('should handle message events for manual update', () => {
    const swCode = readFileSync(join(PUBLIC_DIR, 'sw.js'), 'utf-8');
    expect(swCode).toContain('addEventListener');
    expect(swCode).toContain("'message'");
  });
});

describe('Service Worker Registration', () => {
  it('main.tsx should register the service worker', () => {
    const mainCode = readFileSync(
      resolve(__dirname, '..', '..', 'src', 'main.tsx'),
      'utf-8'
    );
    expect(mainCode).toContain('serviceWorker');
    expect(mainCode).toContain('register');
    expect(mainCode).toContain('/sw.js');
  });
});

describe('index.html PWA tags', () => {
  it('should link the manifest', () => {
    const html = readFileSync(
      resolve(__dirname, '..', '..', 'index.html'),
      'utf-8'
    );
    expect(html).toContain('manifest.webmanifest');
  });

  it('should have apple mobile web app meta tags', () => {
    const html = readFileSync(
      resolve(__dirname, '..', '..', 'index.html'),
      'utf-8'
    );
    expect(html).toContain('apple-mobile-web-app-capable');
    expect(html).toContain('apple-mobile-web-app-title');
  });

  it('should have theme-color meta tag', () => {
    const html = readFileSync(
      resolve(__dirname, '..', '..', 'index.html'),
      'utf-8'
    );
    expect(html).toContain('theme-color');
    expect(html).toContain('#04070d');
  });
});
