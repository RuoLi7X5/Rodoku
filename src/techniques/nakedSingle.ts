import type { Digit } from '../lib/sudoku'
import { computeEffectiveCandidates, indexToRC, rcToIndex } from '../lib/sudoku'
import type { Technique, TechniqueResult } from './types'

function onlyDigit(cands: boolean[]): Digit | null {
  let found: Digit | null = null
  for (let d = 1 as Digit; d <= 9; d = (d + 1) as Digit) {
    if (!cands[d]) continue
    if (found != null) return null
    found = d
  }
  return found
}

/**
 * 唯一余数（常见定义，含两类）：
 * 1) 裸单：某格在“有效候选(行列宫排除 ∩ 非forbidden)”下只剩 1 个候选 -> 必须填它
 * 2) 隐单：在某行/列/宫内，某数字只剩 1 个可放位置 -> 该位置必须填该数字
 */
export const nakedSingle: Technique = {
  id: 'unique-remainder',
  name: '唯一余数',
  apply(board, ctx) {
    const out: TechniqueResult[] = []
    const seen = new Set<string>()

    const pushFill = (idx: number, d: Digit, detail: string) => {
      const sig = `${idx}=${d}`
      if (seen.has(sig)) return
      seen.add(sig)
      out.push({
        techniqueId: 'unique-remainder',
        techniqueName: '唯一余数',
        eliminations: [],
        conclusion: { idx, value: d },
        detail,
      })
    }

    // 1) 裸单：某格仅剩 1 个有效候选
    for (let idx = 0; idx < 81; idx++) {
      if (ctx?.signal?.aborted) break
      if (board[idx].value !== 0) continue
      const eff = computeEffectiveCandidates(board, idx)
      const d = onlyDigit(eff)
      if (!d) continue
      const { r, c } = indexToRC(idx)
      pushFill(idx, d, `裸单：r${r + 1}c${c + 1} 仅剩候选 ${d}`)
    }

    // 2) 隐单：行/列/宫内某数字只有 1 个位置可放
    const scanHouse = (idxs: number[], houseLabel: string) => {
      for (let d = 1 as Digit; d <= 9; d = (d + 1) as Digit) {
        if (ctx?.signal?.aborted) return
        let onlyIdx = -1
        let cnt = 0
        for (const idx of idxs) {
          if (board[idx].value !== 0) continue
          const eff = computeEffectiveCandidates(board, idx)
          if (!eff[d]) continue
          cnt++
          onlyIdx = idx
          if (cnt >= 2) break
        }
        if (cnt === 1 && onlyIdx >= 0) {
          const { r, c } = indexToRC(onlyIdx)
          pushFill(onlyIdx, d, `隐单：${houseLabel} 的 ${d} 仅能放在 r${r + 1}c${c + 1}`)
        }
      }
    }

    for (let r = 0; r < 9; r++) {
      if (ctx?.signal?.aborted) break
      scanHouse(
        Array.from({ length: 9 }, (_, c) => rcToIndex(r, c)),
        `第${r + 1}行`,
      )
    }
    for (let c = 0; c < 9; c++) {
      if (ctx?.signal?.aborted) break
      scanHouse(
        Array.from({ length: 9 }, (_, r) => rcToIndex(r, c)),
        `第${c + 1}列`,
      )
    }
    for (let b = 0; b < 9; b++) {
      if (ctx?.signal?.aborted) break
      const br = Math.floor(b / 3) * 3
      const bc = (b % 3) * 3
      const idxs: number[] = []
      for (let rr = br; rr < br + 3; rr++) {
        for (let cc = bc; cc < bc + 3; cc++) {
          idxs.push(rcToIndex(rr, cc))
        }
      }
      scanHouse(idxs, `第${b + 1}宫`)
    }

    return out
  },
}


