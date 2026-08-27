/**
 * StockReportsPage — Phase 5 chart additions:
 *  • Availability tab: horizontal bar chart comparing qty_on_hand vs reorder level,
 *    colour-coded by status (green/amber/red). Immediately shows which products
 *    are at risk without reading every row.
 *  • Usage tab: horizontal bar chart of top products by units consumed.
 *    Answers "what am I selling the most of?" at a glance.
 *  • Valuation tab: donut (category breakdown) + horizontal bar (top 10 by value).
 *    Shows inventory concentration risk and capital allocation.
 */
import { useState, useEffect, useMemo } from 'react'
import {
  ClipboardCheck, BarChart2, ArrowLeftRight, AlertTriangle,
  CheckCircle, XCircle, TrendingDown, FileText, FileDown, Table2,
  Pencil, Check, X as XIcon, Loader2, Wallet, PieChart as PieIcon,
} from 'lucide-react'
import {
  BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts'
import { stockReportApi, inventoryApi, reportApi, urlToDataUrl } from '@/services/api'
import { useAuthStore } from '@/store/authStore'
import type { Organisation } from '@/types'
import toast from 'react-hot-toast'
import DateInput from '@/components/DateInput'
// @ts-ignore
import autoTable from 'jspdf-autotable'
import jsPDF from 'jspdf'
import { saveBlobFile } from '@/lib/saveBlobFile'

// Chart style constants — dark mode defaults (index.css overrides for light mode)
const axisTickStyle = { fill: '#94a3b8', fontSize: 11 }
const CHART_COLORS = ['#f97316', '#3b82f6', '#10b981', '#a855f7', '#f59e0b', '#06b6d4', '#ec4899', '#84cc16']
const trunc = (s: string, n = 16) => s?.length > n ? s.slice(0, n) + '…' : (s ?? '—')

type ReportTab = 'availability' | 'usage' | 'transfers' | 'stock_card' | 'valuation'

interface AvailabilityRow {
  id: string
  sku: string
  name: string
  category: string | null
  unit_of_measure: string
  quantity_on_hand: number
  min_safety_level: number
  max_safety_level: number | null
  reorder_quantity: number
  quantity_in_pack: number
  cost_price: number
  selling_price: number
  status: 'ok' | 'low' | 'out_of_stock' | 'overstocked'
  warehouses: { warehouse: string; qty: number }[]
}

interface UsageRow {
  id: string
  sku: string
  name: string
  unit_of_measure: string
  total_used: number
}

interface UsageTransaction {
  date: string
  product_name: string
  product_sku: string
  warehouse: string
  quantity: number
  unit_cost: string
  invoice_no: string
  customer: string
  batch_number: string
  sold_by: string
  notes: string
}

interface TransferRow {
  id: string
  date: string
  movement_type: string
  movement_label: string
  product_name: string
  product_sku: string
  warehouse: string
  quantity: number
  unit_cost: string
  reference: string
  supplier: string
  batch_number: string
  batch_expiry: string
  received_by: string
  notes: string
}

interface StockCardRow {
  date: string
  warehouse: string
  in: number | null
  out: number | null
  balance: number
  unit_cost: string
  invoice_no: string
  batch_number: string
  remark: string
  created_by: string
}

interface ValuationItem {
  product: string
  sku: string
  warehouse: string
  quantity: number
  unit_cost: number
  total_value: number
}

interface ValuationReport {
  total_inventory_value: number
  items: ValuationItem[]
}

const STATUS_BADGE: Record<string, string> = {
  ok: 'badge-green',
  low: 'badge-amber',
  out_of_stock: 'badge-red',
  overstocked: 'badge-blue',
}

const STATUS_LABEL: Record<string, string> = {
  ok: 'In Stock',
  low: 'Low Stock',
  out_of_stock: 'Out of Stock',
  overstocked: 'Overstocked',
}

const MOVEMENT_LABEL: Record<string, string> = {
  purchase: 'Purchase',
  purchase_in: 'Purchase In',
  transfer_in: 'Transfer In',
  transfer_out: 'Transfer Out',
  sale_out: 'Sale Out',
  adjustment_in: 'Adjustment In',
  adjustment_out: 'Adjustment Out',
}

// ── Export helpers ─────────────────────────────────────────────────────────────

async function exportCSV(headers: string[], rows: (string | number | null)[][], filename: string) {
  const csv = [headers, ...rows]
    .map((r) => r.map((v) => `"${String(v ?? '').replace(/"/g, '""')}"`).join(','))
    .join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  await saveBlobFile(blob, filename)
}

function buildDocBase(org?: Organisation | null) {
  const hexToRgb = (hex?: string): [number,number,number] => {
    const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex ?? '')
    if (!m) return [249, 115, 22]; return [parseInt(m[1],16), parseInt(m[2],16), parseInt(m[3],16)]
  }
  return {
    BRAND: hexToRgb(org?.brand_color) as [number,number,number],
    tmpl:  org?.invoice_template ?? 'classic',
    displayName: org?.invoice_company_name?.trim() || org?.name || 'Audity',
    orgAddress: org?.address,
    orgEmail: org?.email,
    orgPhone: org?.phone,
    pdfFont: (org?.company_name_font?.toLowerCase().includes('times') ? 'times'
      : org?.company_name_font?.toLowerCase().includes('courier') ? 'courier' : 'helvetica') as string,
    isBold:   org?.company_name_font_bold !== false,
    isItalic: org?.company_name_font_italic === true,
    fontSize: Math.max(8, Math.min(36, org?.company_name_font_size ?? 12)),
    nameColor: ((): [number,number,number] => {
      const tmpl_ = org?.invoice_template ?? 'classic'
      const c = org?.company_name_font_color
      if (!c || c === '#ffffff') return (tmpl_ === 'modern' || tmpl_ === 'minimal') ? [22,22,30] : [255,255,255]
      const m2 = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(c ?? '')
      if (!m2) return [22,22,30]; return [parseInt(m2[1],16), parseInt(m2[2],16), parseInt(m2[3],16)]
    })(),
    showCompanyName: org?.show_company_name_on_pdf !== false,
    companyFontUnderline: org?.company_name_font_underline ?? false,
  }
}

async function exportAvailabilityPDF(rows: AvailabilityRow[], org?: Organisation | null) {
  const { applyDocHeader, buildTableStyle, addDocFooter, COLORS, TYPE } = await import('@/lib/pdfUtils')
  const base = buildDocBase(org)
  const { BRAND, tmpl, displayName, orgAddress, orgEmail, orgPhone, pdfFont } = base
  const DARK = COLORS.DARK; const MUTED = COLORS.MUTED
  let logoData: string | null = null
  const _storedLogo = useAuthStore.getState().logoDataUrl
  if (_storedLogo) { logoData = _storedLogo }
  else if (org?.logo) { try { logoData = await urlToDataUrl(org.logo) } catch { /* skip */ } }
  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  doc.setLineHeightFactor(1.15)
  const pageW = doc.internal.pageSize.getWidth()
  const exportedAt = new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
  const y = applyDocHeader(doc, {
    tmpl, pageW, BRAND, DARK, MUTED, logoData, displayName, orgAddress, orgEmail, orgPhone, pdfFont,
    fontSize: base.fontSize, pdfStyle: base.isBold ? 'bold' : 'normal', nameColor: base.nameColor,
    showCompanyName: base.showCompanyName, companyFontUnderline: base.companyFontUnderline,
    docTitle: 'STOCK AVAILABILITY',
    metaRows: [['Exported', exportedAt]],
  })
  const ts = buildTableStyle(BRAND, pdfFont)
  autoTable(doc, {
    ...ts,
    startY: y,
    head: [['SKU', 'Product', 'Unit', 'On Hand', 'Min', 'Max', 'Qty/Pack', 'Status']],
    body: rows.map((r) => [r.sku, r.name, r.unit_of_measure, r.quantity_on_hand, r.min_safety_level, r.max_safety_level ?? '—', r.quantity_in_pack, STATUS_LABEL[r.status]]),
    columnStyles: {
      0: { cellWidth: 22 },
      3: { halign: 'right' as const },
      4: { halign: 'right' as const },
      5: { halign: 'right' as const },
      6: { halign: 'right' as const },
      7: { cellWidth: 22 },
    },
    didParseCell: (data: any) => {
      if (data.section === 'body' && data.column.index === 7) {
        const status = rows[data.row.index]?.status
        if (status === 'low')          data.cell.styles.textColor = COLORS.AMBER
        else if (status === 'out_of_stock') data.cell.styles.textColor = COLORS.RED
        else if (status === 'ok')      data.cell.styles.textColor = COLORS.GREEN
      }
    },
  })
  const finalY = (doc as any).lastAutoTable.finalY + 4
  doc.setFontSize(TYPE.TINY.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
  doc.text(`Report generated by Audity  ·  ${exportedAt}`, 14, finalY)
  addDocFooter(doc, { orgName: displayName, docTitle: 'STOCK AVAILABILITY', BRAND, pdfFont })
  await saveBlobFile(doc.output('blob'), 'stock-availability.pdf')
}

async function exportAvailabilityCSV(rows: AvailabilityRow[]) {
  await exportCSV(
    ['SKU', 'Product', 'Unit', 'On Hand', 'Min Level', 'Max Level', 'Qty/Pack', 'Status'],
    rows.map((r) => [r.sku, r.name, r.unit_of_measure, r.quantity_on_hand, r.min_safety_level, r.max_safety_level ?? '', r.quantity_in_pack, STATUS_LABEL[r.status]]),
    'stock-availability.csv'
  )
}

async function exportUsagePDF(rows: UsageRow[], txRows: UsageTransaction[], org?: Organisation | null) {
  const { applyDocHeader, buildTableStyle, addDocFooter, COLORS, TYPE } = await import('@/lib/pdfUtils')
  const base = buildDocBase(org)
  const { BRAND, tmpl, displayName, orgAddress, orgEmail, orgPhone, pdfFont } = base
  const DARK = COLORS.DARK; const MUTED = COLORS.MUTED
  let logoData: string | null = null
  const _storedLogo = useAuthStore.getState().logoDataUrl
  if (_storedLogo) { logoData = _storedLogo }
  else if (org?.logo) { try { logoData = await urlToDataUrl(org.logo) } catch { /* skip */ } }
  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  doc.setLineHeightFactor(1.15)
  const pageW = doc.internal.pageSize.getWidth()
  const exportedAt = new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
  let y = applyDocHeader(doc, {
    tmpl, pageW, BRAND, DARK, MUTED, logoData, displayName, orgAddress, orgEmail, orgPhone, pdfFont,
    fontSize: base.fontSize, pdfStyle: base.isBold ? 'bold' : 'normal', nameColor: base.nameColor,
    showCompanyName: base.showCompanyName, companyFontUnderline: base.companyFontUnderline,
    docTitle: 'STOCK USAGE REPORT',
    metaRows: [['Exported', exportedAt]],
  })
  const ts = buildTableStyle(BRAND, pdfFont)
  autoTable(doc, {
    ...ts,
    startY: y,
    head: [['#', 'SKU', 'Product', 'Unit', 'Total Used']],
    body: rows.map((r, i) => [i + 1, r.sku, r.name, r.unit_of_measure, r.total_used]),
    columnStyles: {
      0: { cellWidth: 8,  halign: 'center' as const },
      1: { cellWidth: 24 },
      4: { halign: 'right' as const, cellWidth: 22 },
    },
  })
  if (txRows.length > 0) {
    y = (doc as any).lastAutoTable.finalY + 6
    doc.setFontSize(TYPE.H3.size); doc.setFont(pdfFont, 'bold'); doc.setTextColor(...DARK)
    doc.text('Transaction Breakdown', 14, y)
    y += 4
    autoTable(doc, {
      ...ts,
      startY: y,
      head: [['Date', 'Product', 'Warehouse', 'Qty', 'Unit Cost', 'Invoice', 'Customer', 'Batch', 'Sold By']],
      body: txRows.map((r) => [r.date, r.product_name, r.warehouse, r.quantity, r.unit_cost || '—', r.invoice_no || '—', r.customer || '—', r.batch_number || '—', r.sold_by || '—']),
      styles: { ...ts.styles, fontSize: 7 },
      headStyles: { ...ts.headStyles, fontSize: 6.5 },
    })
  }
  const finalY = (doc as any).lastAutoTable.finalY + 4
  doc.setFontSize(TYPE.TINY.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
  doc.text(`Report generated by Audity  ·  ${exportedAt}`, 14, finalY)
  addDocFooter(doc, { orgName: displayName, docTitle: 'STOCK USAGE REPORT', BRAND, pdfFont })
  await saveBlobFile(doc.output('blob'), 'stock-usage.pdf')
}

async function exportUsageCSV(rows: UsageRow[], txRows: UsageTransaction[]) {
  await exportCSV(['SKU', 'Product', 'Unit', 'Total Used'], rows.map((r) => [r.sku, r.name, r.unit_of_measure, r.total_used]), 'stock-usage-summary.csv')
  if (txRows.length > 0) {
    await exportCSV(
      ['Date', 'Product', 'SKU', 'Warehouse', 'Qty', 'Unit Cost', 'Invoice No', 'Customer', 'Batch', 'Sold By', 'Notes'],
      txRows.map((r) => [r.date, r.product_name, r.product_sku, r.warehouse, r.quantity, r.unit_cost, r.invoice_no, r.customer, r.batch_number, r.sold_by, r.notes]),
      'stock-usage-transactions.csv'
    )
  }
}

async function exportTransfersPDF(rows: TransferRow[], org?: Organisation | null) {
  const { applyDocHeader, buildTableStyle, addDocFooter, COLORS, TYPE } = await import('@/lib/pdfUtils')
  const base = buildDocBase(org)
  const { BRAND, tmpl, displayName, orgAddress, orgEmail, orgPhone, pdfFont } = base
  const DARK = COLORS.DARK; const MUTED = COLORS.MUTED
  let logoData: string | null = null
  const _storedLogo = useAuthStore.getState().logoDataUrl
  if (_storedLogo) { logoData = _storedLogo }
  else if (org?.logo) { try { logoData = await urlToDataUrl(org.logo) } catch { /* skip */ } }
  const doc = new jsPDF({ unit: 'mm', format: 'a4', orientation: 'landscape' })
  doc.setLineHeightFactor(1.15)
  const pageW = doc.internal.pageSize.getWidth()
  const exportedAt = new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
  const y = applyDocHeader(doc, {
    tmpl, pageW, BRAND, DARK, MUTED, logoData, displayName, orgAddress, orgEmail, orgPhone, pdfFont,
    landscape: true,
    fontSize: base.fontSize, pdfStyle: base.isBold ? 'bold' : 'normal', nameColor: base.nameColor,
    showCompanyName: base.showCompanyName, companyFontUnderline: base.companyFontUnderline,
    docTitle: 'STOCK TRANSFER & RECEIPT REPORT',
    metaRows: [['Exported', exportedAt]],
  })
  const ts = buildTableStyle(BRAND, pdfFont, { landscape: true })
  autoTable(doc, {
    ...ts,
    startY: y,
    head: [['Date', 'Type', 'Product', 'SKU', 'Warehouse', 'Qty', 'Unit Cost', 'Supplier', 'Batch', 'Expiry', 'Reference', 'Recv. By', 'Notes']],
    body: rows.map((r) => [r.date, r.movement_label || r.movement_type, r.product_name, r.product_sku, r.warehouse, r.quantity, r.unit_cost || '—', r.supplier || '—', r.batch_number || '—', r.batch_expiry || '—', r.reference || '—', r.received_by || '—', r.notes || '']),
    styles: { ...ts.styles, fontSize: 7 },
    headStyles: { ...ts.headStyles, fontSize: 6.5 },
    columnStyles: {
      0: { cellWidth: 18 },
      1: { cellWidth: 20 },
      5: { halign: 'right' as const, cellWidth: 10 },
      6: { halign: 'right' as const, cellWidth: 22 },
    },
  })
  const finalY = (doc as any).lastAutoTable.finalY + 4
  doc.setFontSize(TYPE.TINY.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
  doc.text(`Report generated by Audity  ·  ${exportedAt}`, 10, finalY)
  addDocFooter(doc, { orgName: displayName, docTitle: 'STOCK TRANSFERS', BRAND, pdfFont, landscape: true })
  await saveBlobFile(doc.output('blob'), 'stock-transfers.pdf')
}

async function exportTransfersCSV(rows: TransferRow[]) {
  await exportCSV(
    ['Date', 'Type', 'Product', 'SKU', 'Warehouse', 'Qty', 'Unit Cost', 'Supplier', 'Batch No', 'Batch Expiry', 'Reference', 'Received By', 'Notes'],
    rows.map((r) => [r.date, r.movement_label || r.movement_type, r.product_name, r.product_sku, r.warehouse, r.quantity, r.unit_cost, r.supplier, r.batch_number, r.batch_expiry, r.reference, r.received_by, r.notes]),
    'stock-transfers.csv'
  )
}

async function exportStockCardPDF(rows: StockCardRow[], productName: string, productSku: string, org?: Organisation | null) {
  const { applyDocHeader, buildTableStyle, addDocFooter, COLORS, TYPE } = await import('@/lib/pdfUtils')
  const base = buildDocBase(org)
  const { BRAND, tmpl, displayName, orgAddress, orgEmail, orgPhone, pdfFont } = base
  const DARK = COLORS.DARK; const MUTED = COLORS.MUTED
  let logoData: string | null = null
  const _storedLogo = useAuthStore.getState().logoDataUrl
  if (_storedLogo) { logoData = _storedLogo }
  else if (org?.logo) { try { logoData = await urlToDataUrl(org.logo) } catch { /* skip */ } }
  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  doc.setLineHeightFactor(1.15)
  const pageW = doc.internal.pageSize.getWidth()
  const exportedAt = new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
  const y = applyDocHeader(doc, {
    tmpl, pageW, BRAND, DARK, MUTED, logoData, displayName, orgAddress, orgEmail, orgPhone, pdfFont,
    fontSize: base.fontSize, pdfStyle: base.isBold ? 'bold' : 'normal', nameColor: base.nameColor,
    showCompanyName: base.showCompanyName, companyFontUnderline: base.companyFontUnderline,
    docTitle: 'STOCK CARD',
    metaRows: [['Product', productName], ['SKU', productSku], ['Exported', exportedAt]],
  })
  const ts = buildTableStyle(BRAND, pdfFont)
  autoTable(doc, {
    ...ts,
    startY: y,
    head: [['Date', 'Warehouse', 'IN', 'OUT', 'BALANCE', 'Unit Cost', 'Invoice No', 'Batch', 'Remark', 'By']],
    body: rows.map((r) => [r.date, r.warehouse, r.in ?? '', r.out ?? '', r.balance, r.unit_cost || '—', r.invoice_no, r.batch_number || '—', r.remark, r.created_by]),
    columnStyles: {
      2: { halign: 'right' as const, cellWidth: 14 },
      3: { halign: 'right' as const, cellWidth: 14 },
      4: { halign: 'right' as const, cellWidth: 16, fontStyle: 'bold' as const },
      5: { halign: 'right' as const, cellWidth: 22 },
    },
  })
  const finalY = (doc as any).lastAutoTable.finalY + 4
  doc.setFontSize(TYPE.TINY.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
  doc.text(`Report generated by Audity  ·  ${exportedAt}`, 14, finalY)
  addDocFooter(doc, { orgName: displayName, docTitle: 'STOCK CARD', docRef: productSku, BRAND, pdfFont })
  await saveBlobFile(doc.output('blob'), `stock-card-${productSku}.pdf`)
}

async function exportStockCardCSV(rows: StockCardRow[], productSku: string) {
  await exportCSV(
    ['Date', 'Warehouse', 'IN', 'OUT', 'BALANCE', 'Unit Cost', 'Invoice No', 'Batch No', 'Remark', 'By'],
    rows.map((r) => [r.date, r.warehouse, r.in ?? '', r.out ?? '', r.balance, r.unit_cost, r.invoice_no, r.batch_number, r.remark, r.created_by]),
    `stock-card-${productSku}.csv`
  )
}

function formatMoney(v: number | string) {
  const n = typeof v === 'number' ? v : parseFloat(String(v))
  return isNaN(n) ? '—' : `₦${n.toLocaleString('en-NG', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

async function exportValuationPDF(report: ValuationReport, org?: Organisation | null) {
  const { applyDocHeader, buildTableStyle, addDocFooter, COLORS, TYPE } = await import('@/lib/pdfUtils')
  const base = buildDocBase(org)
  const { BRAND, tmpl, displayName, orgAddress, orgEmail, orgPhone, pdfFont } = base
  const DARK = COLORS.DARK; const MUTED = COLORS.MUTED
  let logoData: string | null = null
  const _storedLogo = useAuthStore.getState().logoDataUrl
  if (_storedLogo) { logoData = _storedLogo }
  else if (org?.logo) { try { logoData = await urlToDataUrl(org.logo) } catch { /* skip */ } }
  const doc = new jsPDF({ unit: 'mm', format: 'a4' })
  doc.setLineHeightFactor(1.15)
  const pageW = doc.internal.pageSize.getWidth()
  const exportedAt = new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
  const y = applyDocHeader(doc, {
    tmpl, pageW, BRAND, DARK, MUTED, logoData, displayName, orgAddress, orgEmail, orgPhone, pdfFont,
    fontSize: base.fontSize, pdfStyle: base.isBold ? 'bold' : 'normal', nameColor: base.nameColor,
    showCompanyName: base.showCompanyName, companyFontUnderline: base.companyFontUnderline,
    docTitle: 'INVENTORY VALUATION',
    metaRows: [
      ['As of',       exportedAt],
      ['Total Value', formatMoney(report.total_inventory_value)],
    ],
  })
  const ts = buildTableStyle(BRAND, pdfFont)
  autoTable(doc, {
    ...ts,
    startY: y,
    head: [['Product', 'SKU', 'Warehouse', 'Qty', 'Unit Cost', 'Total Value']],
    body: report.items.map((r) => [
      r.product, r.sku, r.warehouse, r.quantity,
      Number(r.unit_cost).toFixed(2), Number(r.total_value).toFixed(2),
    ]),
    columnStyles: {
      3: { halign: 'right' as const, cellWidth: 16 },
      4: { halign: 'right' as const, cellWidth: 28 },
      5: { halign: 'right' as const, cellWidth: 28, fontStyle: 'bold' as const },
    },
  })
  const finalY = (doc as any).lastAutoTable.finalY + 4
  doc.setFontSize(TYPE.TINY.size); doc.setFont(pdfFont, 'normal'); doc.setTextColor(...MUTED)
  doc.text(`Report generated by Audity  ·  ${exportedAt}`, 14, finalY)
  addDocFooter(doc, { orgName: displayName, docTitle: 'INVENTORY VALUATION', BRAND, pdfFont })
  await saveBlobFile(doc.output('blob'), 'inventory-valuation.pdf')
}

async function exportValuationCSV(report: ValuationReport) {
  await exportCSV(
    ['Product', 'SKU', 'Warehouse', 'Qty On Hand', 'Unit Cost', 'Total Value'],
    report.items.map((r) => [r.product, r.sku, r.warehouse, r.quantity, r.unit_cost, r.total_value]),
    'inventory-valuation.csv',
  )
}

// ── Excel export helpers (using xlsx) ─────────────────────────────────────────

async function exportExcel(
  sheetName: string,
  headers: string[],
  rows: (string | number | null)[][],
  filename: string,
) {
  const XLSX = await import('xlsx')
  const ws = XLSX.utils.aoa_to_sheet([headers, ...rows])
  const wb = XLSX.utils.book_new()
  XLSX.utils.book_append_sheet(wb, ws, sheetName)
  const buf = XLSX.write(wb, { bookType: 'xlsx', type: 'array' })
  const blob = new Blob([buf], {
    type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  })
  await saveBlobFile(blob, filename)
}

async function exportAvailabilityExcel(rows: AvailabilityRow[]) {
  await exportExcel(
    'Stock Availability',
    ['SKU', 'Product', 'Unit', 'On Hand', 'Min Level', 'Max Level', 'Qty/Pack', 'Status'],
    rows.map((r) => [r.sku, r.name, r.unit_of_measure, r.quantity_on_hand, r.min_safety_level, r.max_safety_level ?? '', r.quantity_in_pack, STATUS_LABEL[r.status]]),
    'stock-availability.xlsx',
  )
}

async function exportUsageExcel(rows: UsageRow[], txRows: UsageTransaction[]) {
  const XLSX = await import('xlsx')
  const wb = XLSX.utils.book_new()
  const ws1 = XLSX.utils.aoa_to_sheet([
    ['SKU', 'Product', 'Unit', 'Total Used'],
    ...rows.map((r) => [r.sku, r.name, r.unit_of_measure, r.total_used]),
  ])
  XLSX.utils.book_append_sheet(wb, ws1, 'Summary')
  if (txRows.length > 0) {
    const ws2 = XLSX.utils.aoa_to_sheet([
      ['Date', 'Product', 'SKU', 'Warehouse', 'Qty', 'Unit Cost', 'Invoice No', 'Customer', 'Batch', 'Sold By', 'Notes'],
      ...txRows.map((r) => [r.date, r.product_name, r.product_sku, r.warehouse, r.quantity, r.unit_cost, r.invoice_no, r.customer, r.batch_number, r.sold_by, r.notes]),
    ])
    XLSX.utils.book_append_sheet(wb, ws2, 'Transactions')
  }
  const buf = XLSX.write(wb, { bookType: 'xlsx', type: 'array' })
  await saveBlobFile(new Blob([buf], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' }), 'stock-usage.xlsx')
}

async function exportTransfersExcel(rows: TransferRow[]) {
  await exportExcel(
    'Stock Transfers',
    ['Date', 'Type', 'Product', 'SKU', 'Warehouse', 'Qty', 'Unit Cost', 'Supplier', 'Batch No', 'Expiry', 'Reference', 'Received By', 'Notes'],
    rows.map((r) => [r.date, r.movement_label || r.movement_type, r.product_name, r.product_sku, r.warehouse, r.quantity, r.unit_cost, r.supplier, r.batch_number, r.batch_expiry, r.reference, r.received_by, r.notes]),
    'stock-transfers.xlsx',
  )
}

async function exportStockCardExcel(rows: StockCardRow[], productSku: string) {
  await exportExcel(
    'Stock Card',
    ['Date', 'Warehouse', 'IN', 'OUT', 'BALANCE', 'Unit Cost', 'Invoice No', 'Batch No', 'Remark', 'By'],
    rows.map((r) => [r.date, r.warehouse, r.in ?? '', r.out ?? '', r.balance, r.unit_cost, r.invoice_no, r.batch_number, r.remark, r.created_by]),
    `stock-card-${productSku}.xlsx`,
  )
}

async function exportValuationExcel(report: ValuationReport) {
  await exportExcel(
    'Inventory Valuation',
    ['Product', 'SKU', 'Warehouse', 'Qty On Hand', 'Unit Cost', 'Total Value'],
    report.items.map((r) => [r.product, r.sku, r.warehouse, r.quantity, r.unit_cost, r.total_value]),
    'inventory-valuation.xlsx',
  )
}

// ──────────────────────────────────────────────────────────────────────────────

export default function StockReportsPage() {
  const { organisation } = useAuthStore()

  // ── Theme detection ──────────────────────────────────────────────────────────
  const [isLight, setIsLight] = useState(() =>
    typeof document !== 'undefined' && document.documentElement.classList.contains('light')
  )
  useEffect(() => {
    const h = (e: Event) => setIsLight((e as CustomEvent).detail === 'light')
    window.addEventListener('themechange', h)
    return () => window.removeEventListener('themechange', h)
  }, [])

  // Chart styles derived from theme
  const tooltipStyle = isLight
    ? { backgroundColor: '#0f2347', border: '1px solid #1C2F5C', borderRadius: '12px', color: '#f1f5f9', fontSize: 12 }
    : { backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '12px', color: '#f1f5f9', fontSize: 12 }
  const chartGrid   = isLight ? '#cbd5e1' : '#334155'
  // Reorder level bar: white-ish in dark mode, deep navy in light mode
  const reorderFill  = isLight ? '#1e3a5f' : '#cbd5e1'
  const legendColor  = isLight ? '#334155' : '#94a3b8'
  // ─────────────────────────────────────────────────────────────────────────────

  const [tab, setTab] = useState<ReportTab>('availability')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [loading, setLoading] = useState(false)
  const [loaded, setLoaded] = useState(false)

  const [availability, setAvailability] = useState<AvailabilityRow[]>([])
  const [usage, setUsage] = useState<UsageRow[]>([])
  const [usageTransactions, setUsageTransactions] = useState<UsageTransaction[]>([])
  const [showUsageTx, setShowUsageTx] = useState(false)
  const [transfers, setTransfers] = useState<TransferRow[]>([])
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editVals, setEditVals] = useState<{ min: string; max: string; qty_per_pack: string }>({ min: '', max: '', qty_per_pack: '' })
  const [saving, setSaving] = useState(false)

  // Valuation state (auto-loaded, no date range)
  const [valuation, setValuation] = useState<ValuationReport | null>(null)
  const [valuationLoading, setValuationLoading] = useState(false)

  // Stock card state
  const [cardProduct, setCardProduct] = useState('')
  const [cardRows, setCardRows] = useState<StockCardRow[]>([])
  const [cardProductName, setCardProductName] = useState('')
  const [cardProductSku, setCardProductSku] = useState('')
  const [products, setProducts] = useState<{ id: string; name: string; sku: string }[]>([])

  useEffect(() => {
    const fetchProds = () => {
      inventoryApi.products({ page_size: 500, is_active: true }).then(({ data }) => {
        const list = (data.results ?? data) as { id: string; name: string; sku: string }[]
        setProducts(list)   // always update — even if empty so dropdown stays accurate
      }).catch(() => {})
    }
    fetchProds()
    window.addEventListener('online', fetchProds)
    return () => window.removeEventListener('online', fetchProds)
  }, [])

  useEffect(() => {
    if (tab !== 'valuation') return
    // Always reload on tab switch so data stays fresh
    setValuationLoading(true)
    reportApi.inventory()
      .then(({ data }) => setValuation(data as ValuationReport))
      .catch(() => toast.error('Failed to load inventory valuation'))
      .finally(() => setValuationLoading(false))
  }, [tab])

  const toISO = (dd: string) => {
    if (!dd) return ''
    const [d, m, y] = dd.split('/')
    if (!d || !m || !y) return dd
    return `${y}-${m}-${d}`
  }

  const runReport = async () => {
    setLoading(true)
    setLoaded(false)
    try {
      const params: Record<string, string> = {}
      if (dateFrom) params.date_from = toISO(dateFrom)
      if (dateTo) params.date_to = toISO(dateTo)

      if (tab === 'availability') {
        const { data } = await stockReportApi.availability(params)
        setAvailability(data)
      } else if (tab === 'usage') {
        const { data } = await stockReportApi.usage(params)
        setUsage(data.summary ?? data)
        setUsageTransactions(data.transactions ?? [])
        setShowUsageTx(false)
      } else if (tab === 'transfers') {
        const { data } = await stockReportApi.transfers(params)
        setTransfers(data)
      } else {
        if (!cardProduct) { toast.error('Select a product first'); setLoading(false); return }
        const { data } = await stockReportApi.stockCard({ ...params, product_id: cardProduct })
        setCardRows(data.rows)
        setCardProductName(data.product.name)
        setCardProductSku(data.product.sku)
      }
      setLoaded(true)
    } catch {
      toast.error('Failed to load report')
    } finally {
      setLoading(false)
    }
  }

  const handleTabChange = (t: ReportTab) => {
    setTab(t)
    setLoaded(false)
    setStatusFilter('all')
    setEditingId(null)
  }

  const startEdit = (row: AvailabilityRow) => {
    setEditingId(row.id)
    setEditVals({
      min: String(row.min_safety_level),
      max: row.max_safety_level != null ? String(row.max_safety_level) : '',
      qty_per_pack: String(row.quantity_in_pack),
    })
  }

  const saveEdit = async (row: AvailabilityRow) => {
    setSaving(true)
    try {
      const payload: Record<string, unknown> = { reorder_level: parseInt(editVals.min) || 0, quantity_in_pack: parseFloat(editVals.qty_per_pack) || 1 }
      if (editVals.max !== '') payload.max_stock_level = parseInt(editVals.max)
      else payload.max_stock_level = null
      await inventoryApi.updateProduct(row.id, payload)
      setAvailability((prev) => prev.map((r) => r.id === row.id ? {
        ...r,
        min_safety_level: parseInt(editVals.min) || 0,
        max_safety_level: editVals.max !== '' ? parseInt(editVals.max) : null,
        quantity_in_pack: parseFloat(editVals.qty_per_pack) || 1,
      } : r))
      setEditingId(null)
      toast.success('Product updated')
    } catch {
      toast.error('Failed to update product')
    } finally {
      setSaving(false)
    }
  }

  const stats = {
    ok: availability.filter((r) => r.status === 'ok').length,
    low: availability.filter((r) => r.status === 'low').length,
    out: availability.filter((r) => r.status === 'out_of_stock').length,
    over: availability.filter((r) => r.status === 'overstocked').length,
  }
  const filteredAvailability =
    statusFilter === 'all' ? availability : availability.filter((r) => r.status === statusFilter)

  /**
   * Phase 5: Availability bar chart — top 20 products sorted by qty_on_hand.
   * Each bar is split into qty_on_hand (coloured by status) vs reorder threshold.
   */
  const availabilityChartData = useMemo(() =>
    [...availability]
      .sort((a, b) => b.quantity_on_hand - a.quantity_on_hand)
      .slice(0, 20)
      .map(r => ({
        name:    trunc(r.name, 14),
        onHand:  r.quantity_on_hand,
        reorder: r.min_safety_level,
        status:  r.status,
      })),
  [availability])

  /**
   * Phase 5: Usage bar chart — top 15 products by total units consumed.
   */
  const usageChartData = useMemo(() =>
    [...usage]
      .sort((a, b) => b.total_used - a.total_used)
      .slice(0, 15)
      .map(u => ({ name: trunc(u.name, 14), units: u.total_used })),
  [usage])

  /**
   * Phase 5: Valuation donut — group items by product name (summing across
   * warehouses) then take the top 8 by total value + aggregate the rest as "Other".
   */
  const valuationChartData = useMemo(() => {
    if (!valuation) return { donut: [], topBar: [] }
    // Aggregate by product name
    const byProduct: Record<string, number> = {}
    for (const item of valuation.items) {
      byProduct[item.product] = (byProduct[item.product] ?? 0) + item.total_value
    }
    const sorted = Object.entries(byProduct)
      .sort(([, a], [, b]) => b - a)
    const top8  = sorted.slice(0, 8)
    const other = sorted.slice(8).reduce((s, [, v]) => s + v, 0)
    const donut = [
      ...top8.map(([name, value]) => ({ name: trunc(name, 14), value })),
      ...(other > 0 ? [{ name: 'Other', value: other }] : []),
    ]
    const topBar = top8.slice(0, 10).map(([name, value]) => ({ name: trunc(name, 16), value }))
    return { donut, topBar }
  }, [valuation])

  const TABS: { id: ReportTab; label: string; icon: React.ElementType }[] = [
    { id: 'availability', label: 'Stock Availability', icon: ClipboardCheck },
    { id: 'usage', label: 'Usage Report', icon: BarChart2 },
    { id: 'transfers', label: 'Transfer Report', icon: ArrowLeftRight },
    { id: 'stock_card', label: 'Stock Card', icon: FileText },
    { id: 'valuation', label: 'Inventory Value', icon: Wallet },
  ]

  const ExportBar = ({
    onPDF, onCSV, onExcel,
  }: { onPDF: () => void; onCSV: () => void; onExcel?: () => void }) => (
    <div className="flex gap-2">
      <button onClick={onPDF} className="btn-ghost text-xs flex items-center gap-1.5 py-1.5 px-3">
        <FileDown size={14} /> PDF
      </button>
      {onExcel && (
        <button onClick={onExcel} className="btn-ghost text-xs flex items-center gap-1.5 py-1.5 px-3">
          <Table2 size={14} /> Excel
        </button>
      )}
      <button onClick={onCSV} className="btn-ghost text-xs flex items-center gap-1.5 py-1.5 px-3">
        <Table2 size={14} /> CSV
      </button>
    </div>
  )

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-xl font-bold text-white flex items-center gap-2">
          <ClipboardCheck size={20} className="text-brand-400" />
          Stock Reports
        </h1>
        <p className="text-sm text-slate-400 mt-0.5">
          Availability, usage, transfer history, and stock card. Use date range to backdate reports.
        </p>
      </div>

      {/* Tab bar */}
      <div className="flex flex-wrap gap-1 bg-surface-800 border border-surface-700 rounded-xl p-1 w-fit">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => handleTabChange(t.id)}
            className={[
              'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all',
              tab === t.id
                ? 'bg-brand-500 text-white shadow'
                : 'text-slate-400 hover:text-slate-200',
            ].join(' ')}
          >
            <t.icon size={15} />
            {t.label}
          </button>
        ))}
      </div>

      {/* Date controls — hidden for valuation tab (point-in-time snapshot) */}
      {tab !== 'valuation' && <div className="card flex flex-wrap items-end gap-4">
        {tab === 'stock_card' && (
          <div className="w-full sm:w-64">
            <label className="label">Product</label>
            <select className="input" value={cardProduct} onChange={(e) => setCardProduct(e.target.value)}>
              <option value="">— Select product —</option>
              {products.map((p) => (
                <option key={p.id} value={p.id}>{p.name} ({p.sku})</option>
              ))}
            </select>
          </div>
        )}
        <div>
          <label className="label">From</label>
          <DateInput value={dateFrom} onChange={setDateFrom} placeholder="DD/MM/YYYY" />
        </div>
        <div>
          <label className="label">To</label>
          <DateInput value={dateTo} onChange={setDateTo} placeholder="DD/MM/YYYY" />
        </div>
        <button
          onClick={runReport}
          disabled={loading}
          className="btn-primary flex items-center gap-2"
        >
          {loading ? 'Loading…' : 'Run Report'}
        </button>
        {loaded && tab === 'availability' && (
          <p className="text-xs text-slate-500 self-end pb-2">
            {availability.length} products
          </p>
        )}
      </div>}

      {/* Results */}
      {tab !== 'valuation' && !loaded && !loading && (
        <div className="card text-center py-12 text-slate-500 text-sm">
          {tab === 'stock_card' ? 'Select a product and click Run Report.' : 'Select a date range (optional) and click Run Report.'}
        </div>
      )}

      {tab !== 'valuation' && loading && (
        <div className="card text-center py-12 text-slate-400 text-sm">Loading…</div>
      )}

      {/* ── Availability ── */}
      {loaded && tab === 'availability' && (
        <div className="space-y-4">
          {/* Summary tiles */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: 'In Stock', value: stats.ok, icon: CheckCircle, color: 'text-emerald-400', filter: 'ok' },
              { label: 'Low Stock', value: stats.low, icon: AlertTriangle, color: 'text-amber-400', filter: 'low' },
              { label: 'Out of Stock', value: stats.out, icon: XCircle, color: 'text-red-400', filter: 'out_of_stock' },
              { label: 'Overstocked', value: stats.over, icon: TrendingDown, color: 'text-blue-400', filter: 'overstocked' },
            ].map((s) => (
              <button
                key={s.filter}
                onClick={() => setStatusFilter(statusFilter === s.filter ? 'all' : s.filter)}
                className={[
                  'card flex items-center gap-3 cursor-pointer hover:border-brand-500/40 transition-all text-left',
                  statusFilter === s.filter ? 'ring-2 ring-brand-500/50 border-brand-500/40' : '',
                ].join(' ')}
              >
                <s.icon size={20} className={s.color} />
                <div>
                  <p className="text-lg font-bold text-white">{s.value}</p>
                  <p className="text-xs text-slate-400">{s.label}</p>
                </div>
              </button>
            ))}
          </div>

          {/* Phase 5: Availability horizontal bar — qty on hand vs reorder level */}
          {availabilityChartData.length > 0 && (
            <div className="card p-5">
              <div className="flex items-center gap-2 mb-4">
                <BarChart2 size={17} className="text-brand-400" />
                <h2 className="text-sm font-semibold text-white">Stock Level vs Reorder Level (Top 20)</h2>
              </div>
              <ResponsiveContainer width="100%" height={Math.min(500, availabilityChartData.length * 28 + 40)}>
                <BarChart
                  layout="vertical"
                  data={availabilityChartData}
                  margin={{ top: 5, right: 60, left: 10, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke={chartGrid} />
                  <XAxis type="number" tick={axisTickStyle} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="name" tick={axisTickStyle}
                    axisLine={false} tickLine={false} width={100} />
                  <Tooltip
                    contentStyle={tooltipStyle}
                    labelStyle={{ color: '#94a3b8' }}
                    itemStyle={{ color: '#f1f5f9' }}
                    cursor={{ fill: isLight ? 'rgba(28,47,92,0.08)' : 'rgba(255,255,255,0.05)' }}
                  />
                  <Legend
                    content={() => (
                      <div style={{ display: 'flex', justifyContent: 'center', gap: 20, paddingTop: 10, fontSize: 11, color: legendColor }}>
                        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                          <span style={{ display: 'inline-block', width: 12, height: 12, borderRadius: 2, background: '#10b981' }} />
                          On Hand
                        </span>
                        <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                          <span style={{ display: 'inline-block', width: 12, height: 12, borderRadius: 2, background: reorderFill, opacity: 0.85 }} />
                          Reorder Level
                        </span>
                      </div>
                    )}
                  />
                  <Bar dataKey="onHand" name="On Hand" radius={[0, 4, 4, 0]}>
                    {availabilityChartData.map((entry, i) => (
                      <Cell
                        key={i}
                        fill={
                          entry.status === 'out_of_stock' ? '#ef4444'
                          : entry.status === 'low'        ? '#f59e0b'
                          : entry.status === 'overstocked' ? '#3b82f6'
                          : '#10b981'
                        }
                      />
                    ))}
                  </Bar>
                  <Bar dataKey="reorder" name="Reorder Level" fill={reorderFill} radius={[0, 4, 4, 0]} opacity={0.7} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          <div className="flex justify-end">
            <ExportBar
              onPDF={() => exportAvailabilityPDF(filteredAvailability, organisation)}
              onExcel={() => exportAvailabilityExcel(filteredAvailability)}
              onCSV={() => exportAvailabilityCSV(filteredAvailability)}
            />
          </div>

          {/* Table */}
          <div className="card overflow-x-auto p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-700 text-xs text-slate-400 uppercase tracking-wider">
                  <th className="px-4 py-3 text-left">SKU / Product</th>
                  <th className="px-4 py-3 text-right">On Hand</th>
                  <th className="px-4 py-3 text-right">Min Level</th>
                  <th className="px-4 py-3 text-right">Max Level</th>
                  <th className="px-4 py-3 text-right">Qty/Pack</th>
                  <th className="px-4 py-3 text-left">Warehouses</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3 text-center w-20"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-700/50">
                {filteredAvailability.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-slate-500">
                      No products match this filter.
                    </td>
                  </tr>
                ) : (
                  filteredAvailability.map((row) => {
                    const isEditing = editingId === row.id
                    return (
                    <tr key={row.id} className={`transition-colors ${isEditing ? 'bg-surface-700/50' : 'hover:bg-surface-700/30'}`}>
                      <td className="px-4 py-3">
                        <p className="font-medium text-white">{row.name}</p>
                        <p className="text-xs text-slate-500">{row.sku} · {row.unit_of_measure}</p>
                      </td>
                      <td className={[
                        'px-4 py-3 text-right font-bold',
                        row.status === 'out_of_stock' ? 'text-red-400' :
                        row.status === 'low' ? 'text-amber-400' : 'text-white',
                      ].join(' ')}>
                        {row.quantity_on_hand}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {isEditing ? (
                          <input type="number" className="input py-1 px-2 text-right w-20 text-sm" value={editVals.min} onChange={(e) => setEditVals((v) => ({ ...v, min: e.target.value }))} />
                        ) : (
                          <span className="text-slate-400">{row.min_safety_level}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {isEditing ? (
                          <input type="number" className="input py-1 px-2 text-right w-20 text-sm" placeholder="—" value={editVals.max} onChange={(e) => setEditVals((v) => ({ ...v, max: e.target.value }))} />
                        ) : (
                          <span className="text-slate-400">{row.max_safety_level ?? <span className="text-slate-600">—</span>}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {isEditing ? (
                          <input type="number" className="input py-1 px-2 text-right w-20 text-sm" value={editVals.qty_per_pack} onChange={(e) => setEditVals((v) => ({ ...v, qty_per_pack: e.target.value }))} />
                        ) : (
                          <span className="text-slate-400">{row.quantity_in_pack}</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {row.warehouses.length === 0 ? (
                          <span className="text-slate-600 text-xs">None</span>
                        ) : (
                          <div className="space-y-0.5">
                            {row.warehouses.map((w, i) => (
                              <p key={i} className="text-xs text-slate-400">
                                {w.warehouse}: <span className="text-slate-300">{w.qty}</span>
                              </p>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={STATUS_BADGE[row.status] + ' text-xs'}>
                          {STATUS_LABEL[row.status]}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-center">
                        {isEditing ? (
                          <div className="flex items-center gap-1 justify-center">
                            <button onClick={() => saveEdit(row)} disabled={saving} className="p-1 rounded hover:bg-emerald-500/20 text-emerald-400 disabled:opacity-50">
                              {saving ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />}
                            </button>
                            <button onClick={() => setEditingId(null)} className="p-1 rounded hover:bg-red-500/20 text-red-400">
                              <XIcon size={14} />
                            </button>
                          </div>
                        ) : (
                          <button onClick={() => startEdit(row)} className="p-1 rounded hover:bg-surface-600 text-slate-500 hover:text-slate-300">
                            <Pencil size={13} />
                          </button>
                        )}
                      </td>
                    </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Usage ── */}
      {loaded && tab === 'usage' && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex gap-2">
              <button
                onClick={() => setShowUsageTx(false)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${!showUsageTx ? 'bg-brand-500/20 text-brand-400 border border-brand-500/40' : 'text-slate-400 hover:bg-surface-700'}`}
              >Summary</button>
              <button
                onClick={() => setShowUsageTx(true)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${showUsageTx ? 'bg-brand-500/20 text-brand-400 border border-brand-500/40' : 'text-slate-400 hover:bg-surface-700'}`}
              >Transactions ({usageTransactions.length})</button>
            </div>
            <ExportBar
              onPDF={() => exportUsagePDF(usage, usageTransactions, organisation)}
              onExcel={() => exportUsageExcel(usage, usageTransactions)}
              onCSV={() => exportUsageCSV(usage, usageTransactions)}
            />
          </div>

          {/* Phase 5: Usage horizontal bar — top products by units consumed */}
          {!showUsageTx && usageChartData.length > 0 && (
            <div className="card p-5">
              <div className="flex items-center gap-2 mb-4">
                <BarChart2 size={17} className="text-brand-400" />
                <h2 className="text-sm font-semibold text-white">Top Products by Units Consumed</h2>
              </div>
              <ResponsiveContainer width="100%" height={Math.min(420, usageChartData.length * 28 + 40)}>
                <BarChart
                  layout="vertical"
                  data={usageChartData}
                  margin={{ top: 5, right: 40, left: 10, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" stroke={chartGrid} />
                  <XAxis type="number" tick={axisTickStyle} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="name" tick={axisTickStyle}
                    axisLine={false} tickLine={false} width={100} />
                  <Tooltip
                    contentStyle={tooltipStyle}
                    labelStyle={{ color: '#94a3b8' }}
                    itemStyle={{ color: '#f1f5f9' }}
                    formatter={(v: number) => [`${v.toLocaleString()} units`, 'Used']}
                    cursor={{ fill: isLight ? 'rgba(28,47,92,0.08)' : 'rgba(255,255,255,0.07)' }}
                  />
                  <Bar dataKey="units" name="Units Used" fill="#f97316" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {!showUsageTx ? (
            <div className="card overflow-x-auto p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-700 text-xs text-slate-400 uppercase tracking-wider">
                    <th className="px-4 py-3 text-left">#</th>
                    <th className="px-4 py-3 text-left">SKU / Product</th>
                    <th className="px-4 py-3 text-left">Unit</th>
                    <th className="px-4 py-3 text-right">Total Used</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-700/50">
                  {usage.length === 0 ? (
                    <tr><td colSpan={4} className="px-4 py-8 text-center text-slate-500">No sales movements in this period.</td></tr>
                  ) : usage.map((row, i) => (
                    <tr key={row.id} className="hover:bg-surface-700/30 transition-colors">
                      <td className="px-4 py-3 text-slate-600 text-xs">{i + 1}</td>
                      <td className="px-4 py-3"><p className="font-medium text-white">{row.name}</p><p className="text-xs text-slate-500">{row.sku}</p></td>
                      <td className="px-4 py-3 text-slate-400">{row.unit_of_measure}</td>
                      <td className="px-4 py-3 text-right font-bold text-white">{row.total_used}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="card overflow-x-auto p-0">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-surface-700 text-xs text-slate-400 uppercase tracking-wider">
                    <th className="px-4 py-3 text-left whitespace-nowrap">Date</th>
                    <th className="px-4 py-3 text-left">Product</th>
                    <th className="px-4 py-3 text-left">Warehouse</th>
                    <th className="px-4 py-3 text-right whitespace-nowrap">Qty</th>
                    <th className="px-4 py-3 text-right whitespace-nowrap">Unit Cost</th>
                    <th className="px-4 py-3 text-left whitespace-nowrap">Invoice</th>
                    <th className="px-4 py-3 text-left">Customer</th>
                    <th className="px-4 py-3 text-left">Batch</th>
                    <th className="px-4 py-3 text-left whitespace-nowrap">Sold By</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-700/50">
                  {usageTransactions.length === 0 ? (
                    <tr><td colSpan={9} className="px-4 py-8 text-center text-slate-500">No transactions in this period.</td></tr>
                  ) : usageTransactions.map((row, i) => (
                    <tr key={i} className="hover:bg-surface-700/30 transition-colors">
                      <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">{row.date}</td>
                      <td className="px-4 py-3"><p className="text-white text-xs font-medium">{row.product_name}</p><p className="text-slate-500 text-xs">{row.product_sku}</p></td>
                      <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">{row.warehouse}</td>
                      <td className="px-4 py-3 text-right font-semibold text-red-400 text-xs">{row.quantity}</td>
                      <td className="px-4 py-3 text-right text-slate-400 text-xs">{row.unit_cost || '—'}</td>
                      <td className="px-4 py-3 text-slate-400 text-xs font-mono">{row.invoice_no || '—'}</td>
                      <td className="px-4 py-3 text-slate-400 text-xs">{row.customer || <span className="text-slate-600">Walk-in</span>}</td>
                      <td className="px-4 py-3 text-slate-400 text-xs">{row.batch_number || '—'}</td>
                      <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">{row.sold_by || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ── Transfers ── */}
      {loaded && tab === 'transfers' && (
        <div className="space-y-3">
          <div className="flex justify-end">
            <ExportBar
              onPDF={() => exportTransfersPDF(transfers, organisation)}
              onExcel={() => exportTransfersExcel(transfers)}
              onCSV={() => exportTransfersCSV(transfers)}
            />
          </div>
          <div className="card overflow-x-auto p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-700 text-xs text-slate-400 uppercase tracking-wider">
                  <th className="px-4 py-3 text-left whitespace-nowrap">Date</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">Type</th>
                  <th className="px-4 py-3 text-left">Product</th>
                  <th className="px-4 py-3 text-left">Warehouse</th>
                  <th className="px-4 py-3 text-right whitespace-nowrap">Qty</th>
                  <th className="px-4 py-3 text-right whitespace-nowrap">Unit Cost</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">Supplier</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">Batch / Expiry</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">Reference</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">Received By</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-700/50">
                {transfers.length === 0 ? (
                  <tr><td colSpan={10} className="px-4 py-8 text-center text-slate-500">No stock transfers or receipts in this period.</td></tr>
                ) : transfers.map((row) => (
                  <tr key={row.id} className="hover:bg-surface-700/30 transition-colors">
                    <td className="px-4 py-3 text-slate-400 whitespace-nowrap text-xs">{row.date}</td>
                    <td className="px-4 py-3 whitespace-nowrap">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                        row.movement_type === 'purchase_in' ? 'bg-emerald-500/15 text-emerald-400'
                        : row.movement_type === 'transfer_in' ? 'bg-brand-500/15 text-brand-400'
                        : 'bg-amber-500/15 text-amber-400'
                      }`}>{row.movement_label || MOVEMENT_LABEL[row.movement_type] || row.movement_type}</span>
                    </td>
                    <td className="px-4 py-3 min-w-[140px]">
                      <p className="font-medium text-white text-xs">{row.product_name}</p>
                      <p className="text-xs text-slate-500">{row.product_sku}</p>
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">{row.warehouse}</td>
                    <td className="px-4 py-3 text-right font-bold text-white text-xs whitespace-nowrap">{row.quantity}</td>
                    <td className="px-4 py-3 text-right text-slate-400 text-xs whitespace-nowrap">{row.unit_cost || '—'}</td>
                    <td className="px-4 py-3 text-xs">
                      {row.supplier ? <span className="text-emerald-400">{row.supplier}</span> : <span className="text-slate-600">—</span>}
                    </td>
                    <td className="px-4 py-3 text-xs">
                      {row.batch_number ? (
                        <p className="text-slate-300">{row.batch_number}</p>
                      ) : null}
                      {row.batch_expiry ? <p className="text-slate-500 text-xs">{row.batch_expiry}</p> : (!row.batch_number && <span className="text-slate-600">—</span>)}
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs font-mono whitespace-nowrap">{row.reference || '—'}</td>
                    <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">{row.received_by || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Stock Card ── */}
      {loaded && tab === 'stock_card' && (
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <p className="text-sm font-semibold text-white">{cardProductName} <span className="text-slate-500 font-mono text-xs ml-1">{cardProductSku}</span></p>
            <ExportBar
              onPDF={() => exportStockCardPDF(cardRows, cardProductName, cardProductSku, organisation)}
              onExcel={() => exportStockCardExcel(cardRows, cardProductSku)}
              onCSV={() => exportStockCardCSV(cardRows, cardProductSku)}
            />
          </div>
          <div className="card overflow-x-auto p-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-700 text-xs text-slate-400 uppercase tracking-wider">
                  <th className="px-4 py-3 text-left whitespace-nowrap">Date</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">Warehouse</th>
                  <th className="px-4 py-3 text-right whitespace-nowrap text-emerald-400">IN</th>
                  <th className="px-4 py-3 text-right whitespace-nowrap text-red-400">OUT</th>
                  <th className="px-4 py-3 text-right whitespace-nowrap">Balance</th>
                  <th className="px-4 py-3 text-right whitespace-nowrap">Unit Cost</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">Invoice</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">Batch</th>
                  <th className="px-4 py-3 text-left">Remark</th>
                  <th className="px-4 py-3 text-left whitespace-nowrap">By</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-700/50">
                {cardRows.length === 0 ? (
                  <tr><td colSpan={10} className="px-4 py-8 text-center text-slate-500">No stock movements found for this product in the selected period.</td></tr>
                ) : cardRows.map((row, i) => (
                  <tr key={i} className="hover:bg-surface-700/30 transition-colors">
                    <td className="px-4 py-3 text-slate-400 whitespace-nowrap text-xs">{row.date}</td>
                    <td className="px-4 py-3 text-slate-400 text-xs whitespace-nowrap">{row.warehouse}</td>
                    <td className="px-4 py-3 text-right font-semibold text-emerald-400">
                      {row.in != null ? row.in : <span className="text-slate-700">—</span>}
                    </td>
                    <td className="px-4 py-3 text-right font-semibold text-red-400">
                      {row.out != null ? row.out : <span className="text-slate-700">—</span>}
                    </td>
                    <td className="px-4 py-3 text-right font-bold text-white">{row.balance}</td>
                    <td className="px-4 py-3 text-right text-slate-400 text-xs whitespace-nowrap">{row.unit_cost || '—'}</td>
                    <td className="px-4 py-3 text-slate-400 text-xs font-mono whitespace-nowrap">{row.invoice_no || '—'}</td>
                    <td className="px-4 py-3 text-slate-400 text-xs">{row.batch_number || '—'}</td>
                    <td className="px-4 py-3 text-slate-400 text-xs">{row.remark}</td>
                    <td className="px-4 py-3 text-slate-500 text-xs whitespace-nowrap">{row.created_by || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {cardRows.length > 0 && (
            <div className="card flex items-center justify-between py-3">
              <span className="text-sm text-slate-400">Closing Balance</span>
              <span className="text-lg font-bold text-white">{cardRows[cardRows.length - 1].balance}</span>
            </div>
          )}
        </div>
      )}

      {/* ── Inventory Valuation ── */}
      {tab === 'valuation' && (
        <div className="space-y-4">
          {valuationLoading ? (
            <div className="card text-center py-12">
              <Loader2 size={22} className="animate-spin mx-auto text-slate-500" />
            </div>
          ) : !valuation ? null : (
            <>
              {/* Summary strip */}
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                <div className="card py-3">
                  <p className="text-xs text-slate-500 mb-0.5">Total Inventory Value</p>
                  <p className="text-xl font-bold text-emerald-400">{formatMoney(valuation.total_inventory_value)}</p>
                </div>
                <div className="card py-3">
                  <p className="text-xs text-slate-500 mb-0.5">Product Lines</p>
                  <p className="text-xl font-bold text-white">
                    {new Set(valuation.items.map((i) => i.sku)).size}
                  </p>
                </div>
                <div className="card py-3">
                  <p className="text-xs text-slate-500 mb-0.5">Stock Records</p>
                  <p className="text-xl font-bold text-white">{valuation.items.length}</p>
                </div>
              </div>

              {/* Phase 5: Valuation donut + top-10 horizontal bar */}
              {(valuationChartData.donut.length > 0 || valuationChartData.topBar.length > 0) && (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

                  {/* Category (product) donut */}
                  <div className="card p-5">
                    <div className="flex items-center gap-2 mb-4">
                      <PieIcon size={17} className="text-brand-400" />
                      <h2 className="text-sm font-semibold text-white">Inventory Value by Product</h2>
                    </div>
                    <ResponsiveContainer width="100%" height={240}>
                      <PieChart>
                        <Pie data={valuationChartData.donut} cx="50%" cy="45%"
                          innerRadius={55} outerRadius={80} paddingAngle={3} dataKey="value">
                          {valuationChartData.donut.map((_, i) => (
                            <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                          ))}
                        </Pie>
                        <Tooltip contentStyle={tooltipStyle}
                          labelStyle={{ color: '#94a3b8' }} itemStyle={{ color: '#f1f5f9' }}
                          formatter={(v: number) => formatMoney(v)} />
                        <Legend
                          wrapperStyle={{ fontSize: 10, paddingTop: 6, color: legendColor }}
                          formatter={(v: string) => <span style={{ color: legendColor }}>{v}</span>}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>

                  {/* Top 10 by total value — horizontal bar */}
                  <div className="card p-5">
                    <div className="flex items-center gap-2 mb-4">
                      <BarChart2 size={17} className="text-emerald-400" />
                      <h2 className="text-sm font-semibold text-white">Top Products by Inventory Value</h2>
                    </div>
                    <ResponsiveContainer width="100%" height={240}>
                      <BarChart
                        layout="vertical"
                        data={valuationChartData.topBar}
                        margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke={chartGrid} />
                        <XAxis type="number" tick={axisTickStyle} axisLine={false} tickLine={false}
                          tickFormatter={v => formatMoney(v)} />
                        <YAxis type="category" dataKey="name" tick={axisTickStyle}
                          axisLine={false} tickLine={false} width={100} />
                        <Tooltip contentStyle={tooltipStyle}
                          labelStyle={{ color: '#94a3b8' }} itemStyle={{ color: '#f1f5f9' }}
                          formatter={(v: number) => [formatMoney(v), 'Value']}
                          cursor={{ fill: isLight ? 'rgba(28,47,92,0.08)' : 'rgba(255,255,255,0.05)' }}
                        />
                        <Bar dataKey="value" name="Inventory Value" fill="#10b981" radius={[0, 4, 4, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}

              {/* Export buttons */}
              <div className="flex justify-end">
                <ExportBar
                  onPDF={() => exportValuationPDF(valuation, organisation)}
                  onExcel={() => exportValuationExcel(valuation)}
                  onCSV={() => exportValuationCSV(valuation)}
                />
              </div>

              {/* Table */}
              <div className="card overflow-x-auto p-0">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-surface-700 text-xs text-slate-400 uppercase tracking-wider">
                      <th className="px-4 py-3 text-left">Product</th>
                      <th className="px-4 py-3 text-left">SKU</th>
                      <th className="px-4 py-3 text-left">Warehouse</th>
                      <th className="px-4 py-3 text-right">Qty On Hand</th>
                      <th className="px-4 py-3 text-right">Unit Cost</th>
                      <th className="px-4 py-3 text-right">Total Value</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-700/50">
                    {valuation.items.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="px-4 py-8 text-center text-slate-500">
                          No stock on hand.
                        </td>
                      </tr>
                    ) : (
                      valuation.items.map((row, i) => (
                        <tr key={i} className="hover:bg-surface-700/30 transition-colors">
                          <td className="px-4 py-3 font-medium text-white">{row.product}</td>
                          <td className="px-4 py-3 text-slate-400 font-mono text-xs">{row.sku}</td>
                          <td className="px-4 py-3 text-slate-400 text-xs">{row.warehouse}</td>
                          <td className="px-4 py-3 text-right font-semibold text-white tabular-nums">{row.quantity}</td>
                          <td className="px-4 py-3 text-right text-slate-300 tabular-nums">{formatMoney(row.unit_cost)}</td>
                          <td className="px-4 py-3 text-right font-semibold text-emerald-400 tabular-nums">{formatMoney(row.total_value)}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                  {valuation.items.length > 0 && (
                    <tfoot>
                      <tr className="border-t-2 border-surface-600 bg-surface-800">
                        <td colSpan={5} className="px-4 py-3 text-sm font-semibold text-slate-300 text-right">
                          Grand Total
                        </td>
                        <td className="px-4 py-3 text-right text-lg font-bold text-emerald-400 tabular-nums">
                          {formatMoney(valuation.total_inventory_value)}
                        </td>
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
