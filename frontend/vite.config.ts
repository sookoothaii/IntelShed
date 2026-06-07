import { defineConfig } from 'vite'
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

export default defineConfig({
  plugins: [react(), cesium(), faviconIcoFallback()],
  server: {
    port: 5176,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8002',
        changeOrigin: true,
        timeout: 600_000,
        proxyTimeout: 600_000,
      },
    },
  },
})
