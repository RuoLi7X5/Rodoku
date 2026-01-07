export type Digit = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9
export type CellValue = Digit | 0

export type Cell = {
  given: boolean
  value: CellValue
  candidates: boolean[] // index 1..9 used
  forbidden: boolean[] // index 1..9 used, true means "this candidate is eliminated and must not be re-added"
  cellColor?: MarkColor | null
  candidateColors?: (MarkColor | null)[] // index 1..9 used
}

export type Board = Cell[]

export type MarkColor = 'red' | 'orange' | 'yellow' | 'green' | 'blue' | 'purple'

export function emptyCandidates(): boolean[] {
  return new Array<boolean>(10).fill(false)
}

export function emptyForbidden(): boolean[] {
  return new Array<boolean>(10).fill(false)
}

export function emptyCandidateColors(): (MarkColor | null)[] {
  return new Array<MarkColor | null>(10).fill(null)
}

export function createEmptyBoard(): Board {
  return Array.from({ length: 81 }, () => ({
    given: false,
    value: 0 as CellValue,
    candidates: emptyCandidates(),
    forbidden: emptyForbidden(),
    cellColor: null,
    candidateColors: emptyCandidateColors(),
  }))
}

export function rcToIndex(r: number, c: number): number {
  return r * 9 + c
}

export function indexToRC(i: number): { r: number; c: number } {
  return { r: Math.floor(i / 9), c: i % 9 }
}

export function parsePuzzleString(s: string): Board | null {
  const trimmed = s.trim()
  if (trimmed.length !== 81) return null
  const board = createEmptyBoard()
  for (let i = 0; i < 81; i++) {
    const ch = trimmed[i]
    if (ch < '0' || ch > '9') return null
    const n = Number(ch) as CellValue
    if (n === 0) continue
    board[i].given = true
    board[i].value = n
  }
  return board
}

export function exportPuzzleString(board: Board): string {
  return board.map((c) => String(c.value)).join('')
}

export function exportForbiddenKey(board: Board): string {
  // 每格 2 个 base36 字符（0..511），总长 162，稳定用于缓存 key
  return board
    .map((cell) => {
      const forb = cell.forbidden ?? emptyForbidden()
      let mask = 0
      for (let d = 1 as Digit; d <= 9; d = (d + 1) as Digit) {
        if (forb[d]) mask |= 1 << (d - 1)
      }
      return mask.toString(36).padStart(2, '0')
    })
    .join('')
}

export function exportBoardStateKey(board: Board): string {
  return `${exportPuzzleString(board)}|${exportForbiddenKey(board)}`
}

export function isPlacementValid(board: Board, idx: number, v: Digit): boolean {
  const { r, c } = indexToRC(idx)

  // row
  for (let cc = 0; cc < 9; cc++) {
    const j = rcToIndex(r, cc)
    if (j !== idx && board[j].value === v) return false
  }
  // col
  for (let rr = 0; rr < 9; rr++) {
    const j = rcToIndex(rr, c)
    if (j !== idx && board[j].value === v) return false
  }
  // box
  const br = Math.floor(r / 3) * 3
  const bc = Math.floor(c / 3) * 3
  for (let rr = br; rr < br + 3; rr++) {
    for (let cc = bc; cc < bc + 3; cc++) {
      const j = rcToIndex(rr, cc)
      if (j !== idx && board[j].value === v) return false
    }
  }
  return true
}

export function computeConflicts(board: Board): boolean[] {
  const conflicts = new Array<boolean>(81).fill(false)

  // rows
  for (let r = 0; r < 9; r++) {
    const seen = new Map<number, number[]>()
    for (let c = 0; c < 9; c++) {
      const i = rcToIndex(r, c)
      const v = board[i].value
      if (v === 0) continue
      const arr = seen.get(v) ?? []
      arr.push(i)
      seen.set(v, arr)
    }
    for (const [, idxs] of seen) {
      if (idxs.length > 1) idxs.forEach((i) => (conflicts[i] = true))
    }
  }

  // cols
  for (let c = 0; c < 9; c++) {
    const seen = new Map<number, number[]>()
    for (let r = 0; r < 9; r++) {
      const i = rcToIndex(r, c)
      const v = board[i].value
      if (v === 0) continue
      const arr = seen.get(v) ?? []
      arr.push(i)
      seen.set(v, arr)
    }
    for (const [, idxs] of seen) {
      if (idxs.length > 1) idxs.forEach((i) => (conflicts[i] = true))
    }
  }

  // boxes
  for (let b = 0; b < 9; b++) {
    const br = Math.floor(b / 3) * 3
    const bc = (b % 3) * 3
    const seen = new Map<number, number[]>()
    for (let r = br; r < br + 3; r++) {
      for (let c = bc; c < bc + 3; c++) {
        const i = rcToIndex(r, c)
        const v = board[i].value
        if (v === 0) continue
        const arr = seen.get(v) ?? []
        arr.push(i)
        seen.set(v, arr)
      }
    }
    for (const [, idxs] of seen) {
      if (idxs.length > 1) idxs.forEach((i) => (conflicts[i] = true))
    }
  }

  return conflicts
}

export function setCellValue(prev: Board, idx: number, v: Digit | 0): Board {
  const cell = prev[idx]
  if (cell.given) return prev

  const next = prev.slice()
  const nextCell: Cell = { ...cell, value: 0, candidates: cell.candidates }

  if (v !== 0) {
    if (!isPlacementValid(prev, idx, v)) return prev
    nextCell.value = v
    nextCell.candidates = emptyCandidates()
    nextCell.candidateColors = emptyCandidateColors()
    // 填数后：同一行/列/宫内该数字候选必须删除（只删不加）
    const { r, c } = indexToRC(idx)
    const boxR = Math.floor(r / 3) * 3
    const boxC = Math.floor(c / 3) * 3
    for (let cc = 0; cc < 9; cc++) {
      const j = rcToIndex(r, cc)
      if (j === idx) continue
      const peer = prev[j]
      if (peer.value !== 0) continue
      const forb = (peer.forbidden ?? emptyForbidden()).slice()
      forb[v] = true
      const cands = peer.candidates.slice()
      cands[v] = false
      const colors = (peer.candidateColors ?? emptyCandidateColors()).slice()
      colors[v] = null
      next[j] = { ...peer, candidates: cands, forbidden: forb, candidateColors: colors }
    }
    for (let rr = 0; rr < 9; rr++) {
      const j = rcToIndex(rr, c)
      if (j === idx) continue
      const peer = prev[j]
      if (peer.value !== 0) continue
      const forb = (peer.forbidden ?? emptyForbidden()).slice()
      forb[v] = true
      const cands = peer.candidates.slice()
      cands[v] = false
      const colors = (peer.candidateColors ?? emptyCandidateColors()).slice()
      colors[v] = null
      next[j] = { ...peer, candidates: cands, forbidden: forb, candidateColors: colors }
    }
    for (let rr = boxR; rr < boxR + 3; rr++) {
      for (let cc = boxC; cc < boxC + 3; cc++) {
        const j = rcToIndex(rr, cc)
        if (j === idx) continue
        const peer = prev[j]
        if (peer.value !== 0) continue
        const forb = (peer.forbidden ?? emptyForbidden()).slice()
        forb[v] = true
        const cands = peer.candidates.slice()
        cands[v] = false
        const colors = (peer.candidateColors ?? emptyCandidateColors()).slice()
        colors[v] = null
        next[j] = { ...peer, candidates: cands, forbidden: forb, candidateColors: colors }
      }
    }
  } else {
    nextCell.value = 0
  }

  next[idx] = nextCell
  return next
}

export function toggleCellCandidate(
  prev: Board,
  idx: number,
  d: Digit,
  colorToApply?: MarkColor | null,
): Board {
  const cell = prev[idx]
  if (cell.given) return prev
  if (cell.value !== 0) return prev
  const next = prev.slice()
  const cands = cell.candidates.slice()
  const forb = (cell.forbidden ?? emptyForbidden()).slice()
  cands[d] = !cands[d]
  // 用户手动删候选：视为“永久删除”，后续全标/更新不得加回
  if (!cands[d]) forb[d] = true
  else forb[d] = false
  const candColors = (cell.candidateColors ?? emptyCandidateColors()).slice()
  if (cands[d]) candColors[d] = colorToApply ?? candColors[d] ?? null
  else candColors[d] = null
  next[idx] = { ...cell, candidates: cands, forbidden: forb, candidateColors: candColors }
  return next
}

export function clearCellCandidates(prev: Board, idx: number): Board {
  const cell = prev[idx]
  if (cell.given) return prev
  if (cell.value !== 0) return prev
  const next = prev.slice()
  // 仅清空显示/标记，不恢复已经删除的候选（forbidden 保留）
  next[idx] = { ...cell, candidates: emptyCandidates(), candidateColors: emptyCandidateColors() }
  return next
}

export function validateGivenBoard(board: Board): boolean {
  for (let i = 0; i < 81; i++) {
    const v = board[i].value
    if (v === 0) continue
    if (!isPlacementValid(board, i, v as Digit)) return false
  }
  return true
}

export function computeAllowedCandidates(board: Board, idx: number): boolean[] {
  const cell = board[idx]
  if (cell.value !== 0) return emptyCandidates()
  const allowed = emptyCandidates()
  for (let d = 1 as Digit; d <= 9; d = (d + 1) as Digit) {
    allowed[d] = isPlacementValid(board, idx, d)
  }
  return allowed
}

export function computeEffectiveCandidates(board: Board, idx: number): boolean[] {
  const cell = board[idx]
  if (cell.value !== 0) return emptyCandidates()
  const allowed = computeAllowedCandidates(board, idx)
  const forb = cell.forbidden ?? emptyForbidden()
  for (let d = 1 as Digit; d <= 9; d = (d + 1) as Digit) {
    if (forb[d]) allowed[d] = false
  }
  return allowed
}

export function fillAllCandidates(prev: Board): Board {
  const next = prev.slice()
  let changed = false
  for (let i = 0; i < 81; i++) {
    const cell = prev[i]
    if (cell.value !== 0) {
      if (cell.candidates.some(Boolean)) {
        next[i] = { ...cell, candidates: emptyCandidates(), candidateColors: emptyCandidateColors() }
        changed = true
      }
      continue
    }
    const allowed = computeAllowedCandidates(prev, i)
    const forb = cell.forbidden ?? emptyForbidden()
    const cands = allowed.slice()
    for (let d = 1 as Digit; d <= 9; d = (d + 1) as Digit) {
      if (forb[d]) cands[d] = false
    }
    next[i] = { ...cell, candidates: cands, candidateColors: emptyCandidateColors() }
    changed = true
  }
  return changed ? next : prev
}

export function clearAllCandidates(prev: Board): Board {
  const next = prev.slice()
  let changed = false
  for (let i = 0; i < 81; i++) {
    const cell = prev[i]
    if (cell.candidates.some(Boolean) || (cell.candidateColors ?? []).some((x) => x != null)) {
      next[i] = { ...cell, candidates: emptyCandidates(), candidateColors: emptyCandidateColors() }
      changed = true
    }
  }
  return changed ? next : prev
}

export function applyCandidateEliminations(
  prev: Board,
  eliminations: Array<{ idx: number; d: Digit }>,
): Board {
  if (eliminations.length === 0) return prev
  const next = prev.slice()
  for (const { idx, d } of eliminations) {
    const cell = next[idx]
    if (!cell || cell.value !== 0) continue
    const forb = (cell.forbidden ?? emptyForbidden()).slice()
    const cands = cell.candidates.slice()
    const colors = (cell.candidateColors ?? emptyCandidateColors()).slice()
    forb[d] = true
    cands[d] = false
    colors[d] = null
    next[idx] = { ...cell, forbidden: forb, candidates: cands, candidateColors: colors }
  }
  return next
}

export function setCellColor(prev: Board, idx: number, color: MarkColor | null): Board {
  const cell = prev[idx]
  const next = prev.slice()
  next[idx] = { ...cell, cellColor: color }
  return next
}


