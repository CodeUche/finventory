/**
 * AudityLogo — theme-aware brand asset component.
 *
 * variant="horizontal"  →  full logo mark + wordmark (3:1 ratio SVG)
 *                           dark mode  → audity-logo-dark.svg  (white text, blue-gold mark)
 *                           light mode → audity-logo-light.svg (navy text, gold mark)
 *
 * variant="icon"        →  square icon mark only (1:1 ratio SVG)
 *                           dark mode  → audity-icon-dark.svg  (dark navy bg)
 *                           light mode → audity-icon-light.svg (light bg)
 *
 * Subscribes to the 'themechange' custom event so it updates instantly when
 * the user toggles the theme without requiring a page reload.
 */

import { useState, useEffect } from 'react'
import { getStoredTheme, type Theme } from '@/hooks/useTheme'

interface Props {
  variant?: 'horizontal' | 'icon'
  className?: string
  alt?: string
}

export default function AudityLogo({ variant = 'horizontal', className, alt = 'Audity' }: Props) {
  const [theme, setThemeState] = useState<Theme>(getStoredTheme)

  useEffect(() => {
    const handler = (e: Event) => setThemeState((e as CustomEvent<Theme>).detail)
    window.addEventListener('themechange', handler)
    return () => window.removeEventListener('themechange', handler)
  }, [])

  const src = variant === 'icon'
    ? (theme === 'dark' ? '/audity-icon-dark.svg' : '/audity-icon-light.svg')
    : (theme === 'dark' ? '/audity-logo-dark.svg' : '/audity-logo-light.svg')

  return <img src={src} alt={alt} className={className} draggable={false} />
}
