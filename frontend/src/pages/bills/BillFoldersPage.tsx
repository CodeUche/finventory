import { useEffect, useState, useCallback } from 'react'
import { useDataRefresh } from '@/hooks/useDataRefresh'
import { useSearchParams, useNavigate } from 'react-router-dom'
import {
  Folder, FolderOpen, FolderPlus, ChevronRight, Home,
  Trash2, Edit2, Loader2, X, Plus, ArrowLeft,
} from 'lucide-react'
import toast from 'react-hot-toast'
import { billApi } from '@/services/api'
import { formatCurrency, formatDate } from '@/lib/utils'

interface BillFolder {
  id: string
  name: string
  description: string
  folder_date: string | null
  parent: string | null
  children_count: number
  bills_count: number
  ancestors: { id: string; name: string }[]
}

interface BillSummary {
  id: string
  bill_number: string
  supplier_name: string
  status: string
  issue_date: string
  due_date: string
  total_amount: string
  amount_due: string
}

interface FolderForm { name: string; description: string; folder_date: string }
const today = new Date().toISOString().split('T')[0]
const BLANK_FOLDER: FolderForm = { name: '', description: '', folder_date: today }

const STATUS_COLOR: Record<string, string> = {
  paid: 'badge-green',
  approved: 'badge-blue',
  received: 'badge-slate',
  draft: 'badge-slate',
  overdue: 'badge-red',
  partially_paid: 'badge-orange',
  voided: 'badge-red',
}

export default function BillFoldersPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const currentFolderId = searchParams.get('folder') ?? null

  const [currentFolder, setCurrentFolder] = useState<BillFolder | null>(null)
  const [children, setChildren] = useState<BillFolder[]>([])
  const [bills, setBills] = useState<BillSummary[]>([])
  const [loading, setLoading] = useState(true)

  const [showFolderModal, setShowFolderModal] = useState(false)
  const [editingFolder, setEditingFolder] = useState<BillFolder | null>(null)
  const [folderForm, setFolderForm] = useState<FolderForm>(BLANK_FOLDER)
  const [savingFolder, setSavingFolder] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      if (currentFolderId) {
        const { data } = await billApi.folderContents(currentFolderId)
        setCurrentFolder(data.folder)
        setChildren(data.children)
        setBills(data.bills)
      } else {
        setCurrentFolder(null)
        const { data } = await billApi.folders({ parent: 'null' })
        setChildren(data.results ?? data)
        setBills([])
      }
    } catch {
      toast.error('Failed to load folder contents')
    } finally {
      setLoading(false)
    }
  }, [currentFolderId])

  useEffect(() => { load() }, [load])
  useDataRefresh(load)

  const openFolder = (id: string) => setSearchParams({ folder: id })
  const goHome = () => setSearchParams({})
  const goToAncestor = (id: string) => setSearchParams({ folder: id })

  const openCreateFolder = () => {
    setEditingFolder(null)
    setFolderForm(BLANK_FOLDER)
    setShowFolderModal(true)
  }

  const openEditFolder = (f: BillFolder, e: React.MouseEvent) => {
    e.stopPropagation()
    setEditingFolder(f)
    setFolderForm({ name: f.name, description: f.description, folder_date: f.folder_date ?? today })
    setShowFolderModal(true)
  }

  const handleSaveFolder = async (e: React.FormEvent) => {
    e.preventDefault()
    setSavingFolder(true)
    try {
      const payload = { ...folderForm, parent: currentFolderId ?? null }
      if (editingFolder) {
        await billApi.updateFolder(editingFolder.id, payload)
        toast.success('Folder updated')
      } else {
        await billApi.createFolder(payload)
        toast.success('Folder created')
      }
      setShowFolderModal(false)
      load()
    } catch {
      toast.error('Failed to save folder')
    } finally {
      setSavingFolder(false)
    }
  }

  const handleDeleteFolder = async (f: BillFolder, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm(`Delete folder "${f.name}"? Bills inside will be unassigned.`)) return
    try {
      await billApi.deleteFolder(f.id)
      toast.success('Folder deleted')
      load()
    } catch {
      toast.error('Failed to delete folder')
    }
  }

  const ancestors = currentFolder?.ancestors ?? []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {currentFolderId && (
            <button
              onClick={() => {
                const parentId = currentFolder?.ancestors?.slice(-1)[0]?.id
                parentId ? setSearchParams({ folder: parentId }) : goHome()
              }}
              className="btn-ghost p-2 text-slate-400 hover:text-white"
              title="Go back"
            >
              <ArrowLeft size={18} />
            </button>
          )}
          <div>
            <h1 className="text-2xl font-bold text-white">
              {currentFolder ? currentFolder.name : 'Bill Folders'}
            </h1>
            <p className="text-slate-400 text-sm">
              {currentFolder
                ? `Folder · ${currentFolder.bills_count} bill${currentFolder.bills_count !== 1 ? 's' : ''}`
                : 'Organise your bills into folders for easy retrieval'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={openCreateFolder} className="btn-secondary flex items-center gap-2">
            <FolderPlus size={15} /> New Folder
          </button>
          {currentFolderId && (
            <button
              onClick={() => navigate(`/bills?openNew=1&folder=${currentFolderId}`)}
              className="btn-primary flex items-center gap-2"
            >
              <Plus size={15} /> New Bill in Folder
            </button>
          )}
        </div>
      </div>

      {/* Breadcrumb */}
      <div className="flex items-center gap-1.5 text-sm text-slate-400 flex-wrap">
        <button onClick={() => navigate('/bills')} className="flex items-center gap-1 hover:text-white transition-colors">
          <ArrowLeft size={13} /> Bills
        </button>
        <span className="text-slate-600">/</span>
        <button onClick={goHome} className="flex items-center gap-1 hover:text-white transition-colors">
          <Home size={13} /> Bill Folders
        </button>
        {ancestors.map((a) => (
          <span key={a.id} className="flex items-center gap-1.5">
            <ChevronRight size={13} />
            <button onClick={() => goToAncestor(a.id)} className="hover:text-white transition-colors">{a.name}</button>
          </span>
        ))}
        {currentFolder && (
          <span className="flex items-center gap-1.5">
            <ChevronRight size={13} />
            <span className="text-white font-medium">{currentFolder.name}</span>
          </span>
        )}
      </div>

      {loading ? (
        <div className="py-16 text-center"><Loader2 size={28} className="animate-spin mx-auto text-brand-400" /></div>
      ) : (
        <div className="space-y-4">
          {/* Sub-folders */}
          {children.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">Folders</h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                {children.map((f) => (
                  <div
                    key={f.id}
                    onClick={() => openFolder(f.id)}
                    className="card p-4 cursor-pointer hover:border-brand-500/50 transition-all group"
                  >
                    <div className="flex items-start gap-3">
                      <div className="w-10 h-10 rounded-xl bg-brand-500/10 flex items-center justify-center shrink-0">
                        {f.children_count > 0 || f.bills_count > 0
                          ? <FolderOpen size={20} className="text-brand-400" />
                          : <Folder size={20} className="text-brand-400" />}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="font-medium text-white text-sm truncate">{f.name}</p>
                        <p className="text-xs text-slate-500 mt-0.5">
                          {f.children_count} sub-folder{f.children_count !== 1 ? 's' : ''} · {f.bills_count} bill{f.bills_count !== 1 ? 's' : ''}
                        </p>
                        {f.folder_date && <p className="text-xs text-slate-600 mt-0.5">{formatDate(f.folder_date)}</p>}
                      </div>
                      <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button onClick={(e) => openEditFolder(f, e)} className="btn-ghost p-1 text-slate-500 hover:text-white">
                          <Edit2 size={12} />
                        </button>
                        <button onClick={(e) => handleDeleteFolder(f, e)} className="btn-ghost p-1 text-slate-500 hover:text-red-400">
                          <Trash2 size={12} />
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Bills in this folder */}
          {currentFolder && bills.length > 0 && (
            <div>
              <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">Bills in this folder</h3>
              <div className="card p-0 overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-surface-700">
                      {['Bill #', 'Supplier', 'Issue Date', 'Due Date', 'Total', 'Amount Due', 'Status'].map((h) => (
                        <th key={h} className="px-5 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wider">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {bills.map((b) => (
                      <tr key={b.id} className="table-row">
                        <td className="px-5 py-3 font-mono text-xs text-brand-400">{b.bill_number}</td>
                        <td className="px-5 py-3 text-white font-medium">{b.supplier_name}</td>
                        <td className="px-5 py-3 text-slate-300">{formatDate(b.issue_date)}</td>
                        <td className="px-5 py-3 text-slate-300">{formatDate(b.due_date)}</td>
                        <td className="px-5 py-3 text-white">{formatCurrency(b.total_amount)}</td>
                        <td className="px-5 py-3 text-slate-300">{formatCurrency(b.amount_due)}</td>
                        <td className="px-5 py-3">
                          <span className={STATUS_COLOR[b.status] ?? 'badge-slate'}>{b.status}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {children.length === 0 && bills.length === 0 && (
            <div className="py-16 text-center">
              <Folder size={40} className="mx-auto mb-3 text-slate-600" />
              <p className="text-slate-400 font-medium mb-1">
                {currentFolder ? 'This folder is empty' : 'No folders yet'}
              </p>
              <p className="text-slate-600 text-sm">
                {currentFolder
                  ? 'Create sub-folders or add bills directly to this folder.'
                  : 'Create a folder to start organising your bills by month, year, project, etc.'}
              </p>
              <div className="flex items-center justify-center gap-2 mt-4">
                <button onClick={openCreateFolder} className="btn-secondary inline-flex items-center gap-2">
                  <FolderPlus size={14} /> Create Folder
                </button>
                {currentFolderId && (
                  <button
                    onClick={() => navigate(`/bills?openNew=1&folder=${currentFolderId}`)}
                    className="btn-primary inline-flex items-center gap-2"
                  >
                    <Plus size={14} /> New Bill
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Folder Modal */}
      {showFolderModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm">
          <div className="bg-surface-800 border border-surface-700 rounded-2xl w-full max-w-md shadow-2xl animate-slide-up">
            <div className="flex items-center justify-between p-6 border-b border-surface-700">
              <h2 className="font-semibold text-white">{editingFolder ? 'Edit Folder' : 'New Folder'}</h2>
              <button onClick={() => setShowFolderModal(false)} className="btn-ghost p-1.5"><X size={18} /></button>
            </div>
            <form onSubmit={handleSaveFolder} className="p-6 space-y-4">
              <div>
                <label className="label">Folder Name *</label>
                <input className="input" value={folderForm.name} onChange={(e) => setFolderForm((f) => ({ ...f, name: e.target.value }))} required placeholder="e.g. January 2026, Q1 Utilities" />
              </div>
              <div>
                <label className="label">Description</label>
                <textarea className="input h-20 resize-none" value={folderForm.description} onChange={(e) => setFolderForm((f) => ({ ...f, description: e.target.value }))} placeholder="Optional note about this folder" />
              </div>
              <div>
                <label className="label">Folder Date</label>
                <input type="date" className="input" value={folderForm.folder_date} onChange={(e) => setFolderForm((f) => ({ ...f, folder_date: e.target.value }))} />
              </div>
              {currentFolder && (
                <p className="text-xs text-slate-500 flex items-center gap-1.5">
                  <Folder size={12} /> Will be created inside <strong className="text-slate-300">{currentFolder.name}</strong>
                </p>
              )}
              <div className="flex gap-3 pt-2">
                <button type="button" onClick={() => setShowFolderModal(false)} className="btn-secondary flex-1 justify-center">Cancel</button>
                <button type="submit" disabled={savingFolder} className="btn-primary flex-1 justify-center">
                  {savingFolder ? <Loader2 size={16} className="animate-spin" /> : (editingFolder ? 'Save' : 'Create')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
