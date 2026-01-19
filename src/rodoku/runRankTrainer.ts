import type { Board, Digit } from '../lib/sudoku'
import { createEmptyBoard, exportBoardStateKey, exportPuzzleString, fillAllCandidates, setCellValue } from '../lib/sudoku'
import type { FoundStructure, SearchCache } from '../lib/rankSearch'
import type { SearchProgress } from '../lib/rankSearch'
import { getOrBuildSearchCache, searchRankStructures } from '../lib/rankSearch'
import { computeDeletableCandidates } from '../lib/rankDeductions'
import { applyCandidateEliminations } from '../lib/sudoku'
import { solveBoardFast } from '../lib/solver'
import type { RodokuRun, RodokuStep } from './types'

function now() {
  return Date.now()
}

function rid(): string {
  return `${now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
}

function rcOf(idx: number): { r: number; c: number } {
  return { r: Math.floor(idx / 9) + 1, c: (idx % 9) + 1 }
}

function summarizeDeletion(ms: Array<{ idx: number; d: Digit }>): string {
  if (ms.length === 0) return ''
  const parts = ms.slice(0, 6).map((m) => {
    const { r, c } = rcOf(m.idx)
    return `r${r}c${c}<>${m.d}`
  })
  const suffix = ms.length > 6 ? ` …(+${ms.length - 6})` : ''
  return parts.join(' ') + suffix
}

function summarizeStruct(st: FoundStructure): string {
  return `T${st.T} L${st.L} R${st.R}`
}

function onlyCandidate(cands: boolean[]): Digit | null {
  let found: Digit | null = null
  for (let d = 1 as Digit; d <= 9; d = (d + 1) as Digit) {
    if (!cands[d]) continue
    if (found != null) return null
    found = d
  }
  return found
}

function houseCells(kind: 'row' | 'col' | 'box', k: number): number[] {
  const out: number[] = []
  if (kind === 'row') {
    const r = k
    for (let c = 0; c < 9; c++) out.push(r * 9 + c)
    return out
  }
  if (kind === 'col') {
    const c = k
    for (let r = 0; r < 9; r++) out.push(r * 9 + c)
    return out
  }
  const br = Math.floor(k / 3) * 3
  const bc = (k % 3) * 3
  for (let rr = br; rr < br + 3; rr++) for (let cc = bc; cc < bc + 3; cc++) out.push(rr * 9 + cc)
  return out
}

function applyForcedFills(
  board0: Board,
  solution: Digit[],
  run: RodokuRun,
  onUpdate?: (run: RodokuRun) => void,
): Board {
  let board = board0
  // 反复执行：单元格唯一候选 / 位置唯一（行列宫）
  while (true) {
    let moved: { idx: number; d: Digit; why: string } | null = null

    // 1) 单元格唯一候选
    for (let idx = 0; idx < 81; idx++) {
      const cell = board[idx]
      if (cell.value !== 0 || cell.given) continue
      const d = onlyCandidate(cell.candidates)
      if (!d) continue
      moved = { idx, d, why: '单元格唯一候选' }
      break
    }

    // 2) 位置唯一：行/列/宫内某数字仅出现一次
    if (!moved) {
      for (const kind of ['row', 'col', 'box'] as const) {
        for (let k = 0; k < 9; k++) {
          for (let d = 1 as Digit; d <= 9; d = (d + 1) as Digit) {
            let hitIdx = -1
            let count = 0
            for (const idx of houseCells(kind, k)) {
              const cell = board[idx]
              if (cell.value !== 0 || cell.given) continue
              if (!cell.candidates[d]) continue
              count++
              hitIdx = idx
              if (count >= 2) break
            }
            if (count === 1 && hitIdx >= 0) {
              moved = { idx: hitIdx, d, why: `${kind}${k + 1} 位置唯一` }
              break
            }
          }
          if (moved) break
        }
        if (moved) break
      }
    }

    if (!moved) break

    // 安全阀：不填错（不参与解释，只用于保证日志正确）
    if (solution[moved.idx] !== moved.d) break

    const { r, c } = rcOf(moved.idx)
    const step: RodokuStep = {
      stepIndex: run.steps.length,
      atMs: now(),
      action: { type: 'commit', idx: moved.idx, d: moved.d },
      rationale: `${moved.why} ⇒ 填 r${r}c${c}=${moved.d}`,
      affected: [{ idx: moved.idx, d: moved.d }],
    }
    run.steps.push(step)
    board = setCellValue(board, moved.idx, moved.d)
    // 基础规则排除 + forbidden 约束刷新候选
    board = fillAllCandidates(board)
    run.snapshots.push(exportBoardStateKey(board))
    onUpdate?.({ ...run })
  }

  return board
}

export type RankTrainerOptions = {
  minT: number
  maxT: number
  maxSteps: number
  // 当前仓库的秩逻辑 UI 只展示 R<3，这里先沿用做 MVP（后续可放开）
  maxR: number
  // 每一步允许秩搜索的最长时间（避免 UI 长时间无输出）
  stepTimeoutMs?: number
}

export async function runRankTrainer(
  puzzle: string,
  opts: RankTrainerOptions,
  signal?: AbortSignal,
  onUpdate?: (run: RodokuRun) => void,
  onSearchProgress?: (p: SearchProgress) => void,
  forcedRunId?: string,
): Promise<RodokuRun> {
  const startedAtMs = now()
  const run: RodokuRun = {
    id: forcedRunId ?? rid(),
    puzzle,
    startedAtMs,
    status: 'running',
    steps: [],
    snapshots: [],
  }
  onUpdate?.({ ...run })

  try {
    // 以解作为“安全阀”：避免秩结构实现/参数导致误删（不参与解释输出）
    const base = fillAllCandidates(parseBoardFromPuzzle(puzzle))
    const solved = solveBoardFast(base, 2)
    if (solved.status === 'none') {
      run.status = 'error'
      run.error = '题目无解（rank trainer 拒绝执行）'
      run.finishedAtMs = now()
      return run
    }
    const solution = solved.solution

    let board = base
    run.snapshots.push(exportBoardStateKey(board))
    onUpdate?.({ ...run })
    // 先跑一轮强制填数（单元格唯一候选 / 位置唯一），减少后续秩搜索压力
    board = applyForcedFills(board, solution, run, onUpdate)

    let cache: SearchCache | null = null

    for (let stepIndex = 0; stepIndex < opts.maxSteps; stepIndex++) {
      if (signal?.aborted) {
        run.status = 'aborted'
        run.finishedAtMs = now()
        return run
      }

      // 已完成
      if (!exportPuzzleString(board).includes('0')) {
        run.status = 'solved'
        run.finishedAtMs = now()
        return run
      }

      cache = getOrBuildSearchCache(board, cache)

      const ac = new AbortController()
      const abortOnOuter = () => ac.abort()
      signal?.addEventListener('abort', abortOnOuter, { once: true })
      const timeoutMs = Math.max(50, Math.floor(opts.stepTimeoutMs ?? 800))
      const t = setTimeout(() => ac.abort(), timeoutMs)

      let progressed = false
      try {
        const gen = searchRankStructures(
          board,
          { minT: opts.minT, maxT: opts.maxT, maxResults: 200 },
          (p) => onSearchProgress?.(p),
          ac.signal,
          cache,
        )

        for await (const st0 of gen) {
          if (signal?.aborted) break
          const st = { ...st0, source: 'rank' as const }
          if (st.R < 0 || st.R > opts.maxR) continue

          // 1) 先处理“填数结论”
          if (st.conclusion) {
            const idx = st.conclusion.idx
            const v = st.conclusion.value
            // 安全阀：不填错
            if (solution[idx] !== v) continue
            const s: RodokuStep = {
              stepIndex: run.steps.length,
              atMs: now(),
              action: { type: 'commit', idx, d: v },
              rationale: `${summarizeStruct(st)} ⇒ 填 r${rcOf(idx).r}c${rcOf(idx).c}=${v}`,
              affected: [{ idx, d: v }],
            }
            run.steps.push(s)
            board = setCellValue(board, idx, v)
            board = fillAllCandidates(board)
            run.snapshots.push(exportBoardStateKey(board))
            // 触发强制填数链
            board = applyForcedFills(board, solution, run, onUpdate)
            onUpdate?.({ ...run })
            progressed = true
            break
          }

          // 2) 删候选
          const delsAll = computeDeletableCandidates(board, st)
          const dels = delsAll.filter((m) => solution[m.idx] !== m.d) as Array<{ idx: number; d: Digit }>
          if (dels.length === 0) continue

          const s: RodokuStep = {
            stepIndex: run.steps.length,
            atMs: now(),
            action: { type: 'eliminate', idx: dels[0].idx, d: dels[0].d }, // 代表性动作（实际会批量删）
            rationale: `${summarizeStruct(st)} ⇒ 删候选 ${summarizeDeletion(dels)}`,
            affected: dels.map((m) => ({ idx: m.idx, d: m.d })),
          }
          run.steps.push(s)
          board = applyCandidateEliminations(board, dels)
          board = fillAllCandidates(board)
          run.snapshots.push(exportBoardStateKey(board))
          // 删候选后：强制填数（若产生唯一候选/唯一位置）
          board = applyForcedFills(board, solution, run, onUpdate)
          onUpdate?.({ ...run })
          progressed = true
          break
        }
      } finally {
        clearTimeout(t)
        signal?.removeEventListener('abort', abortOnOuter)
      }

      if (!progressed) {
        run.status = 'stuck'
        run.finishedAtMs = now()
        onUpdate?.({ ...run })
        return run
      }
    }

    run.status = 'stuck'
    run.finishedAtMs = now()
    onUpdate?.({ ...run })
    return run
  } catch (e) {
    run.status = 'error'
    run.error = e instanceof Error ? e.message : String(e)
    run.finishedAtMs = now()
    onUpdate?.({ ...run })
    return run
  }
}

function parseBoardFromPuzzle(puzzle: string): Board {
  // puzzle 是 81 位 0..9；这里直接构造 given board
  const board = createEmptyBoard()
  for (let i = 0; i < 81; i++) {
    const ch = puzzle[i]
    const n = Number(ch)
    if (!Number.isFinite(n) || n < 0 || n > 9) continue
    if (n === 0) continue
    board[i].given = true
    board[i].value = n as Digit
  }
  return board
}

