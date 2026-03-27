/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import path from 'path'

export default defineConfig(({ mode }) => {
  // Tauri builds pass --mode desktop (production) or set TAURI_DEBUG (dev).
  // In both cases the PWA service worker must be disabled — it intercepts
  // every fetch in the WebView2 context and strips the Authorization header
  // on cross-origin requests, causing 401 on all authenticated API calls.
  const isTauri = mode === 'desktop' || mode === 'android' ||
    process.env.TAURI_DEBUG !== undefined || process.env.TAURI_ENV_DEBUG !== undefined

  return {
  plugins: [
    react(),
    // Only add PWA plugin for cloud/web builds — Tauri has no use for a SW
    !isTauri && VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.ico', 'apple-touch-icon.png', 'icons/*.png'],
      manifest: {
        name: 'Audity — Business Finance',
        short_name: 'Audity',
        description: 'All-in-one business finance, inventory & payroll platform for Nigerian SMEs',
        theme_color: '#f97316',
        background_color: '#0f172a',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
        ],
        categories: ['finance', 'business', 'productivity'],
        screenshots: [],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
        runtimeCaching: [
          {
            urlPattern: /^https?:\/\/.*\/api\/v1\//,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'api-cache',
              networkTimeoutSeconds: 10,
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
    }),
  ].filter(Boolean),

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

  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    css: false,
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
  }
})
