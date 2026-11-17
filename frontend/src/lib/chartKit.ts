import { useEffect, useState } from 'react'
import { getStoredTheme } from '@/hooks/useTheme'
import { DS_CHART, chartTooltip } from '@/lib/chartTheme'

/**
 * Everything a chart needs besides its series colours, in one place:
 * axis text, grid lines, hover highlight, legend text and the tooltip box.
 * Series colours still come from lib/chartTheme.ts and are the SAME in dark and light.
 */
export interface ChartKit {
  light: boolean
  /** The one brand colour for a single-series chart (same in both themes). */
  accent: string
  tooltipStyle: Record<string, string | number>
  tooltipLabelStyle: { color: string }
  tooltipItemStyle: { color: string }
  axisTickStyle: { fill: string; fontSize: number }
  grid: string
  /** Hover highlight behind bars: a soft kit tint, not the default flat grey block. */
  cursor: { fill: string }
  legendColor: string
  /** Label text drawn on the chart itself (axis titles, reference line labels). */
  labelColor: string
}

export function chartKitFor(light: boolean): ChartKit {
  const tt = chartTooltip(light)
  return {
    light,
    accent: DS_CHART.primary,
    tooltipStyle: tt.contentStyle,
    tooltipLabelStyle: tt.labelStyle,
    tooltipItemStyle: tt.itemStyle,
    axisTickStyle: { fill: light ? '#55545C' : '#A9A6C4', fontSize: 11 },
    grid: light ? 'rgba(85,84,92,.22)' : 'rgba(169,166,196,.22)',
    cursor: { fill: light ? 'rgba(68,121,238,.10)' : 'rgba(164,153,255,.14)' },
    legendColor: light ? '#1C1B1F' : '#F4F2FF',
    labelColor: light ? '#55545C' : '#A9A6C4',
  }
}

export function useChartKit(): ChartKit {
  const [light, setLight] = useState(() => getStoredTheme() === 'light')
  useEffect(() => {
    const h = (e: Event) => setLight((e as CustomEvent).detail === 'light')
    window.addEventListener('themechange', h)
    return () => window.removeEventListener('themechange', h)
  }, [])
  return chartKitFor(light)
}
