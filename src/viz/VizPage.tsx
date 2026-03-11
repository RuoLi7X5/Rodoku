import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import '../sudoku.css'
import { boardFromStateKey } from '../rodoku/boardFromStateKey'
import { RodokuBoard } from '../rodoku/RodokuBoard'
import type { Digit } from '../lib/sudoku'

type Metrics = {
  // 训练/评估曲线（可选）
  steps?: number[]
  solve_rate?: number[]
  stuck_rate?: number[]
  avg_steps?: number[]
  // 归因/贡献曲线（可选）
  step_axis?: number[]
  techlib_hits?: number[]
  rank_steps?: number[]
  ur_steps?: number[]
  basic_steps?: number[]
  deletions?: number[]
  // 参数向量（可选，用于雷达图/多边形）
  params?: { name: string; value: number; max?: number }[]
  // 结构统计（可选）
  structure_freq?: { name: string; count: number }[]
  techlib?: { items: TechItem[]; total: number }
  replay?: { stats?: { total_tail?: number; bytes?: number; last_ms?: number } }
  train?: {
    id: string
    status: string
    steps: number
    last_loss: number
    started_ms: number
    last_ms: number
    error?: string | null
    checkpoints?: string[]
  } | null
  train_hist?: Array<{ at_ms: number; step: number; loss: number; lr?: number }>
  replay_axis?: number[]
  cand_drop_cum?: number[]
  cand_drop_avg?: number[]
  forced_chain_cum?: number[]
  forced_chain_avg?: number[]
}

type TechItem = {
  id: string
  kind: string
  signature: string
  first_seen_ms: number
  seen_count: number
  display_name?: string
  aliases?: string[]
  tags?: string[]
  note?: string
  disabled?: boolean
  merged_from?: string[]
  examples?: Array<{
    puzzle: string
    snapshot_before: string
    snapshot_after: string
    rationale: string
    deletions: Array<{ idx: number; d: number }>
  }>
  features?: Record<string, any>
  example: {
    puzzle: string
    snapshot_before: string
    snapshot_after: string
    rationale: string
    deletions: Array<{ idx: number; d: number }>
  }
}

function clamp01(x: number) {
  if (!Number.isFinite(x)) return 0
  return Math.max(0, Math.min(1, x))
}

function LineChart({
  title,
  xs,
  ys,
  description,
  width = 520,
  height = 160,
}: {
  title: string
  xs: number[]
  ys: number[]
  description?: string
  width?: number
  height?: number
}) {
  // 关键：内部用固定坐标系（viewBox），外部用 100% 宽度自适应
  // 这样网格布局可以一行多列，不会被固定 width=520 撑成单列。
  const vw = width
  const vh = height
  const hasData = xs.length > 1 && ys.length > 1
  
  const pts = useMemo(() => {
    if (xs.length === 0 || ys.length === 0) return ''
    const n = Math.min(xs.length, ys.length)
    // 过滤无效值
    const validYs = ys.slice(0, n).filter(y => Number.isFinite(y))
    if (validYs.length === 0) return ''
    
    const yMin = Math.min(...validYs)
    const yMax = Math.max(...validYs)
    // 防止一直线无法归一化
    const range = yMax - yMin
    const safeRange = range === 0 ? 1.0 : range
    
    const dx = n <= 1 ? 0 : 1 / (n - 1)
    const normY = (y: number) => {
      if (!Number.isFinite(y)) return 0.5
      return (y - yMin) / safeRange
    }
    const path: string[] = []
    for (let i = 0; i < n; i++) {
      const x = 10 + (vw - 20) * (dx * i)
      const y = 10 + (vh - 20) * (1 - normY(ys[i]))
      if (Number.isFinite(y)) {
          path.push(`${i === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`)
      }
    }
    return path.join(' ')
  }, [xs, ys, vw, vh])

  return (
    <div className="panel" style={{ marginBottom: 10 }}>
      <div className="panelTitle">{title}</div>
      <div style={{ position: 'relative', height: vh }}>
        <svg
            viewBox={`0 0 ${vw} ${vh}`}
            width="100%"
            height={vh}
            style={{ display: 'block', background: '#fff', borderRadius: 10, border: '1px solid #eaecf0' }}
        >
            <path d={pts} fill="none" stroke="#175cd3" strokeWidth={2} />
        </svg>
        {!hasData && (
            <div style={{ 
                position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, 
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                background: 'rgba(255,255,255,0.6)', color: '#98a2b3', fontSize: 13
            }}>
                暂无足够数据 (N&lt;2)
            </div>
        )}
      </div>
      <div className="muted" style={{ marginTop: 6, minHeight: '1.5em' }}>
        {description || '暂无说明'}
      </div>
    </div>
  )
}

function RadarChart({ title, params, size = 260 }: { title: string; params: Metrics['params']; size?: number }) {
  const cx = size / 2
  const cy = size / 2
  const r = size * 0.38

  const poly = useMemo(() => {
    if (!params || params.length < 3) return ''
    const n = params.length
    const pts: string[] = []
    for (let i = 0; i < n; i++) {
      const a = (Math.PI * 2 * i) / n - Math.PI / 2
      const p = params[i]
      const max = p.max ?? 1
      const v = clamp01(max === 0 ? 0 : p.value / max)
      const x = cx + Math.cos(a) * r * v
      const y = cy + Math.sin(a) * r * v
      pts.push(`${x.toFixed(2)},${y.toFixed(2)}`)
    }
    return pts.join(' ')
  }, [params, cx, cy, r])

  return (
    <div className="panel" style={{ marginBottom: 10 }}>
      <div className="panelTitle">{title}</div>
      {!params || params.length < 3 ? (
        <div className="muted">暂无 params 数据（至少需要 3 个维度）。</div>
      ) : (
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <svg width={size} height={size} style={{ background: '#fff', borderRadius: 10, border: '1px solid #eaecf0' }}>
            <circle cx={cx} cy={cy} r={r} fill="none" stroke="#eaecf0" />
            <circle cx={cx} cy={cy} r={r * 0.66} fill="none" stroke="#eaecf0" />
            <circle cx={cx} cy={cy} r={r * 0.33} fill="none" stroke="#eaecf0" />
            <polygon points={poly} fill="rgba(105,65,198,0.18)" stroke="#6941c6" strokeWidth={2} />
          </svg>
          <div style={{ minWidth: 240 }}>
            {params.map((p) => (
              <div key={p.name} className="muted" style={{ marginBottom: 6 }}>
                {p.name}: {p.value}
                {p.max != null ? ` / ${p.max}` : ''}
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="muted" style={{ marginTop: 6 }}>
        目标：把“自动进化/策略权重/超参数”的变化以多边形（雷达图）或曲线展示；需要后端持续输出该向量。
      </div>
    </div>
  )
}

function idxToRC(idx: number) {
  const r = Math.floor(idx / 9) + 1
  const c = (idx % 9) + 1
  return { r, c }
}

function formatStructure(it: TechItem): string {
  const f = it.features ?? {}
  if (it.kind === 'UR1' && Array.isArray(f.rows) && Array.isArray(f.cols)) {
    const rs = f.rows.map((x: number) => x + 1).join('')
    const cs = f.cols.map((x: number) => x + 1).join('')
    return `r${rs}c${cs}（单元格矩形）`
  }
  if (it.kind === 'RANK') {
    const T = f.T ?? '?'
    const L = f.L ?? '?'
    const R = f.R ?? '?'
    return `Truth/Link/R 秩结构（T=${T}, L=${L}, R=${R}）`
  }
  return it.signature
}

function formatStructureMini(it: TechItem): string {
  const f = it.features ?? {}
  if (it.kind === 'UR1' && Array.isArray(f.rows) && Array.isArray(f.cols)) {
    const rs = f.rows.map((x: number) => x + 1).join('')
    const cs = f.cols.map((x: number) => x + 1).join('')
    return `r${rs}c${cs}`
  }
  if (it.kind === 'RANK') {
    const T = f.T ?? '?'
    const L = f.L ?? '?'
    const R = f.R ?? '?'
    return `T${T}L${L}R${R}`
  }
  return it.signature
}

function formatDeletionsMini(it: TechItem, limit = 3): string {
  const dels = it.example?.deletions ?? []
  if (dels.length === 0) return '-'
  const head = dels.slice(0, limit).map((x) => {
    const { r, c } = idxToRC(x.idx)
    return `r${r}c${c}<>${x.d}`
  })
  return `${head.join(' ')}${dels.length > limit ? ' …' : ''}`
}

function formatDateShort(ms: number): string {
  const d = new Date(ms)
  // YYYY-MM-DD（更紧凑，避免撑宽）
  return d.toISOString().slice(0, 10)
}

type RegionRef = {
  type: 'cell' | 'rowDigit' | 'colDigit' | 'boxDigit'
  idx?: number | null
  row?: number | null
  col?: number | null
  box?: number | null
  d?: number | null
}

function encodeRankRef(ref: RegionRef, opts: { asLink: boolean }): string {
  if (!ref || !ref.type) return 'unknown'
  if (ref.type === 'cell') {
    const idx = Number(ref.idx ?? -1)
    if (!Number.isFinite(idx) || idx < 0) return 'cell(?)'
    const { r, c } = idxToRC(idx)
    return `${r}${opts.asLink ? 'n' : 'N'}${c}`
  }
  const d = Number(ref.d ?? 0)
  if (ref.type === 'rowDigit') return `${d}${opts.asLink ? 'r' : 'R'}${Number(ref.row ?? 0) + 1}`
  if (ref.type === 'colDigit') return `${d}${opts.asLink ? 'c' : 'C'}${Number(ref.col ?? 0) + 1}`
  if (ref.type === 'boxDigit') return `${d}${opts.asLink ? 'b' : 'B'}${Number(ref.box ?? 0) + 1}`
  return String(ref.type)
}

function getRankLists(it: TechItem): { T: number | null; L: number | null; R: number | null; truths: RegionRef[]; links: RegionRef[] } {
  const f = it.features ?? {}
  const T = typeof f.T === 'number' ? f.T : null
  const L = typeof f.L === 'number' ? f.L : null
  const R = typeof f.R === 'number' ? f.R : null
  const truths = Array.isArray(f.truths) ? (f.truths as RegionRef[]) : []
  const links = Array.isArray(f.links) ? (f.links as RegionRef[]) : []
  return { T, L, R, truths, links }
}

type BoardOverlays = {
  cellMarks: Map<number, 'strong' | 'weak'>
  candidateMarks: Map<number, Map<Digit, string>>
}

const MARK_CLASSES = ['mk0', 'mk1', 'mk2', 'mk3', 'mk4', 'mk5', 'mk6', 'mk7'] as const

function idxFromRC(r: number, c: number) {
  return r * 9 + c
}

function boxCells(box: number): number[] {
  const br = Math.floor(box / 3) * 3
  const bc = (box % 3) * 3
  const out: number[] = []
  for (let dr = 0; dr < 3; dr++) for (let dc = 0; dc < 3; dc++) out.push(idxFromRC(br + dr, bc + dc))
  return out
}

function applyTruthCandidateSet(
  overlays: BoardOverlays,
  board: any,
  ref: RegionRef,
  colorClass: string
) {
  const d = Number(ref.d ?? 0) as Digit
  if (!(d >= 1 && d <= 9)) return
  let cells: number[] = []
  if (ref.type === 'rowDigit') cells = Array.from({ length: 9 }, (_, c) => idxFromRC(Number(ref.row ?? 0), c))
  else if (ref.type === 'colDigit') cells = Array.from({ length: 9 }, (_, r) => idxFromRC(r, Number(ref.col ?? 0)))
  else if (ref.type === 'boxDigit') cells = boxCells(Number(ref.box ?? 0))
  else return

  for (const idx of cells) {
    const cell = board[idx]
    if (!cell || cell.value !== 0) continue
    if (!cell.candidates?.[d]) continue
    let m = overlays.candidateMarks.get(idx)
    if (!m) {
      m = new Map()
      overlays.candidateMarks.set(idx, m)
    }
    // 同一格同一数字可能被多个 Truth 覆盖：保留第一个（更稳定/不闪烁）
    if (!m.has(d)) m.set(d, colorClass)
  }
}

function buildTechOverlays(it: TechItem, board: any): BoardOverlays {
  const overlays: BoardOverlays = { cellMarks: new Map(), candidateMarks: new Map() }

  // 先标记弱区域（再用强区域覆盖，强优先）
  if (it.kind === 'RANK') {
    const { truths, links } = getRankLists(it)
    for (const ref of links) {
      if (ref?.type === 'cell') {
        const idx = Number(ref.idx ?? -1)
        if (Number.isFinite(idx) && idx >= 0) overlays.cellMarks.set(idx, 'weak')
      }
    }
    truths.forEach((ref, i) => {
      const colorClass = MARK_CLASSES[i % MARK_CLASSES.length]
      if (ref?.type === 'cell') {
        const idx = Number(ref.idx ?? -1)
        if (Number.isFinite(idx) && idx >= 0) overlays.cellMarks.set(idx, 'strong')
      } else {
        // 强区域候选集合：给集合内候选打彩色小球标记
        applyTruthCandidateSet(overlays, board, ref, colorClass)
      }
    })
  } else if (it.kind === 'UR1') {
    const f = it.features ?? {}
    const rs = Array.isArray(f.rows) ? (f.rows as number[]) : []
    const cs = Array.isArray(f.cols) ? (f.cols as number[]) : []
    const ab = Array.isArray(f.ab) ? (f.ab as number[]) : []
    if (rs.length === 2 && cs.length === 2) {
      const idxs = [idxFromRC(rs[0], cs[0]), idxFromRC(rs[0], cs[1]), idxFromRC(rs[1], cs[0]), idxFromRC(rs[1], cs[1])]
      for (const idx of idxs) overlays.cellMarks.set(idx, 'strong')
      // 可读性增强：UR 常见两候选 ab，用两种颜色标记在这 4 格内出现的候选
      const d1 = Number(ab[0] ?? 0) as Digit
      const d2 = Number(ab[1] ?? 0) as Digit
      for (const idx of idxs) {
        const cell = board[idx]
        if (!cell || cell.value !== 0) continue
        if (d1 >= 1 && d1 <= 9 && cell.candidates?.[d1]) {
          let m = overlays.candidateMarks.get(idx)
          if (!m) overlays.candidateMarks.set(idx, (m = new Map()))
          m.set(d1, MARK_CLASSES[0])
        }
        if (d2 >= 1 && d2 <= 9 && cell.candidates?.[d2]) {
          let m = overlays.candidateMarks.get(idx)
          if (!m) overlays.candidateMarks.set(idx, (m = new Map()))
          m.set(d2, MARK_CLASSES[1])
        }
      }
    }
  }

  // 强覆盖弱：如果同一 idx 既弱又强，强优先（上面 truths 已覆盖 set）
  return overlays
}

function buildElimsMap(it: TechItem): Map<number, Set<Digit>> | undefined {
  const dels = it.example?.deletions ?? []
  if (!dels || dels.length === 0) return undefined
  const m = new Map<number, Set<Digit>>()
  for (const x of dels) {
    const idx = Number(x.idx)
    const d = Number(x.d) as Digit
    if (!Number.isFinite(idx) || idx < 0) continue
    if (!(d >= 1 && d <= 9)) continue
    const set = m.get(idx) ?? new Set<Digit>()
    set.add(d)
    m.set(idx, set)
  }
  return m.size ? m : undefined
}

function compressRefs(refs: RegionRef[], opts: { asLink: boolean }): string[] {
  // 合并同 digit 的多个 box（例如 6b6 + 6b8 => 6b68），其余保持逐条
  const out: string[] = []
  const boxMap = new Map<string, number[]>() // key: `${d}${b/B}`
  for (const r of refs) {
    if (r?.type === 'boxDigit') {
      const d = Number(r.d ?? 0)
      const key = `${d}${opts.asLink ? 'b' : 'B'}`
      const b = Number(r.box ?? -1) + 1
      if (!boxMap.has(key)) boxMap.set(key, [])
      boxMap.get(key)!.push(b)
    } else {
      out.push(encodeRankRef(r, opts))
    }
  }
  for (const [k, bs] of boxMap.entries()) {
    const uniq = Array.from(new Set(bs)).sort((a, b) => a - b)
    out.push(`${k}${uniq.join('')}`)
  }
  return out
}

function formatDeletions(it: TechItem): string {
  if (!it.example.deletions || it.example.deletions.length === 0) return '无'
  return it.example.deletions
    .map((x) => {
      const { r, c } = idxToRC(x.idx)
      return `r${r}c${c}<>${x.d}`
    })
    .join('，')
}

function formatPrincipleShort(it: TechItem): string {
  if (it.kind === 'UR1') return '致命结构（UR 唯一性）'
  if (it.kind === 'RANK') return '秩逻辑推理（Truth/Link/R）'
  return '逻辑推理'
}

export function VizPage() {
  const [text, setText] = useState<string>('')
  const [backendUrl, setBackendUrl] = useState<string>(() => {
    try {
      return localStorage.getItem('rodoku_backend_url') || 'http://127.0.0.1:8000'
    } catch {
      return 'http://127.0.0.1:8000'
    }
  })

  // ... (existing code)

  // 当 backendUrl 变化时，保存到 localStorage
  useEffect(() => {
    localStorage.setItem('rodoku_backend_url', backendUrl)
  }, [backendUrl])
  const [err, setErr] = useState<string>('')
  const [lastUpdatedMs, setLastUpdatedMs] = useState<number>(0)
  const [expandedTechId, setExpandedTechId] = useState<string | null>(null)
  const [lastViewedTechId, setLastViewedTechId] = useState<string | null>(null)
  const [techSort, setTechSort] = useState<'time_desc' | 'time_asc' | 'freq_desc' | 'freq_asc'>('time_desc')
  const [mergePick, setMergePick] = useState<Set<string>>(new Set())
  const [mergeMaster, setMergeMaster] = useState<string>('')
  const [editDraft, setEditDraft] = useState<Record<string, { display_name: string; tags: string; note: string; disabled: boolean }>>({})
  const [trainBusy, setTrainBusy] = useState<boolean>(false)
  const [trainMsg, setTrainMsg] = useState<string>('')
  const [autoSync, setAutoSync] = useState<boolean>(true)
  const [syncing, setSyncing] = useState<boolean>(false)
  const techScrollRef = useRef<HTMLDivElement | null>(null)
  const techRowRefMap = useRef<Map<string, HTMLTableRowElement>>(new Map())
  const anchorRef = useRef<{ id: string; scrollTop: number; rowTop: number } | null>(null)
  const syncingRef = useRef<boolean>(false)
  const metrics: Metrics | null = useMemo(() => {
    if (!text.trim()) return null
    try {
      const obj = JSON.parse(text) as Metrics
      setErr('')
      return obj
    } catch (e) {
      setErr('JSON 解析失败：请粘贴后端输出的 metrics JSON')
      return null
    }
  }, [text])

  const cacheKey = useMemo(() => `rodoku_viz_cache:${backendUrl.replace(/\/$/, '')}`, [backendUrl])

  async function pullNow() {
    const base = backendUrl.replace(/\/$/, '')
    const m = await fetch(`${base}/metrics`).then((r) => r.json())
    const s = await fetch(`${base}/stats`).then((r) => r.json())
    const t = await fetch(`${base}/techlib`).then((r) => r.json())
    const merged = { ...m, ...s, techlib: t }
    setText(JSON.stringify(merged, null, 2))
    setErr('')
    const now = Date.now()
    setLastUpdatedMs(now)
    localStorage.setItem(cacheKey, JSON.stringify({ at: now, data: merged }))
  }

  async function exportLogs(opts?: { tail?: number; jobId?: string }) {
    const base = backendUrl.replace(/\/$/, '')
    const tail = Math.max(1, Math.min(20000, Number(opts?.tail ?? 6000)))
    const jobId = (opts?.jobId ?? '').trim()
    const qs = new URLSearchParams()
    qs.set('tail', String(tail))
    if (jobId) qs.set('job_id', jobId)
    const res = await fetch(`${base}/logs?${qs.toString()}`).then((r) => r.json())
    if (!res?.ok) throw new Error('导出失败')
    const jsonl = String(res.jsonl ?? '')
    const name = `rodoku_logs_${jobId ? `job-${jobId}_` : ''}${new Date().toISOString().replace(/[:.]/g, '-')}.jsonl`
    const blob = new Blob([jsonl], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = name
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
  }

  async function refreshTechlibOnly() {
    const base = backendUrl.replace(/\/$/, '')
    const m = await fetch(`${base}/metrics`).then((r) => r.json())
    const s = await fetch(`${base}/stats`).then((r) => r.json())
    const t = await fetch(`${base}/techlib`).then((r) => r.json())
    const merged = { ...m, ...s, techlib: t }
    setText(JSON.stringify(merged, null, 2))
    setErr('')
    const now = Date.now()
    setLastUpdatedMs(now)
    localStorage.setItem(cacheKey, JSON.stringify({ at: now, data: merged }))
  }

  // 刷新不丢：先从 localStorage 恢复，再尝试自动拉取
  useEffect(() => {
    try {
      const raw = localStorage.getItem(cacheKey)
      if (raw) {
        const obj = JSON.parse(raw) as { at: number; data: any }
        if (obj?.data) {
          setText(JSON.stringify(obj.data, null, 2))
          setLastUpdatedMs(Number(obj.at) || 0)
        }
      }
    } catch { }
    ; (async () => {
      try {
        await pullNow()
      } catch (e) {
        // 后端不可用时保留缓存并提示
        setErr(e instanceof Error ? e.message : String(e))
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cacheKey])

  // 自动实时同步：轮询拉取后端 metrics/stats/techlib
  useEffect(() => {
    if (!autoSync) return
    let cancelled = false
    const tick = async () => {
      if (cancelled) return
      if (document.visibilityState !== 'visible') return
      if (syncingRef.current) return
      syncingRef.current = true
      setSyncing(true)
      try {
        await pullNow()
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e))
      } finally {
        syncingRef.current = false
        setSyncing(false)
      }
    }
    // 立即拉一次 + 定时拉取
    tick()
    const t = window.setInterval(tick, 1200)
    return () => {
      cancelled = true
      window.clearInterval(t)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoSync, cacheKey])

  const techItemsSorted = useMemo(() => {
    const items = metrics?.techlib?.items ?? []
    const arr = items.slice()
    arr.sort((a, b) => {
      if (techSort === 'time_desc') return (b.first_seen_ms ?? 0) - (a.first_seen_ms ?? 0)
      if (techSort === 'time_asc') return (a.first_seen_ms ?? 0) - (b.first_seen_ms ?? 0)
      if (techSort === 'freq_desc') return (b.seen_count ?? 0) - (a.seen_count ?? 0)
      return (a.seen_count ?? 0) - (b.seen_count ?? 0)
    })
    return arr
  }, [metrics?.techlib?.items, techSort])

  // 展开/收起时保持视口不跳：根据“行的屏幕位置变化”补偿 scrollTop
  useLayoutEffect(() => {
    const a = anchorRef.current
    if (!a) return
    const wrap = techScrollRef.current
    const row = techRowRefMap.current.get(a.id)
    if (!wrap || !row) {
      anchorRef.current = null
      return
    }
    const newTop = row.getBoundingClientRect().top
    const delta = newTop - a.rowTop
    if (Number.isFinite(delta) && Math.abs(delta) > 0.5) {
      wrap.scrollTop = a.scrollTop + delta
    }
    anchorRef.current = null
  }, [expandedTechId])

  return (
    <div className="page">
      <div className="topBar">
        <div className="title">Rodoku 可视化（MVP）</div>
        <div className="muted">训练曲线 / 参数多边形 / 结构频率（后端输出数据后即可渲染）</div>
      </div>

      <main className="main" style={{ gridTemplateColumns: '1fr', alignItems: 'start' }}>
        {/* 顶部控制区：占满宽度，两列并排（窄屏自动换行），避免固定右侧列造成浪费 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 10, marginBottom: 10 }}>
          {/* 训练面板 */}
          <div className="panel">
            <div className="panelTitle">训练管线（replay / PyTorch）</div>
            <div className="muted" style={{ lineHeight: 1.6 }}>
              <div>
                <b>replay</b>：tail={metrics?.replay?.stats?.total_tail ?? 0} 行｜bytes={metrics?.replay?.stats?.bytes ?? 0}
              </div>
              <div>
                <b>train</b>：{metrics?.train ? `${metrics.train.status}｜steps=${metrics.train.steps}｜loss=${metrics.train.last_loss}` : '未启动'}
              </div>
              {metrics?.train?.checkpoints && metrics.train.checkpoints.length > 0 ? (
                <div>
                  <b>checkpoints</b>：{metrics.train.checkpoints.slice(0, 5).join(', ')}
                </div>
              ) : null}
              {metrics?.train?.error ? (
                <div style={{ color: '#b42318' }}>
                  <b>error</b>：{metrics.train.error}
                </div>
              ) : null}
            </div>
            <div className="row" style={{ gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
              <button
                type="button"
                className="smallBtn"
                disabled={trainBusy}
                onClick={async () => {
                  const base = backendUrl.replace(/\/$/, '')
                  try {
                    setTrainBusy(true)
                    setTrainMsg('正在启动训练…')
                    await fetch(`${base}/train/start`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'application/json' },
                      body: JSON.stringify({ batch_size: 32, lr: 3e-4, max_steps: 2000, ckpt_every: 300, mode: 'rl', gamma: 0.99 }),
                    })
                    await pullNow()
                    setTrainMsg('已发送启动请求（请观察 train.status/steps/loss 变化）')
                  } catch (e) {
                    setErr(e instanceof Error ? e.message : String(e))
                    setTrainMsg('启动失败（见 error）')
                  } finally {
                    setTrainBusy(false)
                  }
                }}
              >
                启动训练（RL）
              </button>
              <button
                type="button"
                className="smallBtn danger"
                disabled={trainBusy}
                onClick={async () => {
                  const base = backendUrl.replace(/\/$/, '')
                  try {
                    setTrainBusy(true)
                    setTrainMsg('正在停止训练…')
                    await fetch(`${base}/train/stop`, { method: 'POST' })
                    await pullNow()
                    setTrainMsg('已发送停止请求（请观察 train.status 变为 stopped）')
                  } catch (e) {
                    setErr(e instanceof Error ? e.message : String(e))
                    setTrainMsg('停止失败（见 error）')
                  } finally {
                    setTrainBusy(false)
                  }
                }}
              >
                停止训练
              </button>
            </div>
            {trainMsg ? <div className="muted" style={{ marginTop: 8 }}>{trainMsg}</div> : null}
            <div className="row" style={{ gap: 10, marginTop: 10, flexWrap: 'wrap', alignItems: 'center' }}>
              <span className="tag">同步</span>
              <label className="muted" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                <input type="checkbox" checked={autoSync} onChange={(e) => setAutoSync(e.target.checked)} />
                自动实时同步（刷题/训练进行时自动更新曲线与技巧库）
              </label>
              <span className="muted">{syncing ? '同步中…' : '空闲'}</span>
            </div>
            <div className="muted" style={{ marginTop: 8 }}>
              说明：当前训练为 RL-最小版（TD(0)+advantage），后续会升级到 PPO/DQN 并做更严格的 on-policy 采样与约束。
            </div>
          </div>

          {/* 拉取/输入面板 */}
          <div className="panel rankPane">
            <div className="panelTitle">数据拉取 / 输入</div>
            <div className="row" style={{ gap: 8, marginBottom: 8 }}>
              <span className="tag">后端</span>
              <input
                className="monoText"
                style={{ flex: 1, minWidth: 220, padding: '8px 10px' }}
                value={backendUrl}
                onChange={(e) => setBackendUrl(e.target.value)}
                placeholder="http://127.0.0.1:8000"
                spellCheck={false}
              />
              <button
                type="button"
                className="smallBtn"
                onClick={async () => {
                  try {
                    await pullNow()
                  } catch (e) {
                    setErr(e instanceof Error ? e.message : String(e))
                  }
                }}
              >
                拉取
              </button>
            </div>
            <div className="muted" style={{ marginBottom: 8 }}>
              {lastUpdatedMs ? (
                <span style={{ color: Date.now() - lastUpdatedMs > 60000 ? '#b42318' : undefined }}>
                  {Date.now() - lastUpdatedMs > 60000 ? '⚠️ 数据陈旧 (未连接) — ' : ''}
                  最近更新：{new Date(lastUpdatedMs).toLocaleString()}
                </span>
              ) : (
                '最近更新时间：无（等待拉取/恢复缓存）'
              )}
            </div>
            <textarea
              className="monoText"
              rows={10}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder='例如：{"steps":[0,1,2],"solve_rate":[0.1,0.2,0.3],"params":[{"name":"alpha","value":0.2,"max":1}]}'
              spellCheck={false}
            />
            {err ? <div className="error">{err}</div> : null}
          </div>
        </div>

        {/* 图表区：占满整屏宽度，用网格自动多列 */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 10 }}>
          <RadarChart title="策略/权重参数多维图" params={metrics?.params} />
          <LineChart
            title="Solve Rate"
            xs={metrics?.steps ?? []}
            ys={metrics?.solve_rate ?? []}
            description="近 3000 次求解的成功率走势（1.0 = 100%）。"
          />
          <LineChart
            title="Avg Steps"
            xs={metrics?.steps ?? []}
            ys={metrics?.avg_steps ?? []}
            description="成功求解的平均逻辑步数（越低越好，或代表题目变简单）。"
          />
          <LineChart
            title="技巧库命中（累计）"
            xs={metrics?.step_axis ?? []}
            ys={metrics?.techlib_hits ?? []}
            description="累计使用了多少次已归档的技巧结构。"
          />
          <LineChart
            title="结构步贡献 - rank（累计）"
            xs={metrics?.step_axis ?? []}
            ys={metrics?.rank_steps ?? []}
            description="Rank (Truth/Link) 秩逻辑步的累计贡献次数。"
          />
          <LineChart
            title="结构步贡献 - ur（累计）"
            xs={metrics?.step_axis ?? []}
            ys={metrics?.ur_steps ?? []}
            description="UR 唯一性致命结构（或陷阱规避）的累计贡献次数。"
          />
          <LineChart
            title="结构步贡献 - basic（累计）"
            xs={metrics?.step_axis ?? []}
            ys={metrics?.basic_steps ?? []}
            description="基础逻辑步（唯余/摒除等）的累计贡献次数。"
          />
          <LineChart
            title="累计删数（来自 solve_job）"
            xs={metrics?.step_axis ?? []}
            ys={metrics?.deletions ?? []}
            description="所有任务累计删除的候选数总量。"
          />
          <LineChart
            title="cand_drop（累计）"
            xs={metrics?.replay_axis ?? []}
            ys={metrics?.cand_drop_cum ?? []}
            description="Replay 训练数据中的候选数消除总量。"
          />
          <LineChart
            title="Train Loss（PyTorch）"
            xs={(metrics?.train_hist ?? []).map((x) => x.step)}
            ys={(metrics?.train_hist ?? []).map((x) => x.loss)}
            description="策略网络与价值网络的混合损失（越低越好）。反映 AI 预测动作和局面的准确度。"
          />
        </div>

        <div className="panel rankPane" style={{ marginTop: 10 }}>
          <div className="panelTitle">结构频率（Top）</div>
          {!metrics?.structure_freq || metrics.structure_freq.length === 0 ? (
            <div className="muted">暂无结构统计数据（先点击“拉取”或粘贴 JSON）。</div>
          ) : (
            <div style={{ maxHeight: 360, overflow: 'auto' }}>
              {metrics.structure_freq.slice(0, 50).map((x) => (
                <div key={x.name} className="muted" style={{ marginBottom: 6 }}>
                  {x.name}: {x.count}
                </div>
              ))}
            </div>
          )}
          <div className="muted" style={{ marginTop: 6 }}>
            目标：让 Rodoku “记忆强化”常见结构（例如 UR / 不同 TLR 的秩结构），形成自己的结构库与偏好。
          </div>
        </div>
      </main>

      {/* 技巧库放在页面下方，占满宽度，通过页面滚动查看 */}
      <div style={{ marginTop: 14 }}>
        <div className="panel">
          <div className="panelTitle">技巧库（首次见到的结构）</div>
          <div className="row" style={{ gap: 8, marginTop: 8, marginBottom: 8, flexWrap: 'wrap' }}>
            <span className="tag">排序</span>
            <select className="monoText" value={techSort} onChange={(e) => setTechSort(e.target.value as any)}>
              <option value="time_desc">时间（新 → 旧）</option>
              <option value="time_asc">时间（旧 → 新）</option>
              <option value="freq_desc">次数（多 → 少）</option>
              <option value="freq_asc">次数（少 → 多）</option>
            </select>
            <span className="tag">合并</span>
            <span className="muted">已选 {mergePick.size} 个</span>
            <select
              className="monoText"
              value={mergeMaster}
              onChange={(e) => setMergeMaster(e.target.value)}
              disabled={mergePick.size < 2}
              title="选择合并后的主技巧（master）"
            >
              <option value="">选择 master…</option>
              {Array.from(mergePick).map((id) => (
                <option key={id} value={id}>
                  {id}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="smallBtn"
              disabled={mergePick.size < 2 || !mergeMaster}
              onClick={async () => {
                const base = backendUrl.replace(/\/$/, '')
                const merge_ids = Array.from(mergePick).filter((x) => x !== mergeMaster)
                if (merge_ids.length === 0) return
                if (!window.confirm(`确认合并 ${merge_ids.length} 个技巧到 master=${mergeMaster} ?`)) return
                try {
                  await fetch(`${base}/techlib/merge`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ master_id: mergeMaster, merge_ids }),
                  })
                  setMergePick(new Set())
                  setMergeMaster('')
                  await refreshTechlibOnly()
                } catch (e) {
                  setErr(e instanceof Error ? e.message : String(e))
                }
              }}
            >
              合并
            </button>
            <button
              type="button"
              className="smallBtn danger"
              disabled={mergePick.size < 1}
              title="批量删除当前已勾选的技巧"
              onClick={async () => {
                const base = backendUrl.replace(/\/$/, '')
                const ids = Array.from(mergePick)
                if (ids.length === 0) return
                if (!window.confirm(`确认批量删除 ${ids.length} 条技巧？此操作不可恢复。`)) return
                try {
                  const results = await Promise.allSettled(
                    ids.map((id) => fetch(`${base}/techlib/${encodeURIComponent(id)}`, { method: 'DELETE' }))
                  )
                  const failed = results
                    .map((r, i) => ({ r, id: ids[i] }))
                    .filter((x) => x.r.status === 'rejected' || (x.r.status === 'fulfilled' && !x.r.value.ok))
                  // 如果当前展开项被删，收起
                  if (expandedTechId && ids.includes(expandedTechId)) setExpandedTechId(null)
                  setMergePick(new Set())
                  setMergeMaster('')
                  await refreshTechlibOnly()
                  if (failed.length > 0) {
                    setErr(`批量删除部分失败：${failed.slice(0, 6).map((x) => x.id).join(', ')}${failed.length > 6 ? '…' : ''}`)
                  }
                } catch (e) {
                  setErr(e instanceof Error ? e.message : String(e))
                }
              }}
            >
              批量删除
            </button>
          </div>
          <div className="row" style={{ gap: 8, marginBottom: 8, flexWrap: 'wrap', alignItems: 'center' }}>
            <span className="tag">日志</span>
            <button
              type="button"
              className="smallBtn"
              onClick={async () => {
                try {
                  await exportLogs({ tail: 6000 })
                } catch (e) {
                  setErr(e instanceof Error ? e.message : String(e))
                }
              }}
              title="下载最近 N 条事件日志（JSONL），包含 search heartbeat / step"
            >
              导出日志
            </button>
          </div>
          {!metrics?.techlib?.items || metrics.techlib.items.length === 0 ? (
            <div className="muted">暂无技巧库数据：先在 Rodoku 刷题跑几题，然后在本页点“拉取”。</div>
          ) : (
            <div
              ref={techScrollRef}
              style={{
                border: '1px solid #eaecf0',
                borderRadius: 12,
                overflowY: 'auto',
                overflowX: 'hidden',
                // 目标：窗口高度尽量接近视口高度（不改每行高度，只扩大滚动容器）
                height: 'calc(100vh - 120px)',
                background: '#fff',
              }}
            >
              <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
                <thead>
                  <tr style={{ textAlign: 'left', borderBottom: '1px solid #eaecf0' }}>
                    {(
                      [
                        { k: '选', w: 46 },
                        { k: '类型', w: 64 },
                        { k: '签名', w: 240 },
                        { k: '首次', w: 110 },
                        { k: '次', w: 64 },
                        { k: '删', w: 64 },
                        { k: '说明', w: undefined },
                        { k: '操作', w: 86 },
                      ] as const
                    ).map((x) => (
                      <th
                        key={x.k}
                        style={{
                          padding: '8px 10px',
                          width: x.w,
                          position: 'sticky',
                          top: 0,
                          background: '#fff',
                          zIndex: 4,
                          borderBottom: '1px solid #eaecf0',
                        }}
                      >
                        {x.k}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {techItemsSorted.flatMap((it) => {
                    const isOpen = expandedTechId === it.id
                    const rows: React.ReactNode[] = []
                    const checked = mergePick.has(it.id)
                    rows.push(
                      <tr
                        key={it.id}
                        ref={(el) => {
                          if (el) techRowRefMap.current.set(it.id, el)
                          else techRowRefMap.current.delete(it.id)
                        }}
                        style={{
                          borderBottom: '1px solid #f2f4f7',
                          background: isOpen ? '#eff8ff' : lastViewedTechId === it.id ? '#dbeafe' : undefined,
                        }}
                      >
                        <td style={{ padding: '8px 10px' }}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(e) => {
                              const next = new Set(mergePick)
                              if (e.target.checked) next.add(it.id)
                              else next.delete(it.id)
                              setMergePick(next)
                              if (!mergeMaster && e.target.checked) setMergeMaster(it.id)
                              if (mergeMaster === it.id && !e.target.checked) setMergeMaster('')
                            }}
                          />
                        </td>
                        <td style={{ padding: '8px 10px', whiteSpace: 'nowrap', fontWeight: 900 }}>{it.kind}</td>
                        <td style={{ padding: '8px 10px', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace' }}>
                          <button
                            type="button"
                            className="smallBtn"
                            style={{
                              textAlign: 'left',
                              display: 'block',
                              width: '100%',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                            title={it.display_name?.trim() ? it.display_name : it.signature}
                            onClick={() => {
                              const wrap = techScrollRef.current
                              const row = techRowRefMap.current.get(it.id)
                              if (wrap && row) {
                                anchorRef.current = { id: it.id, scrollTop: wrap.scrollTop, rowTop: row.getBoundingClientRect().top }
                              }
                              setExpandedTechId((prev) => {
                                const next = prev === it.id ? null : it.id
                                // 记住“刚收起/刚查看”的那一条，避免跳动后找不到
                                if (next === null) setLastViewedTechId(it.id)
                                else setLastViewedTechId(null)
                                return next
                              })
                            }}
                          >
                            {it.display_name?.trim() ? it.display_name : it.signature}
                          </button>
                        </td>
                        <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>
                          {formatDateShort(it.first_seen_ms)}
                        </td>
                        <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>{it.seen_count}</td>
                        <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>{it.example.deletions.length}</td>
                        <td style={{ padding: '8px 10px', minWidth: 0 }}>
                          <div className="muted" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {formatStructureMini(it)}｜{formatDeletionsMini(it)}
                          </div>
                        </td>
                        <td style={{ padding: '8px 10px', whiteSpace: 'nowrap' }}>
                          <button
                            type="button"
                            className="smallBtn danger"
                            onClick={async () => {
                              const base = backendUrl.replace(/\/$/, '')
                              if (!window.confirm(`确认删除技巧：${it.signature} ?`)) return
                              try {
                                await fetch(`${base}/techlib/${encodeURIComponent(it.id)}`, { method: 'DELETE' })
                                if (expandedTechId === it.id) setExpandedTechId(null)
                                await refreshTechlibOnly()
                              } catch (e) {
                                setErr(e instanceof Error ? e.message : String(e))
                              }
                            }}
                          >
                            删除
                          </button>
                        </td>
                      </tr>
                    )

                    if (isOpen) {
                      const draft = editDraft[it.id] ?? {
                        display_name: it.display_name ?? '',
                        tags: (it.tags ?? []).join(','),
                        note: it.note ?? '',
                        disabled: !!it.disabled,
                      }
                      rows.push(
                        <tr key={`${it.id}__detail`} style={{ background: '#f5fbff' }}>
                          <td colSpan={8} style={{ padding: 12, borderBottom: '1px solid #eaecf0' }}>
                            <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: 16, alignItems: 'start' }}>
                              <div style={{ display: 'grid', gap: 10 }}>
                                {(['before', 'after'] as const).map((k) => {
                                  const snap = k === 'before' ? it.example.snapshot_before : it.example.snapshot_after
                                  const b = boardFromStateKey(snap, it.example.puzzle)
                                  const overlays = b ? buildTechOverlays(it, b) : null
                                  const elims = k === 'after' ? buildElimsMap(it) : undefined
                                  return (
                                    <div key={k}>
                                      <div className="muted" style={{ marginBottom: 6 }}>
                                        {k}
                                      </div>
                                      {b ? (
                                        <div className="vizSnap">
                                          <RodokuBoard
                                            board={b}
                                            highlightElims={elims}
                                            cellMarks={overlays?.cellMarks}
                                            candidateMarks={overlays?.candidateMarks}
                                          />
                                        </div>
                                      ) : (
                                        <div className="muted">无法还原盘面</div>
                                      )}
                                    </div>
                                  )
                                })}
                              </div>

                              <div className="muted" style={{ lineHeight: 1.55, minWidth: 280 }}>
                                <div className="panel" style={{ padding: 10, marginBottom: 10 }}>
                                  <div style={{ fontWeight: 900, marginBottom: 6 }}>编辑技巧（手动维护）</div>
                                  <div className="row" style={{ gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                                    <span className="tag">名称</span>
                                    <input
                                      className="monoText"
                                      style={{ flex: 1, minWidth: 220, padding: '6px 8px' }}
                                      value={draft.display_name}
                                      onChange={(e) => {
                                        setEditDraft((prev) => ({ ...prev, [it.id]: { ...draft, display_name: e.target.value } }))
                                      }}
                                      placeholder="display_name（可选）"
                                    />
                                    <label className="muted" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                                      <input
                                        type="checkbox"
                                        checked={draft.disabled}
                                        onChange={(e) => setEditDraft((prev) => ({ ...prev, [it.id]: { ...draft, disabled: e.target.checked } }))}
                                      />
                                      禁用
                                    </label>
                                  </div>
                                  <div className="row" style={{ gap: 8, alignItems: 'center', marginTop: 8, flexWrap: 'wrap' }}>
                                    <span className="tag">标签</span>
                                    <input
                                      className="monoText"
                                      style={{ flex: 1, minWidth: 220, padding: '6px 8px' }}
                                      value={draft.tags}
                                      onChange={(e) => setEditDraft((prev) => ({ ...prev, [it.id]: { ...draft, tags: e.target.value } }))}
                                      placeholder="tags，用逗号分隔"
                                    />
                                  </div>
                                  <div style={{ marginTop: 8 }}>
                                    <textarea
                                      className="monoText"
                                      rows={3}
                                      value={draft.note}
                                      onChange={(e) => setEditDraft((prev) => ({ ...prev, [it.id]: { ...draft, note: e.target.value } }))}
                                      placeholder="备注（note）"
                                    />
                                  </div>
                                  <div className="row" style={{ gap: 8, marginTop: 8, alignItems: 'center' }}>
                                    <button
                                      type="button"
                                      className="smallBtn"
                                      onClick={async () => {
                                        const base = backendUrl.replace(/\/$/, '')
                                        try {
                                          await fetch(`${base}/techlib/${encodeURIComponent(it.id)}`, {
                                            method: 'PATCH',
                                            headers: { 'Content-Type': 'application/json' },
                                            body: JSON.stringify({
                                              display_name: draft.display_name,
                                              tags: draft.tags
                                                .split(',')
                                                .map((x) => x.trim())
                                                .filter(Boolean),
                                              note: draft.note,
                                              disabled: draft.disabled,
                                            }),
                                          })
                                          setEditDraft((prev) => {
                                            const n = { ...prev }
                                            delete n[it.id]
                                            return n
                                          })
                                          await refreshTechlibOnly()
                                        } catch (e) {
                                          setErr(e instanceof Error ? e.message : String(e))
                                        }
                                      }}
                                    >
                                      保存
                                    </button>
                                    {it.merged_from && it.merged_from.length > 0 ? (
                                      <div className="muted">已合并：{it.merged_from.join(', ')}</div>
                                    ) : null}
                                    {it.aliases && it.aliases.length > 0 ? <div className="muted">别名：{it.aliases.join(', ')}</div> : null}
                                  </div>
                                </div>
                                <div style={{ marginBottom: 8 }}>
                                  <div>
                                    <b>技巧结构：</b>
                                    {formatStructure(it)}。
                                  </div>
                                  <div>
                                    <b>删除候选：</b>
                                    {formatDeletions(it)}。
                                  </div>
                                  <div>
                                    <b>原理说明：</b>
                                    {formatPrincipleShort(it)}。
                                  </div>
                                </div>

                                {it.kind === 'RANK' ? (
                                  (() => {
                                    const rk = getRankLists(it)
                                    const T = rk.T ?? rk.truths.length
                                    const L = rk.L ?? rk.links.length
                                    const R = rk.R ?? null
                                    const truthList = rk.truths.length ? compressRefs(rk.truths, { asLink: false }) : []
                                    const linkList = rk.links.length ? compressRefs(rk.links, { asLink: true }) : []
                                    const truthText = truthList.length ? truthList.join('-') : '无'
                                    const linkText = linkList.length ? `{${linkList.join(' ')}}` : '无'
                                    return (
                                      <div style={{ marginBottom: 8 }}>
                                        <div>
                                          <b>T/L/R：</b>
                                          T={T}，L={L}，R={R ?? '未知'}
                                        </div>
                                        <div>
                                          <b>T{T}＝</b>
                                          {truthText}
                                        </div>
                                        <div>
                                          <b>L{L}＝</b>
                                          {linkText}
                                        </div>
                                        <div>
                                          <b>rank</b> {R ?? '未知'}
                                        </div>
                                      </div>
                                    )
                                  })()
                                ) : null}

                                <div>
                                  <b>详情说明：</b> {it.example.rationale}
                                </div>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )
                    }

                    return rows
                  })}
                </tbody>
              </table>

              {/* 底部占位：让滚动容器永远有足够余量，底部展开/收起不至于强行跳回 */}
              <div style={{ height: 220, display: 'grid', placeItems: 'center', color: '#98a2b3', fontWeight: 900 }}>
                rodoku
              </div>
            </div>
          )}
          <div className="muted" style={{ marginTop: 6 }}>
            说明：技巧库只记录“首次见到”的结构样例（before/after 快照 + 删数），后续只累加出现次数，用于记忆强化与频率统计。
          </div>
        </div>
      </div>
    </div>
  )
}

