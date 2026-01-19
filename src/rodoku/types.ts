import type { Digit } from '../lib/sudoku'

export type RodokuAction =
  | { type: 'eliminate'; idx: number; d: Digit }
  | { type: 'commit'; idx: number; d: Digit }

export type RodokuStep = {
  stepIndex: number
  atMs: number
  action: RodokuAction
  rationale: string
  meta?: any
  // 用于回放/高亮（可选）
  affected?: Array<{ idx: number; d?: Digit }>
}

export type RodokuRun = {
  id: string
  jobId?: string
  puzzle: string // 81位，0 表示空格
  startedAtMs: number
  finishedAtMs?: number
  status: 'idle' | 'running' | 'solved' | 'stuck' | 'aborted' | 'error'
  error?: string
  steps: RodokuStep[]
  // 每一步之后的盘面快照（用于回放）
  snapshots: string[] // exportBoardStateKey 形式：digits|forbidden
}

