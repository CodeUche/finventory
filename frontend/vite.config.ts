import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// `tauri dev` sets TAURI_DEBUG; detect so we can tweak build options
const isTauri = process.env.TAURI_DEBUG !== undefined || process.env.TAURI_ENV_DEBUG !== undefined

export default defineConfig({
  plugins: [react()],

  // Expose both VITE_ and TAURI_ prefixed vars to the app
  envPrefix: ['VITE_', 'TAURI_'],

  // Preserve terminal output — Tauri's process manager needs it
  clearScreen: false,

  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },

  build: {
    // Tauri's embedded WebView needs ES2021; safe for modern Android too
    target: ['es2021', 'chrome100', 'safari13'],
    minify: isTauri ? false : 'esbuild',
    sourcemap: isTauri,
  },

  server: {
    port: 3000,
    strictPort: true, // Tauri expects exactly this port
    proxy: {
      // Active only during `vite` dev server — not in packaged builds
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
