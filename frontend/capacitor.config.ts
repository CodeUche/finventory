import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'com.finventory.app',
  appName: 'Finventory',
  webDir: 'dist',
  server: {
    // Use https scheme so cookies/localStorage behave like a real origin
    androidScheme: 'https',
  },
  android: {
    // Allow cleartext (http) traffic to backend during local dev
    // Remove this in production when backend is on https
    allowMixedContent: true,
  },
}

export default config
