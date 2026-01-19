import type { Board, Digit } from '../lib/sudoku'
import type { RegionRef } from '../lib/rank'

export type Elimination = {
  idx: number
  d: Digit
  /** 可选：给 UI/日志使用的人类可读原因 */
  reason?: string
}

export type TechniqueResult = {
  /** 技巧唯一 id，如 "naked-single"、"xyz-wing" */
  techniqueId: string
  /** 技巧显示名，如 "Naked Single"、"XYZ-Wing" */
  techniqueName: string
  /** 本次发现对应的删数集合 */
  eliminations: Elimination[]
  /** 可选：结构性说明（后续可扩展为 Truth/Link 或更一般集合） */
  detail?: string
  /** 可选：填数结论（用于“唯一余数”等直接落子类技巧） */
  conclusion?: {
    idx: number
    value: Digit
  }
  /**
   * 可选：将该技巧实例映射为“秩结构”用于统一展示。
   * - 只有提供了该字段的技巧结果才会在“秩查询”里以秩结构方式展示
   * - truths/links 必须能让项目现有的 Rank 删数规则推导出 eliminations（否则表现会不一致）
   */
  rankStructure?: {
    truths: RegionRef[]
    links: RegionRef[]
    /** 可选：若不填则默认 truths.length */
    T?: number
    /** 可选：若不填则默认 links.length */
    L?: number
    /** 可选：若不填则默认 L-T */
    R?: number
  }
}

export type TechniqueContext = {
  signal?: AbortSignal
}

export type Technique = {
  id: string
  name: string
  /**
   * 在当前盘面（有效候选=允许候选∩非forbidden）上查找该技巧的所有实例。
   * 返回 0..N 个结果，每个结果可以包含 1..M 个删数。
   */
  apply(board: Board, ctx?: TechniqueContext): TechniqueResult[]
}


