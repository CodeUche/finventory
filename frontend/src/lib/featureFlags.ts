/**
 * Feature flags — controls which features are visible in the UI.
 * The underlying code, routes, and backend endpoints are fully implemented.
 * Set a flag to `true` to expose the feature in the next release.
 */
export const FEATURES = {
  /**
   * Partner / Accountant Channel
   * - Partner Dashboard sidebar link
   * - "Manage Books" client management
   * - Partner Channel billing section
   * - Client View amber banner
   * - "Accountant · FirmName" badge in Settings Team tab
   *
   * Re-enable: set to `true` and rebuild.
   */
  PARTNER_CHANNEL: false,
} as const
