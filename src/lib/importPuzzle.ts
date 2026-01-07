import type { Board, Digit } from './sudoku'
import { applyCandidateEliminations, createEmptyBoard, fillAllCandidates } from './sudoku'

export type ImportResult = {
  board: Board
  // deletions already applied into board.forbidden
}

function isDigitChar(ch: string): boolean {
  return ch >= '0' && ch <= '9'
}

export function parseFlexible81(input: string): { board: Board } | null {
  const normalized = input.replace(/\r|\n|\t/g, '')
  const cells: string[] = []

  // 若长度刚好 81，则认为“每个字符就是一个格子”（支持空格表示空格）
  if (normalized.length === 81) {
    for (const ch of normalized) {
      if (ch === ' ') cells.push('0')
      else if (ch === '.' || ch === '0' || (ch >= '1' && ch <= '9')) cells.push(ch)
      else return null
    }
  } else {
    // 否则按“抽取单元格符号”的方式解析（忽略分隔空格）
    for (const ch of normalized) {
      if (ch === '.' || ch === '0' || (ch >= '1' && ch <= '9')) cells.push(ch)
      else if (ch === ' ') {
        // 在这种模式下，空格更可能是分隔符，不计为格子
        continue
      }
    }
  }

  if (cells.length !== 81) return null
  const board = createEmptyBoard()
  for (let i = 0; i < 81; i++) {
    const ch = cells[i]
    if (ch === '.' || ch === '0') continue
    const d = Number(ch) as Digit
    board[i].given = true
    board[i].value = d
  }
  return { board }
}

export function parseSpecialFormat(input: string): ImportResult | null {
  // Example:
  // :0000:x:3.+12.+9.....+9.1+4..5..2..81.+9+21.8+964.+3.+3..2+5.9+19...3+1..8..3..7+9.+24+2.9.+38+17.9...+2...:724 627 ... ::
  const parts = input.split(':')
  if (parts.length < 4) return null

  // find puzzle segment: contains '.' or '+' and long enough
  let puzzleSeg = ''
  let puzzleIdx = -1
  for (let i = 0; i < parts.length; i++) {
    const p = parts[i]
    if ((p.includes('.') || p.includes('+')) && p.length >= 50) {
      puzzleSeg = p
      puzzleIdx = i
      break
    }
  }
  if (!puzzleSeg) return null

  const deletionsSeg = parts[puzzleIdx + 1] ?? ''

  // parse 81 cells from puzzleSeg
  const board = createEmptyBoard()
  const cells: Array<{ v: Digit | 0; given: boolean }> = []
  const s = puzzleSeg.replace(/\s/g, '')
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]
    if (ch === '.') {
      cells.push({ v: 0, given: false })
      continue
    }
    if (ch === '+') {
      const next = s[i + 1]
      if (!next || next < '1' || next > '9') return null
      cells.push({ v: Number(next) as Digit, given: false })
      i++
      continue
    }
    if (ch >= '1' && ch <= '9') {
      cells.push({ v: Number(ch) as Digit, given: true })
      continue
    }
    // ignore other chars
  }
  if (cells.length !== 81) return null

  for (let i = 0; i < 81; i++) {
    const { v, given } = cells[i]
    if (v === 0) continue
    board[i].value = v
    board[i].given = given
  }

  // parse deletions list like "724" => delete r2c4 digit7
  const tokens = deletionsSeg.split(/\s+/).filter(Boolean)
  const elim: Array<{ idx: number; d: Digit }> = []
  for (const t of tokens) {
    if (t.length !== 3) continue
    if (!isDigitChar(t[0]) || !isDigitChar(t[1]) || !isDigitChar(t[2])) continue
    const d = Number(t[0]) as Digit
    const r = Number(t[1])
    const c = Number(t[2])
    if (d < 1 || d > 9) continue
    if (r < 1 || r > 9 || c < 1 || c > 9) continue
    const idx = (r - 1) * 9 + (c - 1)
    elim.push({ idx, d })
  }

  let out = board
  if (elim.length > 0) out = applyCandidateEliminations(out, elim)
  // import要求：默认全标（会尊重 forbidden）
  out = fillAllCandidates(out)

  return { board: out }
}

export function parsePuzzleInput(input: string): ImportResult | null {
  const trimmed = input.trim()
  if (!trimmed) return null
  // special format if contains ':' and '+' or '::'
  if (trimmed.includes(':') && (trimmed.includes('+') || trimmed.includes('::'))) {
    return parseSpecialFormat(trimmed)
  }
  const parsed = parseFlexible81(trimmed)
  if (!parsed) return null
  // import要求：默认全标
  return { board: fillAllCandidates(parsed.board) }
}


