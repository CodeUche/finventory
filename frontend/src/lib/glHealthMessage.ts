export interface GLSummaryLike { posted: number; failed: number; not_configured: number; pending: number }
export interface GLReconLike { is_balanced: boolean; all_reconciled: boolean }

export interface GLHealthNote {
  tone: 'good' | 'warn' | 'bad'
  title: string
  text: string
}

/**
 * The message under the GL Health cards when there is no failure list to show.
 * It must follow the numbers: green "all posted" only when nothing is pending,
 * failed or out of balance. The old panel always said "all posted" even with
 * pending entries and variances on the same page.
 */
export function glHealthNote(summary: GLSummaryLike, recon?: GLReconLike | null): GLHealthNote {
  if (summary.failed > 0 || summary.not_configured > 0) {
    return {
      tone: 'bad',
      title: 'Some entries did not post',
      text: 'Fix the account mapping, then retry the failed entries.',
    }
  }
  if (recon && (!recon.is_balanced || !recon.all_reconciled)) {
    return {
      tone: 'bad',
      title: 'The ledger does not balance with its subledgers',
      text: 'See Ledger Integrity above for the accounts with a variance.',
    }
  }
  if (summary.pending > 0) {
    const n = summary.pending
    return {
      tone: 'warn',
      title: `${n} ${n === 1 ? 'entry is' : 'entries are'} still waiting to post`,
      text: 'They will post on their own. Refresh in a moment to check.',
    }
  }
  return {
    tone: 'good',
    title: 'All GL entries posted successfully',
    text: 'No failed or misconfigured postings',
  }
}
