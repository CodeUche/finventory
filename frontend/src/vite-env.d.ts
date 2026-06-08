/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string
  /** PostHog project API key. Leave unset to disable analytics. */
  readonly VITE_POSTHOG_KEY?: string
  /** PostHog ingestion host. Defaults to https://us.i.posthog.com. */
  readonly VITE_POSTHOG_HOST?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
