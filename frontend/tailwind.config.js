/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Brand = Audity gold. Drives all accent/highlight usages (active nav,
        // links, icon tiles, focus rings). Primary buttons are navy — see
        // .btn-primary in index.css. (Was orange.)
        brand: {
          50:  '#FBF6E6',
          100: '#F8ECC4',
          200: '#F2DD97',
          300: '#EFD06F',
          400: '#E8B65A',  // accent text/icons on dark
          500: '#D4A017',  // primary gold
          600: '#B8891F',
          700: '#9A7416',  // gold text on light surfaces
          800: '#7E5E12',
          900: '#5F470E',
          950: '#3A2B08',
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
        gold: {
          400: '#E8B65A',
          500: '#D4A017',
          600: '#B8891F',
          700: '#9A7416',
        },
        // Kill orange app-wide: any leftover `*-orange-*` utility now renders gold.
        orange: {
          50:  '#FBF6E6', 100: '#F8ECC4', 200: '#F2DD97', 300: '#EFD06F', 400: '#E8B65A',
          500: '#D4A017', 600: '#B8891F', 700: '#9A7416', 800: '#7E5E12', 900: '#5F470E', 950: '#3A2B08',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      boxShadow: {
        // 'glow-orange' kept as a name for back-compat but now emits a gold glow.
        'glow-orange': '0 0 22px rgba(212, 160, 23, 0.30)',
        'glow-gold':   '0 0 22px rgba(212, 160, 23, 0.30)',
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
