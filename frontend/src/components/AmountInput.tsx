import { forwardRef, useRef } from 'react'
import { formatAmountInput } from '@/lib/utils'

interface AmountInputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'onChange' | 'type'> {
  value: string
  onChange: (formatted: string) => void
}

/**
 * Comma-formatted amount input with CARET PRESERVATION.
 *
 * Reformatting the value on every keystroke normally makes React reset the
 * cursor to the end of the field — so editing "23,4|80,000" deleted from the
 * back no matter where the user clicked. We count the significant characters
 * (digits / decimal point) before the caret in what the user typed, format,
 * then restore the caret after the same number of significant characters in
 * the formatted string.
 */
const AmountInput = forwardRef<HTMLInputElement, AmountInputProps>(
  ({ value, onChange, onFocus, ...props }, ref) => {
    const innerRef = useRef<HTMLInputElement | null>(null)

    const setRefs = (node: HTMLInputElement | null) => {
      innerRef.current = node
      if (typeof ref === 'function') ref(node)
      else if (ref) (ref as React.MutableRefObject<HTMLInputElement | null>).current = node
    }

    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      const el = e.target
      const raw = el.value
      const caret = el.selectionStart ?? raw.length

      // How many significant chars (digits or '.') sit before the caret?
      let sig = 0
      for (let i = 0; i < caret; i++) if (/[0-9.]/.test(raw[i])) sig++

      const formatted = formatAmountInput(raw)

      // Caret goes after the same count of significant chars in the new string.
      let pos = 0
      let seen = 0
      while (pos < formatted.length && seen < sig) {
        if (/[0-9.]/.test(formatted[pos])) seen++
        pos++
      }

      onChange(formatted)
      requestAnimationFrame(() => {
        const n = innerRef.current
        if (n && document.activeElement === n) n.setSelectionRange(pos, pos)
      })
    }

    const handleFocus = (e: React.FocusEvent<HTMLInputElement>) => {
      const stripped = e.target.value.replace(/,/g, '').trim()
      if (!stripped || parseFloat(stripped) === 0) {
        onChange('')
      }
      onFocus?.(e)
    }

    return (
      <input
        ref={setRefs}
        type="text"
        inputMode="decimal"
        value={value}
        onChange={handleChange}
        onFocus={handleFocus}
        {...props}
      />
    )
  }
)

AmountInput.displayName = 'AmountInput'
export default AmountInput
