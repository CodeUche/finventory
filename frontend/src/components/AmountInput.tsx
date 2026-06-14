import { forwardRef } from 'react'
import { formatAmountInput } from '@/lib/utils'

interface AmountInputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'onChange' | 'type'> {
  value: string
  onChange: (formatted: string) => void
}

const AmountInput = forwardRef<HTMLInputElement, AmountInputProps>(
  ({ value, onChange, onFocus, ...props }, ref) => {
    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      onChange(formatAmountInput(e.target.value))
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
        ref={ref}
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
