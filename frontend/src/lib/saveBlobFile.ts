/**
 * Save a Blob to disk.
 *
 * - Tauri desktop: opens a native Save-As dialog via tauri-plugin-dialog,
 *   then writes to the chosen path via tauri-plugin-fs.
 * - Browser: falls back to the standard anchor-download approach.
 */

import toast from 'react-hot-toast'

const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window

const EXT_FILTERS: Record<string, { name: string; extensions: string[] }[]> = {
  pdf:  [{ name: 'PDF Files',   extensions: ['pdf'] }],
  csv:  [{ name: 'CSV Files',   extensions: ['csv'] }],
  xlsx: [{ name: 'Excel Files', extensions: ['xlsx'] }],
}

/**
 * @param blob     The file content as a Blob
 * @param filename Default filename including extension, e.g. "invoice-001.pdf"
 */
export async function saveBlobFile(blob: Blob, filename: string): Promise<void> {
  if (isTauri) {
    const ext = filename.split('.').pop()?.toLowerCase() ?? 'pdf'
    const filters = EXT_FILTERS[ext] ?? [{ name: 'Files', extensions: [ext] }]

    const { save } = await import('@tauri-apps/plugin-dialog')
    const { writeFile } = await import('@tauri-apps/plugin-fs')

    const savePath = await save({ defaultPath: filename, filters })
    if (!savePath) return // user cancelled

    const arrayBuffer = await blob.arrayBuffer()
    await writeFile(savePath, new Uint8Array(arrayBuffer))
    toast.success(`Saved to ${savePath.split(/[\\/]/).pop()}`)
  } else {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    setTimeout(() => URL.revokeObjectURL(url), 30_000)
  }
}
