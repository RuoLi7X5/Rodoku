import type { Technique } from './types'
import { generateRank0InSingleHouse } from './rank0House'

/**
 * 数对（你定义）：2 个 Truth + 2 个 Link 组成的 R=0 结构，
 * 且 Truth 覆盖的候选与 Link 额外覆盖可删候选落在同一行/列/宫内。
 */
export const pair: Technique = {
  id: 'pair',
  name: '数对',
  apply(board, ctx) {
    if (ctx?.signal?.aborted) return []
    return generateRank0InSingleHouse(board, {
      m: 2,
      techId: 'pair',
      techName: '数对',
      maxPerHouse: 60,
    })
  },
}



