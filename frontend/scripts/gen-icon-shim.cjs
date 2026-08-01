/* Generates src/lib/lucide-shim.tsx — maps every lucide icon name used in the
   app to a Phosphor (duotone) equivalent. Validates each Phosphor target exists
   in the installed package before writing, so the build can't break on a typo. */
const fs = require('fs')
const path = require('path')
// Validate against the names declared in the package type defs (reliable across
// CJS/ESM interop) rather than a runtime require of the React module.
const dts = fs.readFileSync('node_modules/@phosphor-icons/react/dist/index.d.ts', 'utf8')
const phNames = new Set(
  [...dts.matchAll(/export \* from '\.\/csr\/([A-Za-z0-9]+)'/g)].map((m) => m[1]),
)
const Ph = null // unused

// lucide name -> phosphor name
const MAP = {
  Activity:'Pulse', AlertCircle:'WarningCircle', AlertTriangle:'Warning', Archive:'Archive',
  ArrowDownCircle:'ArrowCircleDown', ArrowLeft:'ArrowLeft', ArrowLeftRight:'ArrowsLeftRight',
  ArrowUpDown:'ArrowsDownUp', Ban:'Prohibit', BarChart3:'ChartBar', Bell:'Bell',
  BookMarked:'BookBookmark', BookOpen:'BookOpen', Bot:'Robot', Boxes:'Stack', Briefcase:'Briefcase',
  Building2:'Buildings', Calculator:'Calculator', Calendar:'Calendar', CalendarClock:'CalendarCheck',
  CalendarDays:'CalendarDots', Camera:'Camera', CheckCircle:'CheckCircle', CheckCircle2:'CheckCircle',
  ChevronDown:'CaretDown', ChevronRight:'CaretRight', ChevronUp:'CaretUp', ChevronsUpDown:'CaretUpDown',
  ChevronFirst:'CaretDoubleLeft', ChevronLast:'CaretDoubleRight', ChevronLeft:'CaretLeft',
  ClipboardList:'ClipboardText', Clock:'Clock', Coins:'Coins', Copy:'Copy', CreditCard:'CreditCard',
  DollarSign:'CurrencyDollar', Download:'DownloadSimple', Edit2:'PencilSimple', ExternalLink:'ArrowSquareOut',
  Eye:'Eye', EyeOff:'EyeSlash', FileBarChart2:'FileText', FileDown:'FileArrowDown', FileSpreadsheet:'FileXls',
  FileText:'FileText', Folder:'Folder', GitBranch:'GitBranch', Globe:'Globe', GraduationCap:'GraduationCap',
  HelpCircle:'Question', History:'ClockCounterClockwise', Home:'House', Info:'Info', Key:'Key', KeyRound:'Key',
  Landmark:'Bank', LandmarkIcon:'Bank', Layers:'StackSimple', Layout:'Layout', LayoutDashboard:'SquaresFour',
  LayoutGrid:'GridFour', Loader2:'CircleNotch', Lock:'Lock', LogOut:'SignOut', Mail:'Envelope', MapPin:'MapPin',
  Maximize2:'ArrowsOut', Menu:'List', MessageCircle:'ChatCircle', MessageSquare:'ChatText', Minimize2:'ArrowsIn',
  Minus:'Minus', MinusCircle:'MinusCircle', Moon:'Moon', Package:'Package', PackageCheck:'Package', Pencil:'PencilSimple', Phone:'Phone',
  PieChart:'ChartPie', Play:'Play', Plus:'Plus', Printer:'Printer', Receipt:'Receipt',
  Heart:'Heart', Share2:'ShareNetwork',
  RefreshCw:'ArrowsClockwise',
  RotateCcw:'ArrowCounterClockwise', Scale:'Scales', Search:'MagnifyingGlass', Send:'PaperPlaneTilt',
  Shield:'Shield', ShieldCheck:'ShieldCheck', ShoppingCart:'ShoppingCart', Sparkles:'Sparkle', Star:'Star',
  Sun:'Sun', Table2:'Table', Trash2:'Trash', TrendingDown:'TrendDown', TrendingUp:'TrendUp', Truck:'Truck',
  Unlock:'LockOpen', Upload:'UploadSimple', UploadCloud:'UploadSimple', User:'User', UserCheck:'UserCheck',
  UserPlus:'UserPlus', Users:'Users', UsersRound:'UsersThree', Wallet:'Wallet', Warehouse:'Warehouse',
  Wifi:'WifiHigh', WifiOff:'WifiSlash', X:'X', XCircle:'XCircle', Zap:'Lightning',
  // additional names found in multiline imports
  Banknote:'Money', ClipboardCheck:'ClipboardText', CheckSquare:'CheckSquare', Square:'Square',
  Check:'Check', FolderOpen:'FolderOpen', FolderPlus:'FolderPlus', ArrowUpRight:'ArrowUpRight',
  ArrowUpCircle:'ArrowCircleUp', BarChart2:'ChartBar', LockKeyhole:'LockKey', Gift:'Gift',
  Settings:'GearSix',
}

// fallbacks to try if the primary name is missing
const FALLBACK = {
  Pulse:['Activity','Heartbeat'], Layout:['Layout','SidebarSimple','Browsers'], UserCheck:['UserCheck','UserCircleCheck','UserCirclePlus'],
  StackSimple:['StackSimple','Stack'], CalendarDots:['CalendarDots','CalendarBlank','Calendar'],
  CaretUpDown:['CaretUpDown','ArrowsDownUp'], GridFour:['GridFour','SquaresFour'], FileXls:['FileXls','FileCsv','FileText'],
  Warehouse:['Warehouse','Factory','Garage'], ChatText:['ChatText','ChatCircleText','Chat'],
}

// Scan all source files for lucide-react imports (handles multiline blocks).
function walk(dir, acc = []) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name)
    if (e.isDirectory()) walk(p, acc)
    else if (/\.(t|j)sx?$/.test(e.name)) acc.push(p)
  }
  return acc
}
const nameSet = new Set()
for (const file of walk('src')) {
  const src = fs.readFileSync(file, 'utf8')
  for (const m of src.matchAll(/import\s*\{([^{}]*?)\}\s*from\s*['"]lucide-react['"]/g)) {
    for (const raw of m[1].split(',')) {
      const n = raw.replace(/\s+as\s+\w+/g, '').replace(/\/\/.*$/gm, '').trim()
      if (n && /^[A-Z]/.test(n)) nameSet.add(n)
    }
  }
}
const names = [...nameSet].sort()
const exportsSet = phNames
const lines = []
const used = new Set()
const missing = []

function resolve(target){
  if (exportsSet.has(target)) return target
  for (const alt of (FALLBACK[target]||[])) if (exportsSet.has(alt)) return alt
  return null
}

for (const lucide of names){
  const target = MAP[lucide]
  if (!target){ missing.push(`${lucide} (no mapping)`); continue }
  const resolved = resolve(target)
  if (!resolved){ missing.push(`${lucide} -> ${target} (not in phosphor)`); continue }
  used.add(resolved)
  // Reference the aliased named import so the bundler can tree-shake. Each
  // phosphor icon is imported once as _<Name>.
  lines.push(`export const ${lucide} = mk(_${resolved})`)
}

if (missing.length){
  console.error('MISSING / UNRESOLVED:\n' + missing.join('\n'))
  process.exit(1)
}

// Named, aliased imports → only the icons actually used get bundled (no
// `import * as` which would pull in all ~1500 phosphor icons and bloat the build).
const importLine =
  'import {\n' +
  [...used].sort().map((n) => `  ${n} as _${n},`).join('\n') +
  "\n} from '@phosphor-icons/react'"

const header = `/* AUTO-GENERATED by scripts/gen-icon-shim.cjs — do not edit by hand.
 * Drop-in replacement for 'lucide-react': every icon name the app uses, backed
 * by Phosphor duotone icons recolored via currentColor. Aliased in vite.config
 * and tsconfig so existing  import { X } from 'lucide-react'  keeps working.
 * Uses explicit named imports so the bundle only includes icons in use. */
import { forwardRef, type ComponentType } from 'react'
import type { Icon, IconProps } from '@phosphor-icons/react'
${importLine}

export type LucideProps = Omit<IconProps, 'weight'> & {
  size?: number | string
  strokeWidth?: number          // accepted & ignored (lucide compat)
  absoluteStrokeWidth?: boolean // accepted & ignored
  weight?: IconProps['weight']
}

export type LucideIcon = ComponentType<LucideProps>

function mk(Cmp: Icon) {
  const Wrapped = forwardRef<SVGSVGElement, LucideProps>(
    ({ strokeWidth: _sw, absoluteStrokeWidth: _asw, weight, ...rest }, ref) => (
      <Cmp ref={ref} weight={weight ?? 'duotone'} {...rest} />
    ),
  )
  return Wrapped
}
`

fs.writeFileSync(path.join('src','lib','lucide-shim.tsx'), header + '\n' + lines.join('\n') + '\n')
console.log(`OK — wrote src/lib/lucide-shim.tsx with ${lines.length} icons (${used.size} unique phosphor).`)
