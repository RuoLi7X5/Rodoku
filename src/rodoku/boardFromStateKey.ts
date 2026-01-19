import type { Board, Digit } from '../lib/sudoku'
import { createEmptyBoard, emptyForbidden, fillAllCandidates } from '../lib/sudoku'

// 将 exportBoardStateKey 生成的 key（digits|forbiddenKey）还原为 Board
// - `puzzle` 用于恢复 given 标记（题面提示数）
export function boardFromStateKey(stateKey: string, puzzle: string): Board | null {
  const [digits, forbKey] = stateKey.split('|')
  if (!digits || digits.length !== 81) return null
  if (!forbKey || forbKey.length !== 162) return null
  if (!puzzle || puzzle.length !== 81) return null

  const board = createEmptyBoard()

  for (let i = 0; i < 81; i++) {
    const chP = puzzle[i]
    const chD = digits[i]

    const pv = Number(chP)
    const dv = Number(chD)
    if (Number.isFinite(pv) && pv >= 1 && pv <= 9) board[i].given = true
    if (Number.isFinite(dv) && dv >= 1 && dv <= 9) board[i].value = dv as Digit

    const code = forbKey.slice(i * 2, i * 2 + 2)
    const mask = parseInt(code, 36)
    if (Number.isFinite(mask) && mask > 0) {
      const forb = emptyForbidden()
      for (let d = 1 as Digit; d <= 9; d = (d + 1) as Digit) {
        forb[d] = (mask & (1 << (d - 1))) !== 0
      }
      board[i].forbidden = forb
    }
  }

  return fillAllCandidates(board)
}

