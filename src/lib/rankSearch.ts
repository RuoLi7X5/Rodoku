import type { Board, Digit } from './sudoku'
import { computeAllowedCandidates, emptyForbidden, exportBoardStateKey, indexToRC } from './sudoku'
import type { RegionRef } from './rank'
import type { Bitset } from './bitset'
import {
  bitsetAndNonZero,
  bitsetAndNot,
  bitsetClone,
  bitsetCreate,
  bitsetIsZero,
  bitsetOrInto,
  bitsetPopFirst,
  bitsetHas,
  bitsetSet,
} from './bitset'

type Candidate = { r: number; c: number; d: Digit; cellIdx: number; box: number }

type TruthOption = {
  ref: RegionRef
  candBits: Bitset
  candIdxs: number[]
  forbid: 'cell' | 'rowDigit' | 'colDigit' | 'boxDigit'
  size: number
}

export type FoundStructure = {
  id: string
  T: number
  L: number
  R: number
  truths: RegionRef[]
  links: RegionRef[]
  /** 可选：填数结论（技巧类结构可能直接给出落子） */
  conclusion?: { idx: number; value: Digit }
  /** 可选：来源标记（秩搜索 / 技巧库映射） */
  source?: 'rank' | 'tech'
  /** 可选：来源名称（如 XYZ-Wing / UR） */
  sourceName?: string
  /** 可选：来源说明 */
  sourceDetail?: string
}

export type SearchProgress = {
  currentT: number
  exploredTruthSets: number
  found: number
}

export type SearchParams = {
  minT: number
  maxT: number
  maxResults?: number
}

export type SearchCache = {
  key: string
  candidates: Candidate[]
  truthOptions: TruthOption[]
  // candidate index -> its 3 house-link keys
  houseKeyRow: string[]
  houseKeyCol: string[]
  houseKeyBox: string[]
}

export function getOrBuildSearchCache(board: Board, existingCache?: SearchCache | null): SearchCache {
  const key = exportBoardStateKey(board)
  if (existingCache && existingCache.key === key) return existingCache

  const candidates: Candidate[] = []
  for (let idx = 0; idx < 81; idx++) {
    if (board[idx].value !== 0) continue
    const { r, c } = indexToRC(idx)
    const allowed = computeAllowedCandidates(board, idx)
    const box = Math.floor(r / 3) * 3 + Math.floor(c / 3)
    for (let d = 1 as Digit; d <= 9; d = (d + 1) as Digit) {
      if (!allowed[d]) continue
      const forb = board[idx].forbidden ?? emptyForbidden()
      if (forb[d]) continue
      candidates.push({ r, c, d, cellIdx: idx, box })
    }
  }

  const houseKeyRow = candidates.map((x) => `R:${x.r}:${x.d}`)
  const houseKeyCol = candidates.map((x) => `C:${x.c}:${x.d}`)
  const houseKeyBox = candidates.map((x) => `B:${x.box}:${x.d}`)

  const bitCount = candidates.length
  const truthOptions: TruthOption[] = []

  // cell truth options
  for (let idx = 0; idx < 81; idx++) {
    if (board[idx].value !== 0) continue
    const { r, c } = indexToRC(idx)
    const candBits = bitsetCreate(bitCount)
    const candIdxs: number[] = []
    let size = 0
    for (let i = 0; i < candidates.length; i++) {
      const cand = candidates[i]
      if (cand.r === r && cand.c === c) {
        bitsetSet(candBits, i)
        candIdxs.push(i)
        size++
      }
    }
    if (size === 0) continue
    truthOptions.push({
      ref: { type: 'cell', idx },
      candBits,
      candIdxs,
      forbid: 'cell',
      size,
    })
  }

  // row/col/box digit truth options
  const addHouseDigitTruth = (ref: RegionRef, predicate: (cand: Candidate) => boolean) => {
    const candBits = bitsetCreate(bitCount)
    const candIdxs: number[] = []
    let size = 0
    for (let i = 0; i < candidates.length; i++) {
      if (!predicate(candidates[i])) continue
      bitsetSet(candBits, i)
      candIdxs.push(i)
      size++
    }
    if (size === 0) return
    const forbid =
      ref.type === 'rowDigit'
        ? 'rowDigit'
        : ref.type === 'colDigit'
          ? 'colDigit'
          : 'boxDigit'
    truthOptions.push({ ref, candBits, candIdxs, forbid, size })
  }

  for (let row = 0; row < 9; row++) {
    for (let d = 1 as Digit; d <= 9; d = (d + 1) as Digit) {
      addHouseDigitTruth({ type: 'rowDigit', row, d }, (cand) => cand.r === row && cand.d === d)
    }
  }
  for (let col = 0; col < 9; col++) {
    for (let d = 1 as Digit; d <= 9; d = (d + 1) as Digit) {
      addHouseDigitTruth({ type: 'colDigit', col, d }, (cand) => cand.c === col && cand.d === d)
    }
  }
  for (let box = 0; box < 9; box++) {
    for (let d = 1 as Digit; d <= 9; d = (d + 1) as Digit) {
      addHouseDigitTruth({ type: 'boxDigit', box, d }, (cand) => cand.box === box && cand.d === d)
    }
  }

  // heuristics: smaller candidate sets first -> easier pruning
  truthOptions.sort((a, b) => a.size - b.size)

  return { key, candidates, truthOptions, houseKeyRow, houseKeyCol, houseKeyBox }
}

function linksForHouseKey(key: string): RegionRef {
  // key format: "R:row:d" | "C:col:d" | "B:box:d"
  const [t, a, b] = key.split(':')
  const numA = Number(a)
  const d = Number(b) as Digit
  if (t === 'R') return { type: 'rowDigit', row: numA, d }
  if (t === 'C') return { type: 'colDigit', col: numA, d }
  return { type: 'boxDigit', box: numA, d }
}

function linkRefFromKey(key: string): RegionRef {
  if (key.startsWith('N:')) {
    const idx = Number(key.split(':')[1])
    return { type: 'cell', idx }
  }
  return linksForHouseKey(key)
}

function yieldToBrowser(): Promise<void> {
  return new Promise((r) => setTimeout(r, 0))
}

export async function* searchRankStructures(
  board: Board,
  params: SearchParams,
  onProgress?: (p: SearchProgress) => void,
  signal?: AbortSignal,
  existingCache?: SearchCache,
): AsyncGenerator<FoundStructure, void, void> {
  const minT = Math.max(1, Math.floor(params.minT))
  const maxT = Math.max(minT, Math.floor(params.maxT))
  const maxResults = params.maxResults ?? Number.POSITIVE_INFINITY

  const cache = getOrBuildSearchCache(board, existingCache ?? null)
  const { candidates, truthOptions, houseKeyRow, houseKeyCol, houseKeyBox } = cache
  const bitCount = candidates.length

  let found = 0
  let exploredTruthSets = 0

  const usedTruth = new Array<boolean>(truthOptions.length).fill(false)

  const usedCandBits = bitsetCreate(bitCount)
  const chosenTruths: RegionRef[] = []
  const forbidByCand = new Array<number>(bitCount).fill(-1) // 0=cell 1=row 2=col 3=box

  function forbidCode(f: TruthOption['forbid']): number {
    if (f === 'cell') return 0
    if (f === 'rowDigit') return 1
    if (f === 'colDigit') return 2
    return 3
  }

  async function* enumerateTruths(startIdx: number, targetT: number): AsyncGenerator<RegionRef[], void, void> {
    if (signal?.aborted) return
    if (chosenTruths.length === targetT) {
      exploredTruthSets++
      if (exploredTruthSets % 200 === 0) {
        onProgress?.({ currentT: targetT, exploredTruthSets, found })
        await yieldToBrowser()
      }
      yield chosenTruths.slice()
      return
    }

    const remaining = targetT - chosenTruths.length
    for (let i = startIdx; i < truthOptions.length; i++) {
      if (signal?.aborted) return
      if (truthOptions.length - i < remaining) return
      if (usedTruth[i]) continue

      const opt = truthOptions[i]
      if (bitsetAndNonZero(usedCandBits, opt.candBits)) continue // Truth 不重叠

      // choose
      usedTruth[i] = true
      chosenTruths.push(opt.ref)
      const usedCandBefore = bitsetClone(usedCandBits)
      const forbidTouched = opt.candIdxs.slice()
      bitsetOrInto(usedCandBits, opt.candBits)
      const code = forbidCode(opt.forbid)
      for (const ci of forbidTouched) forbidByCand[ci] = code

      yield* enumerateTruths(i + 1, targetT)

      // undo
      chosenTruths.pop()
      usedTruth[i] = false
      for (let k = 0; k < usedCandBits.length; k++) usedCandBits[k] = usedCandBefore[k]
      for (const ci of forbidTouched) forbidByCand[ci] = -1
    }
  }

  function buildCoverMaps(bits: Bitset): {
    keyToCoverBits: Map<string, Bitset>
    candToOptions: Map<number, string[]>
  } {
    const keyToCoverBits = new Map<string, Bitset>()
    const candToOptions = new Map<number, string[]>()

    for (let i = 0; i < bitCount; i++) {
      if (!bitsetHas(bits, i)) continue
      const forbid = forbidByCand[i]
      const cellKey = `N:${candidates[i].cellIdx}`
      const rowKey = houseKeyRow[i]
      const colKey = houseKeyCol[i]
      const boxKey = houseKeyBox[i]
      const opts: string[] = []
      if (forbid !== 0) opts.push(cellKey)
      if (forbid !== 1) opts.push(rowKey)
      if (forbid !== 2) opts.push(colKey)
      if (forbid !== 3) opts.push(boxKey)
      candToOptions.set(i, opts)
      for (const k of opts) {
        let cover = keyToCoverBits.get(k)
        if (!cover) {
          cover = bitsetCreate(bitCount)
          keyToCoverBits.set(k, cover)
        }
        bitsetSet(cover, i)
      }
    }
    return { keyToCoverBits, candToOptions }
  }

  async function* enumerateLinkCovers(bits: Bitset, maxLinks: number): AsyncGenerator<string[], void, void> {
    if (signal?.aborted) return
    if (bitsetIsZero(bits)) {
      yield []
      return
    }
    const { keyToCoverBits, candToOptions } = buildCoverMaps(bits)
    const targetBits = bits

    const selected: string[] = []
    let covered = bitsetCreate(bitCount)
    const dedupe = new Set<string>()
    const allKeys = Array.from(keyToCoverBits.keys()).sort()

    async function* dfs(uncovered: Bitset, startExtraKeyIdx: number): AsyncGenerator<string[], void, void> {
      if (signal?.aborted) return
      if (selected.length > maxLinks) return

      if (bitsetIsZero(uncovered)) {
        // 覆盖已满足：允许继续加额外 Link（用于制造重叠从而产生 R>0 删数）
        const sorted = selected.slice().sort()
        const sig = sorted.join('|')
        if (!dedupe.has(sig)) {
          dedupe.add(sig)
          yield sorted
        }

        // 继续加 Link（最多加到 maxLinks），仅从“能覆盖 Truth 的候选”的 link key 集合中挑选
        if (selected.length === maxLinks) return
        for (let ki = startExtraKeyIdx; ki < allKeys.length; ki++) {
          if (signal?.aborted) return
          const k = allKeys[ki]
          if (selected.includes(k)) continue
          selected.push(k)
          const coveredBefore = bitsetClone(covered)
          bitsetOrInto(covered, keyToCoverBits.get(k)!)
          const nextUncovered = bitsetAndNot(targetBits, covered)
          if (selected.length % 24 === 0) await yieldToBrowser()
          yield* dfs(nextUncovered, ki + 1)
          selected.pop()
          covered = coveredBefore
        }
        return
      }

      const pick = bitsetPopFirst(uncovered)
      if (pick == null) return

      const opts = (candToOptions.get(pick) ?? []).slice().sort()
      for (const k of opts) {
        if (signal?.aborted) return
        const coverBits = keyToCoverBits.get(k)!
        if (!bitsetHas(coverBits, pick)) continue
        // add link k
        selected.push(k)
        const coveredBefore = bitsetClone(covered)
        bitsetOrInto(covered, coverBits)
        const nextUncovered = bitsetAndNot(targetBits, covered)
        if (selected.length % 24 === 0) await yieldToBrowser()
        yield* dfs(nextUncovered, 0)
        // undo
        selected.pop()
        covered = coveredBefore
      }
    }

    const initialUncovered = bitsetClone(bits)
    yield* dfs(initialUncovered, 0)
  }

  for (let targetT = minT; targetT <= maxT; targetT++) {
    if (signal?.aborted) break
    onProgress?.({ currentT: targetT, exploredTruthSets, found })
    for await (const truthRefs of enumerateTruths(0, targetT)) {
      if (signal?.aborted) break

      // 仅计算 R < 3（R=0/1/2）：允许 L <= T+2
      for await (const keys of enumerateLinkCovers(usedCandBits, targetT + 2)) {
        if (signal?.aborted) break
        const links = keys.map(linkRefFromKey)
        const T = truthRefs.length
        const L = links.length
        const R = L - T
        if (R < 0 || R > 2) continue
        found++
        const id = `${found}`
        yield { id, T, L, R, truths: truthRefs, links }
        if (found % 50 === 0) onProgress?.({ currentT: targetT, exploredTruthSets, found })
        if (found >= maxResults) return
        if (found % 10 === 0) await yieldToBrowser()
      }
    }
  }
}


