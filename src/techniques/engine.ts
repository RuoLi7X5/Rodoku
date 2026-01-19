import type { Board } from '../lib/sudoku'
import type { Technique, TechniqueContext, TechniqueResult } from './types'

export type RunTechniquesOptions = {
  signal?: AbortSignal
  /**
   * 最多返回多少条结果（不是删数数量），避免 UI 被海量结果淹没。
   * 不传表示不限制。
   */
  maxResults?: number
}

function elimSig(e: { idx: number; d: number }): string {
  return `${e.d}@${e.idx}`
}

function conclSig(c: { idx: number; value: number }): string {
  return `=${c.value}@${c.idx}`
}

function resultSig(r: TechniqueResult): string {
  const parts: string[] = []
  if (r.conclusion) parts.push(conclSig(r.conclusion))
  if (r.eliminations && r.eliminations.length > 0) {
    parts.push(
      r.eliminations
        .map(elimSig)
        .sort()
        .join(','),
    )
  }
  return parts.filter(Boolean).join('|')
}

export type AggregatedTechniqueResult = TechniqueResult & {
  /** 对应删数签名，可用于去重/缓存 */
  signature: string
}

/**
 * 按注册顺序遍历技巧，汇总所有结果，并按删数签名去重。
 * 注意：技巧本身不应修改 board，只返回删数。
 */
export function runTechniques(
  board: Board,
  techniques: Technique[],
  opts: RunTechniquesOptions = {},
): AggregatedTechniqueResult[] {
  const out: AggregatedTechniqueResult[] = []
  const seen = new Set<string>()
  const ctx: TechniqueContext = { signal: opts.signal }

  for (const t of techniques) {
    if (opts.signal?.aborted) break
    const results = t.apply(board, ctx)
    for (const r of results) {
      if (opts.signal?.aborted) break
      // 允许“填数结论”类技巧：可能没有 eliminations
      if ((!r.eliminations || r.eliminations.length === 0) && !r.conclusion) continue
      const sig = resultSig(r)
      if (!sig) continue
      if (seen.has(sig)) continue
      seen.add(sig)
      out.push({ ...r, signature: sig })
      if (opts.maxResults != null && out.length >= opts.maxResults) return out
    }
  }

  return out
}


