/**
 * One place for report-chart colours, taken from the designer's palette
 * (Design System > Primitive colors). No gold or orange: the designer's
 * "warning" is a clear yellow and is only used where a number means warning.
 *
 * Every pair works on both the dark and the light page background.
 */
export const DS_CHART = {
  primary: '#4479EE',    // primary 600
  accent: '#A499FF',     // accent
  tertiary: '#7766FF',   // tertiary 700
  secondary: '#8086E5',  // secondary 600
  sky: '#739BF2',        // primary 500
  lilac: '#ABAEED',      // secondary 700
  good: '#0E9900',       // success
  warn: '#FECB01',       // warning
  bad: '#FF3336',        // error
  badDeep: '#990003',    // error 400
  neutral: '#808080',    // neutral
} as const

/**
 * Categorical series (pies, multi-bar, "just different things"). Blue / violet / grey
 * only: green, red and yellow are never used here because they would read as
 * good / bad / warning. Use DS_CHART.good / bad / warn only where a number means that.
 */
export const CHART_SERIES = [
  DS_CHART.primary, DS_CHART.accent, DS_CHART.secondary, DS_CHART.sky,
  DS_CHART.tertiary, DS_CHART.lilac, DS_CHART.neutral, '#4933FF', '#565DDC', '#2C35D3',
] as const

/** Ageing buckets, healthy to critical. */
export const AGING_SERIES = [DS_CHART.good, DS_CHART.warn, '#FF6669', DS_CHART.bad, DS_CHART.badDeep] as const

/** Tooltip box for dark and light pages (kit surface/outline colours). */
export const chartTooltip = (light: boolean) => ({
  contentStyle: light
    ? { backgroundColor: '#FFFFFF', border: '1px solid #B9B4F2', borderRadius: 12, color: '#1C1B1F', fontSize: 12 }
    : { backgroundColor: '#13244B', border: '1px solid rgba(164,153,255,.35)', borderRadius: 12, color: '#F4F2FF', fontSize: 12 },
  labelStyle: { color: light ? '#55545C' : '#A9A6C4' },
  itemStyle: { color: light ? '#1C1B1F' : '#F4F2FF' },
})
