import { NO_REPORT_ACCESS_NOTE } from '@/hooks/useReportAccess'

/** Plain, quiet note shown where a report needs a permission the person does not hold. */
export default function NoAccessNote({ className = '' }: { className?: string }) {
  return (
    <p
      data-testid="report-no-access"
      className={`text-sm text-slate-400 text-center py-8 ${className}`}
    >
      {NO_REPORT_ACCESS_NOTE}
    </p>
  )
}
