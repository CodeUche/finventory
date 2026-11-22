/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string
  /** Public web address for links people copy and share from the desktop and Android apps. */
  readonly VITE_PUBLIC_WEB_ORIGIN?: string
  /** PostHog project API key. Leave unset to disable analytics. */
  /** Public web address for links people copy and share from the desktop/Android apps. */
  readonly VITE_PUBLIC_WEB_ORIGIN?: string
  /** PostHog project API key. Leave unset to disable analytics. */
  readonly VITE_POSTHOG_KEY?: string
  /** PostHog ingestion host. Defaults to https://us.i.posthog.com. */
  readonly VITE_POSTHOG_HOST?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
