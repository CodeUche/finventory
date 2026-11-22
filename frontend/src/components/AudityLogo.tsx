/**
 * AudityLogo — the designer's blue diamond + wordmark (same artwork as the
 * top bar and the sign-in screens; see BrandLogo). The old gold-mark SVG files
 * are no longer used here. Follows the theme and updates instantly on toggle.
 *
 * variant="horizontal" -> diamond + AUDITY wordmark
 * variant="icon"       -> diamond only
 */

import { useState, useEffect } from 'react'
import { getStoredTheme, type Theme } from '@/hooks/useTheme'
import BrandLogo from '@/components/BrandLogo'
import '@/styles/app-shell.css'

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

  // The wordmark colour comes from --sh-head, which only exists inside the app shell,
  // so set it here for the sign-in style pages that have no shell.
  const style = { ['--sh-head' as string]: theme === 'dark' ? '#FFFFFF' : '#111111', ['--sh-ink' as string]: theme === 'dark' ? '#F4F2FF' : '#1C1B1F' } as React.CSSProperties
  return (
    <span className={className} style={{ ...style, display: 'inline-flex', alignItems: 'center' }} aria-label={alt}>
      <BrandLogo iconOnly={variant === 'icon'} />
    </span>
  )
}
