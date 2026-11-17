import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

const inFlight = vi.hoisted(() => ({ value: false }))
vi.mock('@/services/api', () => ({ hasMutationInFlight: () => inFlight.value }))

import { handleEscape, registerEscapeLayer, _resetEscapeLayers, findTopOverlay } from '@/lib/escapeStack'
import { onceThisSession, _forgetOnceKeys } from '@/lib/onceThisSession'
import { defaultConfirmText } from '@/lib/dialog'
import { tagPopup } from '@/lib/popupEnhance'

function html(markup: string): HTMLElement {
  const host = document.createElement('div')
  host.innerHTML = markup
  document.body.appendChild(host)
  return host
}

describe('Escape stack', () => {
  let host: HTMLElement | null = null
  beforeEach(() => { inFlight.value = false; _resetEscapeLayers() })
  afterEach(() => { host?.remove(); host = null })

  it('closes only the newest registered layer per key press', () => {
    const order: string[] = []
    registerEscapeLayer(() => order.push('a'))
    const offB = registerEscapeLayer(() => order.push('b'))
    expect(handleEscape()).toBe(true)
    expect(order).toEqual(['b'])
    offB()
    expect(handleEscape()).toBe(true)
    expect(order).toEqual(['b', 'a'])
  })

  it('a registered layer is closed before a pop-up written as plain markup', () => {
    host = html('<div class="fixed inset-0 z-50"><button id="x"><svg class="lucide lucide-x"></svg></button></div>')
    const clicked = vi.fn()
    host.querySelector('#x')!.addEventListener('click', clicked)
    const layer = vi.fn()
    registerEscapeLayer(layer)
    handleEscape()
    expect(layer).toHaveBeenCalledOnce()
    expect(clicked).not.toHaveBeenCalled()
  })

  it('presses the X in the pop-up header, not a remove-X further down', () => {
    host = html(`<div class="fixed inset-0 z-50"><div class="card">
      <div><h2>Title</h2><button id="close"><svg class="lucide lucide-x"></svg></button></div>
      <div><button id="row"><svg class="lucide lucide-x"></svg></button></div></div></div>`)
    // jsdom has no layout: give the row button a far-down position so the header rule can tell them apart.
    host.querySelector('#row')!.getBoundingClientRect = () => ({ top: 400, bottom: 420, left: 0, right: 0, width: 20, height: 20, x: 0, y: 400, toJSON() {} })
    const close = vi.fn(); const row = vi.fn()
    host.querySelector('#close')!.addEventListener('click', close)
    host.querySelector('#row')!.addEventListener('click', row)
    expect(handleEscape()).toBe(true)
    expect(close).toHaveBeenCalledOnce()
    expect(row).not.toHaveBeenCalled()
  })

  it('falls back to a Cancel button, then to clicking the backdrop', () => {
    host = html('<div class="fixed inset-0 z-50"><div class="card"><button id="c">Cancel</button><button id="s">Save</button></div></div>')
    const c = vi.fn(); const s = vi.fn()
    host.querySelector('#c')!.addEventListener('click', c)
    host.querySelector('#s')!.addEventListener('click', s)
    handleEscape()
    expect(c).toHaveBeenCalledOnce(); expect(s).not.toHaveBeenCalled()
    host.remove()
    host = html('<div class="fixed inset-0 z-50"><div id="bd" class="absolute inset-0"></div><div class="card"><button>Save</button></div></div>')
    const bd = vi.fn()
    host.querySelector('#bd')!.addEventListener('click', bd)
    handleEscape()
    expect(bd).toHaveBeenCalledOnce()
  })

  it('does nothing while a save is running or the save button shows its spinner', () => {
    host = html('<div class="fixed inset-0 z-50"><div class="card"><button id="c">Cancel</button></div></div>')
    const c = vi.fn()
    host.querySelector('#c')!.addEventListener('click', c)
    inFlight.value = true
    expect(handleEscape()).toBe(false)
    inFlight.value = false
    host.querySelector('.card')!.insertAdjacentHTML('beforeend', '<button disabled><svg class="animate-spin"></svg></button>')
    expect(handleEscape()).toBe(false)
    expect(c).not.toHaveBeenCalled()
  })

  it('a dropdown click-catcher inside a pop-up closes first; the pop-up on the next press', () => {
    host = html(`<div id="modal" class="fixed inset-0 z-50"><div class="card"><button id="c">Cancel</button>
      <div id="catcher" class="fixed inset-0 z-40"></div></div></div>`)
    const catcher = vi.fn(); const cancel = vi.fn()
    host.querySelector('#catcher')!.addEventListener('click', () => { catcher(); host!.querySelector('#catcher')!.remove() })
    host.querySelector('#c')!.addEventListener('click', cancel)
    expect(findTopOverlay()?.id).toBe('catcher')
    handleEscape()
    expect(catcher).toHaveBeenCalledOnce(); expect(cancel).not.toHaveBeenCalled()
    handleEscape()
    expect(cancel).toHaveBeenCalledOnce()
  })

  it('leaves a gate that must not be dismissed alone', () => {
    host = html('<div class="fixed inset-0 z-50" data-no-escape><div class="card"><button id="c">Cancel</button></div></div>')
    const c = vi.fn()
    host.querySelector('#c')!.addEventListener('click', c)
    expect(handleEscape()).toBe(false)
    expect(c).not.toHaveBeenCalled()
  })
})

describe('once per session', () => {
  beforeEach(() => _forgetOnceKeys())
  it('is true the first time and false after, per key', () => {
    expect(onceThisSession('low-stock:org1')).toBe(true)
    expect(onceThisSession('low-stock:org1')).toBe(false)
    expect(onceThisSession('low-stock:org2')).toBe(true)
  })
})

describe('confirm dialog wording', () => {
  it('uses the action word on a delete question, Confirm otherwise', () => {
    expect(defaultConfirmText('confirm', true, 'Delete "Rice"? This cannot be undone.')).toBe('Delete')
    expect(defaultConfirmText('confirm', true, 'Remove this image?')).toBe('Remove')
    expect(defaultConfirmText('confirm', true, 'Cancel this order?')).toBe('Confirm')
    expect(defaultConfirmText('confirm', false, 'Post this entry?')).toBe('Confirm')
    expect(defaultConfirmText('prompt', false, 'Reason')).toBe('Save')
    expect(defaultConfirmText('alert', false, 'Saved')).toBe('OK')
  })
})

describe('pop-up tagging', () => {
  it('marks Cancel buttons and nothing else', () => {
    const host = html('<div class="fixed inset-0"><div class="card"><button>Cancel</button><button>Save</button><button>Cancel order</button></div></div>')
    tagPopup(host.firstElementChild as HTMLElement)
    const roles = Array.from(host.querySelectorAll('button')).map((b) => b.dataset.kitRole ?? '')
    expect(roles).toEqual(['cancel', '', ''])
    host.remove()
  })
})
