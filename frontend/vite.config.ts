import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dev server forwards /api to the FastAPI backend, so the browser sees
// one origin and needs no CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': process.env.API_PROXY_TARGET ?? 'http://localhost:8000',
    },
  },
})
