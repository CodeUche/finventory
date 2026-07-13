/**
 * AppBackdrop — the same "Compass" motif used on the auth pages (see AuthShell),
 * rendered behind the whole logged-in app so the shell has visual character
 * instead of a flat fill. Purely decorative: fixed, aria-hidden and
 * pointer-events:none so it never intercepts clicks or scrolls. Styling +
 * theme-aware colours live in index.css (.app-backdrop*).
 */
export default function AppBackdrop() {
  return (
    <div className="app-backdrop" aria-hidden="true">
      <svg
        className="app-backdrop-compass"
        viewBox="0 0 1440 900"
        preserveAspectRatio="xMidYMid slice"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <g transform="translate(1180 430)" opacity="0.5">
          <g className="ab-line" strokeWidth="1">
            <path d="M0 -81 L70 0 L0 81 L-70 0 Z" />
            <path d="M0 -162 L140 0 L0 162 L-140 0 Z" />
            <path d="M0 -244 L210 0 L0 244 L-210 0 Z" />
            <path d="M0 -325 L280 0 L0 325 L-280 0 Z" />
            <path d="M0 -406 L350 0 L0 406 L-350 0 Z" opacity="0.6" />
          </g>
          <g className="ab-line" strokeWidth="1" strokeDasharray="2 7" opacity="0.7">
            <line x1="0" y1="-440" x2="0" y2="440" />
            <line x1="-400" y1="0" x2="400" y2="0" />
          </g>
          <g className="ab-line" strokeWidth="1.4">
            <line x1="0" y1="-406" x2="0" y2="-386" />
            <line x1="0" y1="406" x2="0" y2="386" />
            <line x1="-350" y1="0" x2="-330" y2="0" />
            <line x1="350" y1="0" x2="330" y2="0" />
          </g>
          <path d="M0 -325 L18 -300 L-18 -300 Z" className="ab-gold-f" opacity="0.8" />
          <circle r="22" className="ab-gold" strokeWidth="1.2" opacity="0.7" />
          <circle r="5" className="ab-gold-f" />
        </g>
      </svg>
    </div>
  )
}
