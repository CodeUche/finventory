/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Brand = the designer's primary blue, with the accent lavender on dark.
        // (Design System > Primitive colors.) The numbered shades 300-600 read CSS
        // vars (see index.css) so every brand utility, including /opacity
        // variants, flips per theme: dark uses the light accent tones for
        // readability, light uses the primary / tertiary blues.
        brand: {
          50:  '#F6F8FE',
          100: '#ECF2FD',
          200: '#D0DEFB',
          300: 'rgb(var(--brand-300) / <alpha-value>)',
          400: 'rgb(var(--brand-400) / <alpha-value>)',
          500: 'rgb(var(--brand-500) / <alpha-value>)',
          600: 'rgb(var(--brand-600) / <alpha-value>)',
          700: '#0D358C',
          800: '#09235D',
          900: '#04122F',
          950: '#030B1C',
        },
        // Surfaces = Audity navy (deep midnight in dark mode). Was slate.
        surface: {
          50:  '#F7F8FB',
          100: '#EEF1F7',
          200: '#DBE1EC',
          300: '#B9C3D6',
          400: '#8C9ABA',
          500: '#5E6E92',
          600: '#314272',
          700: '#1E2F56',
          800: '#13244B',
          900: '#0B1730',
          950: '#060C1C',
        },
        // No gold in the kit. Any leftover `gold-*` utility renders the designer's accent lavender.
        gold: {
          300: '#D2CCFF', 400: '#A499FF', 500: '#7766FF', 600: '#4933FF', 700: '#1600CC',
        },
        // The kit has no orange. Caution tones that used orange now use the kit's warning yellow.
        orange: {
          50: '#FFFDF5', 100: '#FFF9E1', 200: '#FFF5CC', 300: '#FFEA99', 400: '#FED634',
          500: '#FECB01', 600: '#CBA301', 700: '#987A01', 800: '#665100', 900: '#332900', 950: '#332900',
        },
        // The designer's warning colour is a clear yellow (#FECB01). amber / yellow
        // utilities (kept for real warnings) use that ramp, not Tailwind's orange-ish amber.
        amber: {
          50: '#FFFDF5', 100: '#FFF9E1', 200: '#FFF5CC', 300: '#FFEA99', 400: '#FED634',
          500: '#FECB01', 600: '#CBA301', 700: '#987A01', 800: '#665100', 900: '#332900', 950: '#332900',
        },
        yellow: {
          50: '#FFFDF5', 100: '#FFF9E1', 200: '#FFF5CC', 300: '#FFEA99', 400: '#FED634',
          500: '#FECB01', 600: '#CBA301', 700: '#987A01', 800: '#665100', 900: '#332900', 950: '#332900',
        },
      },
      fontFamily: {
        sans: ['Roboto', 'system-ui', 'sans-serif'],
        mono: ['Roboto Mono', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        // Theme-aware brand glow via --brand-500.
        'glow-orange': '0 0 22px rgb(var(--brand-500) / 0.30)',
        'glow-gold':   '0 0 22px rgb(var(--brand-500) / 0.30)',
        'glow-navy':   '0 10px 30px rgba(8, 31, 68, 0.35)',
        'glow-green':  '0 0 20px rgba(34, 197, 94, 0.3)',
        'glow-red':    '0 0 20px rgba(239, 68, 68, 0.3)',
      },
      animation: {
        'fade-in':    'fadeIn 0.3s ease-out',
        'slide-up':   'slideUp 0.3s ease-out',
        'slide-in':   'slideIn 0.3s ease-out',
        'pulse-slow': 'pulse 3s ease-in-out infinite',
      },
      keyframes: {
        fadeIn:  { from: { opacity: '0' }, to: { opacity: '1' } },
        slideUp: { from: { opacity: '0', transform: 'translateY(16px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        slideIn: { from: { opacity: '0', transform: 'translateX(-16px)' }, to: { opacity: '1', transform: 'translateX(0)' } },
      },
    },
  },
  plugins: [],
  // Ensure hover variants used inside @apply in index.css are generated,
  // since they don't appear directly in template files.
  safelist: [
    'hover:bg-brand-600',
    'hover:shadow-glow-orange',
    'hover:shadow-glow-navy',
    'hover:bg-surface-600',
    'hover:bg-surface-700',
    'hover:bg-surface-700/30',
    'hover:bg-surface-700/60',
    'hover:border-surface-600',
    'hover:text-white',
  ],
}
