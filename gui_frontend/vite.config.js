import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { readFileSync } from 'node:fs'

const readJson = path => JSON.parse(readFileSync(new URL(path, import.meta.url), 'utf8'))
const { version } = readJson('../version.json')
const packageInfo = readJson('./package.json')
const lock = readJson('./package-lock.json')
if ([packageInfo.version, lock.version, lock.packages[''].version].some(value => value !== version)) {
  throw new Error('Versiones desalineadas. Ejecuta python tools/set_version.py <version> desde la raíz.')
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true
      }
    }
  }
})
