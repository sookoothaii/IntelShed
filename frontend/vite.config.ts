import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import cesium from 'vite-plugin-cesium'
import { execSync } from 'child_process'
import { readFileSync, writeFileSync } from 'fs'
import { resolve } from 'path'

/** Browsers still request /favicon.ico — serve SVG instead of 404. */
function faviconIcoFallback() {
  return {
    name: 'favicon-ico-fallback',
    configureServer(server: { middlewares: { use: (fn: (req: any, res: any, next: () => void) => void) => void } }) {
      server.middlewares.use((req, _res, next) => {
        if (req.url === '/favicon.ico') req.url = '/favicon.svg'
        next()
      })
    },
  }
}

/**
 * E-09 CSP Single Source of Truth — syncs CSP from backend/csp_policy.py into
 * frontend/index.html (meta tag) and Caddyfile (header directive) at build start.
 * One source (csp_policy.py) → three outputs, no manual sync needed.
 */
function cspSync() {
  const backendDir = resolve(__dirname, '..', 'backend')
  const indexPath = resolve(__dirname, 'index.html')
  const caddyPath = resolve(__dirname, '..', 'Caddyfile')

  function getCspFromPython(format: string): string {
    try {
      return execSync(`python -c "from csp_policy import CSPPolicy; print(CSPPolicy.to_${format}())"`, {
        cwd: backendDir,
        encoding: 'utf-8',
        timeout: 10_000,
      }).trim()
    } catch {
      console.warn('[csp-sync] Could not run csp_policy.py — skipping sync')
      return ''
    }
  }

  function syncIndexHtml(cspValue: string) {
    if (!cspValue) return
    let html = readFileSync(indexPath, 'utf-8')
    const metaRegex = /(<meta\s+http-equiv="Content-Security-Policy"\s+content=")([^"]*)(")/s
    if (metaRegex.test(html)) {
      html = html.replace(metaRegex, `$1${cspValue}$3`)
      writeFileSync(indexPath, html, 'utf-8')
    }
  }

  function syncCaddyfile(caddyLine: string) {
    if (!caddyLine) return
    let caddy = readFileSync(caddyPath, 'utf-8')
    const cspRegex = /Content-Security-Policy "[^"]*"/
    if (cspRegex.test(caddy)) {
      caddy = caddy.replace(cspRegex, caddyLine)
      writeFileSync(caddyPath, caddy, 'utf-8')
    }
  }

  return {
    name: 'csp-sync',
    buildStart() {
      const cspValue = getCspFromPython('meta_tag')
      if (cspValue) syncIndexHtml(cspValue)
      const caddyLine = getCspFromPython('caddyfile_line')
      if (caddyLine) syncCaddyfile(caddyLine)
    },
  }
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, '')
  const apiTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8002'

  return {
  plugins: [react(), cesium({ devMinifyCesium: true }), faviconIcoFallback(), cspSync()],
  server: {
    host: '127.0.0.1',
    port: 5176,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        secure: false,
        timeout: 600_000,
        proxyTimeout: 600_000,
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 6_000,
    rollupOptions: {
      output: {
        manualChunks: {
          'maplibre-vendor': ['maplibre-gl'],
          'react-vendor': ['react', 'react-dom', '@tanstack/react-query'],
          'cytoscape-vendor': ['cytoscape'],
          'satellite-vendor': ['satellite.js'],
        },
      },
    },
  },
  }
})
