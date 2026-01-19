import type { Technique, TechniqueResult } from './types'
import { generateRank0InSingleHouse } from './rank0House'

function arrayName(m: number): string {
  if (m === 3) return '三数组'
  return `${m}数组`
}

/**
 * 数组（你定义）：m 个 Truth + m 个 Link（m>2）的 R=0 结构，
 * 且 Truth 覆盖的候选与 Link 额外覆盖可删候选落在同一行/列/宫内。
 *
 * 这里先实现 m=3/4（三数组、4数组），避免组合爆炸拖慢查询；
 * 若你确认需要更大的 m，我们再把上限提升并加更强剪枝/缓存。
 */
export const arrays: Technique = {
  id: 'arrays',
  name: '数组',
  apply(board, ctx) {
    if (ctx?.signal?.aborted) return []
    const out: TechniqueResult[] = []
    for (const m of [3, 4]) {
      if (ctx?.signal?.aborted) break
      out.push(
        ...generateRank0InSingleHouse(board, {
          m,
          techId: `array-${m}`,
          techName: arrayName(m),
          maxPerHouse: m === 3 ? 30 : 12,
        }),
      )
    }
    return out
  },
}



