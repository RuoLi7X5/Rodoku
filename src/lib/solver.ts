import type { Board, CellValue, Digit } from './sudoku'
import { exportPuzzleString } from './sudoku'

const ALL = 0b1111111110 // bits 1..9

function bitCount(x: number): number {
  // Kernighan
  let c = 0
  while (x) {
    x &= x - 1
    c++
  }
  return c
}

function lowestBit(x: number): number {
  return x & -x
}

function bitToDigit(bit: number): Digit {
  // bit is 1<<d
  const d = Math.log2(bit) | 0
  return d as Digit
}

function boxOf(r: number, c: number): number {
  return Math.floor(r / 3) * 3 + Math.floor(c / 3)
}

export type SolveResult =
  | { status: 'none'; key: string }
  | { status: 'unique'; key: string; solution: Digit[] }
  | { status: 'multiple'; key: string; solution: Digit[] }

export function solveBoardFast(board: Board, limitSolutions: number = 2): SolveResult {
  const key = exportPuzzleString(board)

  const rows = new Array<number>(9).fill(0)
  const cols = new Array<number>(9).fill(0)
  const boxes = new Array<number>(9).fill(0)

  const values = new Array<CellValue>(81).fill(0)

  for (let i = 0; i < 81; i++) {
    const v = board[i].value
    values[i] = v
    if (v === 0) continue
    const r = Math.floor(i / 9)
    const c = i % 9
    const b = boxOf(r, c)
    const bit = 1 << v
    if ((rows[r] & bit) || (cols[c] & bit) || (boxes[b] & bit)) {
      return { status: 'none', key }
    }
    rows[r] |= bit
    cols[c] |= bit
    boxes[b] |= bit
  }

  let solutionCount = 0
  let firstSolution: Digit[] | null = null

  function dfs(): void {
    if (solutionCount >= limitSolutions) return

    // pick MRV cell
    let bestIdx = -1
    let bestMask = 0
    let bestCount = 99

    for (let i = 0; i < 81; i++) {
      if (values[i] !== 0) continue
      const r = Math.floor(i / 9)
      const c = i % 9
      const b = boxOf(r, c)
      const mask = ALL & ~(rows[r] | cols[c] | boxes[b])
      const cnt = bitCount(mask)
      if (cnt === 0) return // dead
      if (cnt < bestCount) {
        bestCount = cnt
        bestIdx = i
        bestMask = mask
        if (cnt === 1) break
      }
    }

    if (bestIdx === -1) {
      // solved
      solutionCount++
      if (!firstSolution) {
        firstSolution = values.map((x) => (x === 0 ? 1 : x)) as Digit[]
      }
      return
    }

    const r = Math.floor(bestIdx / 9)
    const c = bestIdx % 9
    const b = boxOf(r, c)

    // iterate candidates
    let mask = bestMask
    while (mask) {
      const bit = lowestBit(mask)
      mask ^= bit
      const d = bitToDigit(bit)
      values[bestIdx] = d
      rows[r] |= bit
      cols[c] |= bit
      boxes[b] |= bit
      dfs()
      boxes[b] ^= bit
      cols[c] ^= bit
      rows[r] ^= bit
      values[bestIdx] = 0
      if (solutionCount >= limitSolutions) return
    }
  }

  dfs()

  if (solutionCount === 0 || !firstSolution) return { status: 'none', key }
  if (solutionCount === 1) return { status: 'unique', key, solution: firstSolution }
  return { status: 'multiple', key, solution: firstSolution }
}


