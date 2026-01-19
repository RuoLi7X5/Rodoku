import type { Technique } from './types'
import { generateRank0InSingleHouse } from './rank0House'

/**
 * 区块（你定义）：1 个 Truth + 1 个 Link 组成的 R=0 结构，
 * 且 Truth 覆盖的候选与 Link 额外覆盖可删候选落在同一行/列/宫内。
 */
export const block: Technique = {
  id: 'block',
  name: '区块',
  apply(board, ctx) {
    if (ctx?.signal?.aborted) return []
    return generateRank0InSingleHouse(board, {
      m: 1,
      techId: 'block',
      techName: '区块',
      maxPerHouse: 80,
    })
  },
}



