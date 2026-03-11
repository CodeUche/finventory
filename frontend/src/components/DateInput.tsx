/**
 * DateInput — DD/MM/YYYY text field with a native calendar picker.
 *
 * - Displays and accepts input in DD/MM/YYYY format
 * - Auto-inserts "/" separators as the user types
 * - Calendar icon opens the native <input type="date"> picker
 * - value / onChange always use YYYY-MM-DD (ISO) for API compatibility
 */

import { useRef, useState, useEffect } from 'react'
import { CalendarDays } from 'lucide-react'

interface DateInputProps {
  value: string          // YYYY-MM-DD or ""
  onChange: (iso: string) => void
  placeholder?: string
  className?: string
  min?: string           // YYYY-MM-DD
  max?: string           // YYYY-MM-DD
  disabled?: boolean
  id?: string
  name?: string
}

/** "2025-12-31" → "31/12/2025" */
function isoToDisplay(iso: string): string {
  if (!iso) return ''
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (!m) return ''
  return `${m[3]}/${m[2]}/${m[1]}`
}

/** "31/12/2025" → "2025-12-31" (returns "" if invalid / incomplete) */
function displayToIso(display: string): string {
  const m = display.match(/^(\d{2})\/(\d{2})\/(\d{4})$/)
  if (!m) return ''
  const day = parseInt(m[1], 10)
  const month = parseInt(m[2], 10)
  const year = parseInt(m[3], 10)
  if (month < 1 || month > 12 || day < 1 || day > 31 || year < 1000) return ''
  const d = new Date(year, month - 1, day)
  if (d.getFullYear() !== year || d.getMonth() !== month - 1 || d.getDate() !== day) return ''
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

/** Auto-insert slashes: "3112" → "31/12/" etc. */
function autoFormat(raw: string): string {
  // Strip non-digits
  const digits = raw.replace(/\D/g, '')
  if (digits.length <= 2) return digits
  if (digits.length <= 4) return `${digits.slice(0, 2)}/${digits.slice(2)}`
  return `${digits.slice(0, 2)}/${digits.slice(2, 4)}/${digits.slice(4, 8)}`
}

export default function DateInput({
  value,
  onChange,
  placeholder = 'DD/MM/YYYY',
  className = '',
  min,
  max,
  disabled,
  id,
  name,
}: DateInputProps) {
  const [display, setDisplay] = useState(isoToDisplay(value))
  const hiddenRef = useRef<HTMLInputElement>(null)

  // Sync when parent changes value externally
  useEffect(() => {
    setDisplay(isoToDisplay(value))
  }, [value])

  function handleTextChange(e: React.ChangeEvent<HTMLInputElement>) {
    const raw = e.target.value
    const formatted = autoFormat(raw)
    setDisplay(formatted)
    const iso = displayToIso(formatted)
    if (iso) onChange(iso)
    else if (!formatted) onChange('')
  }

  function handleTextBlur() {
    // On blur: if we have a full display string, validate it
    const iso = displayToIso(display)
    if (iso) {
      setDisplay(isoToDisplay(iso))
      onChange(iso)
    } else if (!display) {
      onChange('')
    }
    // If invalid partial input, leave it as-is so user can see and correct it
  }

  function handleCalendarChange(e: React.ChangeEvent<HTMLInputElement>) {
    const iso = e.target.value // YYYY-MM-DD from native picker
    onChange(iso)
    setDisplay(isoToDisplay(iso))
  }

  function openCalendar() {
    hiddenRef.current?.showPicker?.()
    hiddenRef.current?.click()
  }

  return (
    <div className={`relative ${className}`}>
      <input
        id={id}
        name={name}
        type="text"
        value={display}
        onChange={handleTextChange}
        onBlur={handleTextBlur}
        placeholder={placeholder}
        disabled={disabled}
        maxLength={10}
        className="input pr-10"
        autoComplete="off"
      />
      <button
        type="button"
        tabIndex={-1}
        onClick={openCalendar}
        disabled={disabled}
        className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-brand-400 transition-colors disabled:opacity-40"
        aria-label="Open date picker"
      >
        <CalendarDays size={16} />
      </button>
      {/* Hidden native date input — used only for the calendar popup */}
      <input
        ref={hiddenRef}
        type="date"
        value={value || ''}
        min={min}
        max={max}
        onChange={handleCalendarChange}
        tabIndex={-1}
        className="sr-only"
        aria-hidden="true"
      />
    </div>
  )
}
