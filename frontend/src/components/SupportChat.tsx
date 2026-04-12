import { useState, useRef, useEffect } from 'react'
import { MessageCircle, X, Send, Loader2, Bot, User, ChevronDown } from 'lucide-react'
import { aiApi } from '@/services/api'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

const FAQS = [
  'How do I create an invoice?',
  'How do I add a product?',
  'How do I record a payment?',
  'How do I set up VAT?',
  'What does each plan include?',
  'How do I invite a team member?',
  'How do I run payroll?',
  'How do I process a sales return?',
]

function renderMarkdown(text: string): string {
  const lines = text.split('\n')
  const out: string[] = []
  let inUl = false
  let inOl = false

  const closeUl = () => { if (inUl) { out.push('</ul>'); inUl = false } }
  const closeOl = () => { if (inOl) { out.push('</ol>'); inOl = false } }
  const closeLists = () => { closeUl(); closeOl() }

  // Escape raw HTML before applying markdown so injected tags can't execute
  const escapeHtml = (s: string) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')

  const inline = (s: string) =>
    escapeHtml(s)
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      .replace(/`([^`]+)`/g, '<code class="bg-surface-600 px-1 rounded text-xs font-mono">$1</code>')

  for (const raw of lines) {
    const line = raw.trimEnd()

    // H3
    if (/^###\s/.test(line)) {
      closeLists()
      out.push(`<p class="text-xs font-bold text-brand-400 uppercase tracking-wide mt-3 mb-1">${inline(line.slice(4))}</p>`)
      continue
    }
    // H2
    if (/^##\s/.test(line)) {
      closeLists()
      out.push(`<p class="text-sm font-bold text-white mt-3 mb-1">${inline(line.slice(3))}</p>`)
      continue
    }
    // Unordered list
    if (/^[-•*]\s/.test(line)) {
      closeOl()
      if (!inUl) { out.push('<ul class="list-disc pl-4 space-y-0.5 my-1">'); inUl = true }
      out.push(`<li>${inline(line.replace(/^[-•*]\s/, ''))}</li>`)
      continue
    }
    // Ordered list
    if (/^\d+\.\s/.test(line)) {
      closeUl()
      if (!inOl) { out.push('<ol class="list-decimal pl-4 space-y-0.5 my-1">'); inOl = true }
      out.push(`<li>${inline(line.replace(/^\d+\.\s/, ''))}</li>`)
      continue
    }
    // Blank line
    if (line === '') {
      closeLists()
      out.push('<div class="h-1.5"></div>')
      continue
    }
    // Normal paragraph line
    closeLists()
    out.push(`<p>${inline(line)}</p>`)
  }

  closeLists()
  return out.join('')
}

export default function SupportChat() {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      content: "Hi! I'm Audity Support. Ask me anything about how to use the app — invoices, inventory, payroll, reports, and more. Or pick a common question below.",
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [showFaqs, setShowFaqs] = useState(true)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 100)
    }
  }, [open])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const send = async (text: string) => {
    const msg = text.trim()
    if (!msg || loading) return
    setInput('')
    setShowFaqs(false)
    setMessages((prev) => [...prev, { role: 'user', content: msg }])
    setLoading(true)
    try {
      const { data } = await aiApi.support(msg)
      setMessages((prev) => [...prev, { role: 'assistant', content: data.response }])
    } catch (err: any) {
      const errMsg = err?.response?.data?.error ?? 'Support is temporarily unavailable. Email support@audity.app for help.'
      setMessages((prev) => [...prev, { role: 'assistant', content: errMsg }])
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    send(input)
  }

  return (
    <>
      {/* Floating button */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="fixed bottom-5 right-5 z-50 w-13 h-13 rounded-full bg-brand-500 hover:bg-brand-600 text-white shadow-xl flex items-center justify-center transition-all duration-200 hover:scale-110"
        style={{ width: 52, height: 52 }}
        title="Support Chat"
        aria-label="Open support chat"
      >
        {open ? <X size={22} /> : <MessageCircle size={22} />}
        {!open && messages.length > 1 && (
          <span className="absolute -top-1 -right-1 w-4 h-4 bg-emerald-400 rounded-full border-2 border-surface-950" />
        )}
      </button>

      {/* Chat panel */}
      {open && (
        <div className="fixed bottom-20 right-5 z-50 w-[360px] max-w-[calc(100vw-2rem)] bg-surface-800 border border-surface-700 rounded-2xl shadow-2xl flex flex-col overflow-hidden animate-slide-up"
          style={{ height: 520, maxHeight: 'calc(100vh - 120px)' }}>

          {/* Header */}
          <div className="flex items-center gap-3 px-4 py-3 border-b border-surface-700 bg-surface-900 shrink-0">
            <div className="w-8 h-8 rounded-full bg-brand-500/20 flex items-center justify-center">
              <Bot size={16} className="text-brand-400" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-white leading-tight">Audity Support</p>
              <p className="text-xs text-emerald-400">Online · AI-powered</p>
            </div>
            <button onClick={() => setOpen(false)} className="btn-ghost p-1 text-slate-400">
              <ChevronDown size={18} />
            </button>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
            {messages.map((m, i) => (
              <div key={i} className={`flex gap-2 ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                {m.role === 'assistant' && (
                  <div className="w-6 h-6 rounded-full bg-brand-500/20 flex items-center justify-center shrink-0 mt-0.5">
                    <Bot size={12} className="text-brand-400" />
                  </div>
                )}
                <div
                  className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm leading-relaxed ${
                    m.role === 'user'
                      ? 'bg-brand-500 text-white rounded-br-sm'
                      : 'bg-surface-700 text-slate-200 rounded-bl-sm'
                  }`}
                >
                  {m.role === 'assistant' ? (
                    <div
                      className="prose prose-invert prose-sm max-w-none"
                      dangerouslySetInnerHTML={{ __html: renderMarkdown(m.content) }}
                    />
                  ) : (
                    m.content
                  )}
                </div>
                {m.role === 'user' && (
                  <div className="w-6 h-6 rounded-full bg-surface-600 flex items-center justify-center shrink-0 mt-0.5">
                    <User size={12} className="text-slate-400" />
                  </div>
                )}
              </div>
            ))}

            {loading && (
              <div className="flex gap-2 justify-start">
                <div className="w-6 h-6 rounded-full bg-brand-500/20 flex items-center justify-center shrink-0 mt-0.5">
                  <Bot size={12} className="text-brand-400" />
                </div>
                <div className="bg-surface-700 rounded-2xl rounded-bl-sm px-4 py-3 flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-1.5 h-1.5 rounded-full bg-slate-400 animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            )}

            {/* FAQ chips */}
            {showFaqs && !loading && (
              <div className="pt-1 flex flex-wrap gap-2">
                {FAQS.map((q) => (
                  <button
                    key={q}
                    onClick={() => send(q)}
                    className="text-xs px-3 py-1.5 rounded-full bg-surface-700 hover:bg-surface-600 text-slate-300 hover:text-white border border-surface-600 hover:border-brand-500/50 transition-colors text-left"
                  >
                    {q}
                  </button>
                ))}
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <form onSubmit={handleSubmit} className="flex items-center gap-2 px-3 py-3 border-t border-surface-700 bg-surface-900 shrink-0">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask anything about Audity…"
              disabled={loading}
              className="flex-1 bg-surface-700 border border-surface-600 rounded-xl px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-brand-500 disabled:opacity-60"
            />
            <button
              type="submit"
              disabled={!input.trim() || loading}
              className="w-9 h-9 rounded-xl bg-brand-500 hover:bg-brand-600 disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center transition-colors shrink-0"
            >
              {loading ? <Loader2 size={15} className="animate-spin text-white" /> : <Send size={15} className="text-white" />}
            </button>
          </form>
        </div>
      )}
    </>
  )
}
