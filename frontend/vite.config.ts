import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Docker Desktop's bind-mount file sharing (macOS) doesn't reliably
    // forward inotify events into the container under rapid successive
    // writes -- Vite's watcher then silently keeps serving a stale
    // transform of an already-changed file until the container restarts.
    // Polling sidesteps that by not depending on those events at all.
    watch: {
      usePolling: true,
      interval: 300,
    },
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://backend:8000',
        changeOrigin: true,
      },
    },
  },
})
