import type { Board, Digit } from './sudoku'
import { computeEffectiveCandidates, indexToRC, rcToIndex } from './sudoku'

export type CandidateNode = { r: number; c: number; d: Digit }

export function candidateId(n: CandidateNode): string {
  return `${n.r}${n.c}${n.d}`
}

export type GroupKind = 'truth' | 'link'
export type RegionRef =
  | { type: 'cell'; idx: number }
  | { type: 'rowDigit'; row: number; d: Digit }
  | { type: 'colDigit'; col: number; d: Digit }
  | { type: 'boxDigit'; box: number; d: Digit }

export type RankGroup = {
  id: string
  kind: GroupKind
  ref: RegionRef
}

export function describeGroup(g: RankGroup): string {
  const r = g.ref
  if (r.type === 'cell') {
    const { r: rr, c: cc } = indexToRC(r.idx)
    return `${g.kind.toUpperCase()}：单元格 R${rr + 1}C${cc + 1}（该格允许候选集合）`
  }
  if (r.type === 'rowDigit') return `${g.kind.toUpperCase()}：第 ${r.row + 1} 行的数字 ${r.d} 候选`
  if (r.type === 'colDigit') return `${g.kind.toUpperCase()}：第 ${r.col + 1} 列的数字 ${r.d} 候选`
  return `${g.kind.toUpperCase()}：第 ${r.box + 1} 宫的数字 ${r.d} 候选`
}

export function resolveGroup(board: Board, ref: RegionRef): CandidateNode[] {
  if (ref.type === 'cell') {
    const cell = board[ref.idx]
    if (cell.value !== 0) return []
    const { r, c } = indexToRC(ref.idx)
    const allowed = computeEffectiveCandidates(board, ref.idx)
    const nodes: CandidateNode[] = []
    for (let d = 1 as Digit; d <= 9; d = (d + 1) as Digit) {
      if (allowed[d]) nodes.push({ r, c, d })
    }
    return nodes
  }

  if (ref.type === 'rowDigit') {
    const nodes: CandidateNode[] = []
    const row = ref.row
    for (let c = 0; c < 9; c++) {
      const idx = rcToIndex(row, c)
      if (board[idx].value !== 0) continue
      const allowed = computeEffectiveCandidates(board, idx)
      if (allowed[ref.d]) nodes.push({ r: row, c, d: ref.d })
    }
    return nodes
  }

  if (ref.type === 'colDigit') {
    const nodes: CandidateNode[] = []
    const col = ref.col
    for (let r = 0; r < 9; r++) {
      const idx = rcToIndex(r, col)
      if (board[idx].value !== 0) continue
      const allowed = computeEffectiveCandidates(board, idx)
      if (allowed[ref.d]) nodes.push({ r, c: col, d: ref.d })
    }
    return nodes
  }

  // boxDigit
  const nodes: CandidateNode[] = []
  const br = Math.floor(ref.box / 3) * 3
  const bc = (ref.box % 3) * 3
  for (let r = br; r < br + 3; r++) {
    for (let c = bc; c < bc + 3; c++) {
      const idx = rcToIndex(r, c)
      if (board[idx].value !== 0) continue
      const allowed = computeEffectiveCandidates(board, idx)
      if (allowed[ref.d]) nodes.push({ r, c, d: ref.d })
    }
  }
  return nodes
}

export type RankAnalysis = {
  T: number
  L: number
  R: number
  truthCandidates: Set<string>
  linkCandidates: Set<string>
  truthOverlap: Set<string>
  uncoveredByLinks: Set<string>
}

export function analyzeRankStructure(board: Board, truths: RankGroup[], links: RankGroup[]): RankAnalysis {
  const truthCandidates = new Set<string>()
  const linkCandidates = new Set<string>()

  const seenInTruth = new Map<string, number>()
  const truthOverlap = new Set<string>()

  for (const g of truths) {
    const nodes = resolveGroup(board, g.ref)
    for (const n of nodes) {
      const id = candidateId(n)
      const cnt = (seenInTruth.get(id) ?? 0) + 1
      seenInTruth.set(id, cnt)
      if (cnt >= 2) truthOverlap.add(id)
      truthCandidates.add(id)
    }
  }

  for (const g of links) {
    const nodes = resolveGroup(board, g.ref)
    for (const n of nodes) linkCandidates.add(candidateId(n))
  }

  const uncoveredByLinks = new Set<string>()
  for (const id of truthCandidates) {
    if (!linkCandidates.has(id)) uncoveredByLinks.add(id)
  }

  const T = truths.length
  const L = links.length
  const R = L - T

  return { T, L, R, truthCandidates, linkCandidates, truthOverlap, uncoveredByLinks }
}



