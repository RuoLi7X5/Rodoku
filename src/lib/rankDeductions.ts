import type { Digit, Board } from './sudoku'
import { indexToRC, rcToIndex } from './sudoku'
import type { FoundStructure } from './rankSearch'
import { resolveGroup } from './rank'

export type CandidateMark = { idx: number; r: number; c: number; d: Digit }

function key(r: number, c: number, d: Digit): string {
  return `${r}${c}${d}`
}

export function computeDeletableCandidates(board: Board, s: FoundStructure): CandidateMark[] {
  // Truth candidates set
  const truth = new Set<string>()
  for (const t of s.truths) {
    for (const n of resolveGroup(board, t)) truth.add(key(n.r, n.c, n.d))
  }

  // Link coverage counts
  const linkCount = new Map<string, number>()
  for (const l of s.links) {
    for (const n of resolveGroup(board, l)) {
      const k = key(n.r, n.c, n.d)
      linkCount.set(k, (linkCount.get(k) ?? 0) + 1)
    }
  }

  const out: CandidateMark[] = []
  const R = s.R
  for (const [k, cnt] of linkCount.entries()) {
    // 统一删数规则（与你现在的解释一致）：
    // - 永远不删强区域覆盖到的候选（避免“把 Truth 自己删空/削弱”造成伪推理）
    // - R=0: 未被 Truth 覆盖 且 被任意 Link 覆盖 -> 可删（等价于 cnt>=1）
    // - R=1: 未被 Truth 覆盖 且 被 >=2 个 Link 覆盖 -> 可删
    // - R=2: 未被 Truth 覆盖 且 被 >=3 个 Link 覆盖 -> 可删
    if (truth.has(k)) continue
    const need = R + 1
    if (need <= 0) continue
    if (cnt < need) continue
    const r = Number(k[0])
    const c = Number(k[1])
    const d = Number(k[2]) as Digit
    out.push({ idx: rcToIndex(r, c), r, c, d })
  }

  // 排序：按 r/c/d
  out.sort((a, b) => a.r - b.r || a.c - b.c || a.d - b.d)
  return out
}

export function formatDeletionList(marks: CandidateMark[]): string {
  if (marks.length === 0) return '无'
  // 输出简洁：r1c1:3,5 这样的格式
  const byCell = new Map<number, Digit[]>()
  for (const m of marks) {
    const arr = byCell.get(m.idx) ?? []
    arr.push(m.d)
    byCell.set(m.idx, arr)
  }
  const parts: string[] = []
  for (const [idx, ds] of Array.from(byCell.entries()).sort((a, b) => a[0] - b[0])) {
    const { r, c } = indexToRC(idx)
    const uniq = Array.from(new Set(ds)).sort((a, b) => a - b)
    parts.push(`r${r + 1}c${c + 1}:${uniq.join('')}`)
  }
  return parts.join('  ')
}


