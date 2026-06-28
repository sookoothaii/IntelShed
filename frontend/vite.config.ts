import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import cesium from 'vite-plugin-cesium'

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

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, '')
  const apiTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8002'

  return {
  plugins: [react(), cesium({ devMinifyCesium: true }), faviconIcoFallback()],
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
