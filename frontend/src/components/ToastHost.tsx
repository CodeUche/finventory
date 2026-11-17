/**
 * The one place toasts are drawn.
 *
 * Normally they sit at the bottom, centred in the page area, clear of the support bubble, the
 * register's basket and any open slide-over (see lib/drawerToastOffset.ts, which publishes the
 * free strip as CSS variables). While a pop-up is open they move to the top of the screen,
 * above the scrim, where pop-ups keep a free band, so a toast never covers a pop-up's header
 * or its buttons.
 */
import { useEffect, useState } from 'react'
import { Toaster } from 'react-hot-toast'
import { isPopupOpen, subscribePopupOpen } from '@/lib/drawerToastOffset'

export default function ToastHost() {
  const [popup, setPopup] = useState(isPopupOpen())
  useEffect(() => subscribePopupOpen(setPopup), [])

  return (
    <Toaster
      position={popup ? 'top-center' : 'bottom-center'}
      gutter={8}
      // The strip variables come from lib/drawerToastOffset.ts. 9999 keeps pop-ups from covering messages.
      containerStyle={
        popup
          ? { top: 12, left: 16, right: 16, bottom: 'auto', zIndex: 9999 }
          : {
              top: 'auto',
              bottom: 'var(--toast-bottom, 20px)',
              left: 'var(--toast-left, 16px)',
              right: 'var(--toast-right, 16px)',
              zIndex: 9999,
            }
      }
      toastOptions={{
        // Everything goes away by itself; errors stay a little longer so they can be read.
        duration: 4500,
        error: { duration: 6500, iconTheme: { primary: '#FF3336', secondary: '#04122F' } },
        success: { duration: 3500, iconTheme: { primary: '#13CC00', secondary: '#04122F' } },
        style: {
          background: '#13244B',
          color: '#f8fafc',
          border: '1px solid #1E2F56',
          borderRadius: '12px',
          fontSize: '14px',
          maxWidth: 'min(420px, calc(100vw - 32px))',
        },
      }}
    />
  )
}
