/**
 * App-native replacements for window.confirm / window.prompt / window.alert.
 *
 * The Tauri desktop WebView renders those built-ins as an unstyled
 * "tauri.localhost says …" system box. These helpers instead render a themed
 * modal (matching the rest of Audity) via a single <DialogHost/> mounted once
 * near the app root, and return a Promise so call sites read almost identically:
 *
 *   if (!(await confirmDialog('Delete this invoice?'))) return
 *   const reason = await promptDialog('Reason for rejection', { optional: true })
 *   await alertDialog('Saved!')
 *
 * confirmDialog → boolean · promptDialog → string | null (null = cancelled).
 */
import { useEffect, useState } from 'react'
import { create } from 'zustand'
import { X } from 'lucide-react'
import { useEscapeLayer } from '@/lib/escapeStack'

type Kind = 'confirm' | 'prompt' | 'alert'

interface DialogRequest {
  id: number
  kind: Kind
  title: string
  message?: string
  confirmText: string
  cancelText: string
  danger: boolean
  placeholder?: string
  defaultValue?: string
  optional: boolean
  multiline: boolean
  resolve: (value: boolean | string | null) => void
}

interface DialogStore {
  current: DialogRequest | null
  enqueue: (req: DialogRequest) => void
  clear: () => void
}

const useDialogStore = create<DialogStore>((set) => ({
  current: null,
  enqueue: (req) => set({ current: req }),
  clear: () => set({ current: null }),
}))

let _id = 0
const DANGER_RE = /\b(delete|remove|revoke|void|cancel|deactivate|discard|permanent|clear all|reject|unlink|purge)\b/i
// The action word shown on the red button ("Delete", "Remove", ...), taken from the question.
const ACTION_RE = /\b(delete|remove|revoke|void|deactivate|discard|reject|unlink|purge)\b/i

interface ConfirmOpts {
  title?: string
  confirmText?: string
  cancelText?: string
  danger?: boolean
}
interface PromptOpts extends ConfirmOpts {
  placeholder?: string
  defaultValue?: string
  optional?: boolean
  multiline?: boolean
}

/** "Delete" on a delete question, "Confirm" otherwise (a prompt says "Save", an alert "OK"). */
export function defaultConfirmText(kind: Kind, danger: boolean, text: string): string {
  if (kind === 'alert') return 'OK'
  if (kind === 'prompt') return 'Save'
  const m = danger ? ACTION_RE.exec(text) : null
  return m ? m[1].charAt(0).toUpperCase() + m[1].slice(1).toLowerCase() : 'Confirm'
}

function base(kind: Kind, message: string, opts: PromptOpts = {}): Promise<boolean | string | null> {
  // When no explicit title is given, use the first line of the message as the
  // heading and the rest as the body — many legacy confirm() strings pack a
  // question + explanation separated by "\n\n" (which HTML would collapse).
  let title = opts.title
  let body: string | undefined = opts.title ? message : undefined
  if (!title) {
    const idx = message.indexOf('\n')
    if (idx === -1) { title = message; body = undefined }
    else { title = message.slice(0, idx).trim(); body = message.slice(idx + 1).trim() || undefined }
  }
  const danger = opts.danger ?? DANGER_RE.test(message + ' ' + (opts.title ?? ''))
  return new Promise((resolve) => {
    useDialogStore.getState().enqueue({
      id: ++_id,
      kind,
      title,
      message: body,
      confirmText: opts.confirmText ?? defaultConfirmText(kind, danger, message + ' ' + (opts.title ?? '')),
      cancelText: opts.cancelText ?? 'Cancel',
      danger,
      placeholder: opts.placeholder,
      defaultValue: opts.defaultValue,
      optional: opts.optional ?? true,
      multiline: opts.multiline ?? false,
      resolve,
    })
  })
}

export const confirmDialog = (message: string, opts: ConfirmOpts = {}) =>
  base('confirm', message, opts) as Promise<boolean>

export const promptDialog = (message: string, opts: PromptOpts = {}) =>
  base('prompt', message, opts) as Promise<string | null>

export const alertDialog = (message: string, opts: ConfirmOpts = {}) =>
  base('alert', message, opts) as Promise<boolean>

/** Mount once (App root). Renders the active dialog and resolves its promise. */
export function DialogHost() {
  const current = useDialogStore((s) => s.current)
  const clear = useDialogStore((s) => s.clear)
  const [value, setValue] = useState('')

  useEffect(() => { setValue(current?.defaultValue ?? '') }, [current?.id])

  // Escape closes the dialog as Cancel (one app-wide Escape handler; this dialog is always on top).
  useEscapeLayer(!!current, () => {
    if (!current) return
    current.resolve(current.kind === 'prompt' ? null : false)
    clear()
  })

  if (!current) return null

  const finish = (result: boolean | string | null) => { current.resolve(result); clear() }
  const onCancel = () => finish(current.kind === 'prompt' ? null : false)
  const onConfirm = () => {
    if (current.kind === 'prompt') {
      if (!current.optional && value.trim().length === 0) return
      finish(value.trim())
    } else {
      finish(true)
    }
  }
  const titleId = `ds-dialog-title-${current.id}`

  // One look for every confirm / delete / prompt (designer's Pop Up 58, 111, 121): the title and text
  // are centred, Cancel is the outlined navy button, and a delete is the solid pink Delete.
  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby={titleId}>
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onCancel} />
      <div className="relative ds-dialog" data-kit-skip="">
        <button type="button" onClick={onCancel} className="ds-dialog-x" aria-label="Close"><X size={20} /></button>
        <h2 id={titleId} className="ds-dialog-title">{current.title}</h2>
        {current.message && <p className="ds-dialog-text">{current.message}</p>}

        {current.kind === 'prompt' && (
          current.multiline ? (
            <textarea
              className="input resize-none" rows={3} autoFocus placeholder={current.placeholder}
              value={value} onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) onConfirm() }}
            />
          ) : (
            <input
              className="input" autoFocus placeholder={current.placeholder}
              value={value} onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') onConfirm() }}
            />
          )
        )}

        <div className="ds-dialog-actions">
          {current.kind !== 'alert' && (
            <button type="button" className="btn-secondary" data-kit-role="cancel" onClick={onCancel}>
              {current.cancelText}
            </button>
          )}
          <button
            type="button"
            className={current.danger ? 'ds-btn-delete' : 'btn-primary'}
            onClick={onConfirm}
            autoFocus={current.kind === 'alert'}
          >
            {current.confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}
