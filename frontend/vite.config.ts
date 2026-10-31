import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  // Only matters for GitHub Pages' default project-site URL
  // (https://<user>.github.io/<repo>/), which serves from a subpath. Set
  // via VITE_BASE_PATH at build time; leave unset for the LAN quick-start
  // mode (served from "/" by the backend) or a custom Pages domain. See
  // DEPLOYMENT.md.
  base: process.env.VITE_BASE_PATH || '/',
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
      },
    },
  },
})
