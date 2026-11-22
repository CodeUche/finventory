/**
 * Web fonts for the invoice / quote font picker and its live preview ONLY.
 * Nothing else in the app uses them (the app itself is self-hosted Roboto), so
 * they are fetched the first time the picker is opened, not on every page.
 * Needs a network; offline or where the desktop policy blocks it, the preview
 * simply falls back to a system font.
 */
const LINK_ID = 'document-fonts'
const HREF =
  'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Open+Sans:ital,wght@0,400;0,700;1,400&family=Lato:ital,wght@0,400;0,700;1,400&family=Montserrat:ital,wght@0,400;0,700;1,400&family=Poppins:ital,wght@0,400;0,700;1,400&family=Raleway:ital,wght@0,400;0,700;1,400&family=Nunito:ital,wght@0,400;0,700;1,400&family=Ubuntu:ital,wght@0,400;0,700;1,400&family=Oswald:wght@400;700&family=Playfair+Display:ital,wght@0,400;0,700;1,400&family=Merriweather:ital,wght@0,400;0,700;1,400&family=Lora:ital,wght@0,400;0,700;1,400&family=Libre+Baskerville:ital,wght@0,400;0,700;1,400&family=EB+Garamond:ital,wght@0,400;0,700;1,400&family=Crimson+Text:ital,wght@0,400;0,600;1,400&family=Cinzel:wght@400;700&family=Cormorant+Garamond:ital,wght@0,400;0,700;1,400&family=Spectral:ital,wght@0,400;0,700;1,400&family=Bebas+Neue&family=Source+Sans+3:ital,wght@0,400;0,700;1,400&display=swap'

export function ensureDocumentFonts(): void {
  if (typeof document === 'undefined' || document.getElementById(LINK_ID)) return
  const link = document.createElement('link')
  link.id = LINK_ID
  link.rel = 'stylesheet'
  link.href = HREF
  document.head.appendChild(link)
}
