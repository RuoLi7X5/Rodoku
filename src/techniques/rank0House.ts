import type { Board, Digit } from '../lib/sudoku'
import { rcToIndex } from '../lib/sudoku'
import type { CandidateNode, RegionRef } from '../lib/rank'
import { candidateId, resolveGroup } from '../lib/rank'
import type { TechniqueResult } from './types'

type House =
  | { kind: 'row'; r: number }
  | { kind: 'col'; c: number }
  | { kind: 'box'; b: number }

function boxOf(r: number, c: number): number {
  return Math.floor(r / 3) * 3 + Math.floor(c / 3)
}

function inHouse(h: House, n: CandidateNode): boolean {
  if (h.kind === 'row') return n.r === h.r
  if (h.kind === 'col') return n.c === h.c
  return boxOf(n.r, n.c) === h.b
}

function houseLabel(h: House): string {
  if (h.kind === 'row') return `r${h.r + 1}`
  if (h.kind === 'col') return `c${h.c + 1}`
  return `b${h.b + 1}`
}

function allHouses(): House[] {
  const hs: House[] = []
  for (let i = 0; i < 9; i++) {
    hs.push({ kind: 'row', r: i })
    hs.push({ kind: 'col', c: i })
    hs.push({ kind: 'box', b: i })
  }
  return hs
}

function refKey(ref: RegionRef): string {
  if (ref.type === 'cell') return `cell:${ref.idx}`
  if (ref.type === 'rowDigit') return `row:${ref.row}:${ref.d}`
  if (ref.type === 'colDigit') return `col:${ref.col}:${ref.d}`
  return `box:${ref.box}:${ref.d}`
}

function enumerateRegionRefs(): RegionRef[] {
  const out: RegionRef[] = []
  for (let idx = 0; idx < 81; idx++) out.push({ type: 'cell', idx })
  for (let row = 0; row < 9; row++) {
    for (let d = 1 as Digit; d <= 9; d = (d + 1) as Digit) out.push({ type: 'rowDigit', row, d })
  }
  for (let col = 0; col < 9; col++) {
    for (let d = 1 as Digit; d <= 9; d = (d + 1) as Digit) out.push({ type: 'colDigit', col, d })
  }
  for (let box = 0; box < 9; box++) {
    for (let d = 1 as Digit; d <= 9; d = (d + 1) as Digit) out.push({ type: 'boxDigit', box, d })
  }
  return out
}

type RefInfo = {
  ref: RegionRef
  key: string
  type: RegionRef['type']
  nodes: CandidateNode[]
  ids: Set<string>
  size: number
}

function buildRefInfos(board: Board): RefInfo[] {
  const refs = enumerateRegionRefs()
  const out: RefInfo[] = []
  for (const ref of refs) {
    const nodes = resolveGroup(board, ref)
    if (nodes.length === 0) continue
    const ids = new Set(nodes.map(candidateId))
    out.push({ ref, key: refKey(ref), type: ref.type, nodes, ids, size: nodes.length })
  }
  return out
}

function isDisjoint(a: Set<string>, b: Set<string>): boolean {
  for (const x of a) if (b.has(x)) return false
  return true
}

function unionInto(dst: Set<string>, src: Set<string>): void {
  for (const x of src) dst.add(x)
}

function diffIds(a: Set<string>, b: Set<string>): string[] {
  const out: string[] = []
  for (const x of a) if (!b.has(x)) out.push(x)
  return out
}

function nodeFromId(id: string): { r: number; c: number; d: Digit } {
  // candidateId: `${r}${c}${d}` where r,c are 0..8, d is 1..9
  const r = Number(id[0])
  const c = Number(id[1])
  const d = Number(id[2]) as Digit
  return { r, c, d }
}

function cellKeyOfCandId(id: string): string {
  // `${r}${c}${d}` -> `${r}${c}`（唯一单元格定位）
  return `${id[0]}${id[1]}`
}

export type GenOptions = {
  m: number
  techId: string
  techName: string
  /** 每个 house 最多产出多少条结果，避免爆炸 */
  maxPerHouse?: number
}

export function generateRank0InSingleHouse(board: Board, opts: GenOptions): TechniqueResult[] {
  const m = opts.m
  const out: TechniqueResult[] = []
  const infos = buildRefInfos(board)
  const byHouse: Array<{ house: House; truths: RefInfo[]; links: RefInfo[] }> = []

  // 预分组：只保留“节点完全落在该 house 内”的 ref（否则不符合你定义的‘同一行列宫内’）
  for (const h of allHouses()) {
    const inside = infos.filter((ri) => ri.nodes.every((n) => inHouse(h, n)))
    // Truth/Link 可共用同一候选 ref 集合；最终会再应用“类型不相同”等约束
    byHouse.push({ house: h, truths: inside, links: inside })
  }

  for (const { house, truths, links } of byHouse) {
    if (opts.maxPerHouse != null && out.length >= opts.maxPerHouse * 27) break
    const houseOut: TechniqueResult[] = []

    // truths：优先小集合，减少组合
    const truthOpts = truths
      .slice()
      .sort((a, b) => a.size - b.size || a.key.localeCompare(b.key))
      .slice(0, m >= 3 ? 120 : 100000) // m>=3 轻微限流（技巧是加速器，rank 搜索仍是完整枚举）

    const pickTruths: RefInfo[] = []
    const usedTruthIds = new Set<string>()
    const truthTypeOf = new Map<string, RegionRef['type']>() // candId -> truthRef.type

    const dfsTruth = (start: number) => {
      if (opts.maxPerHouse != null && houseOut.length >= opts.maxPerHouse) return
      if (pickTruths.length === m) {
        // 构造 truth union
        const truthIds = new Set<string>()
        for (const t of pickTruths) unionInto(truthIds, t.ids)
        if (truthIds.size === 0) return

        // 关键约束（你新增的定义）：
        // m 个 Truth 覆盖到的所有候选，必须“只分布在 m 个单元格”里。
        // - 数对：2T -> 恰好 2 个单元格
        // - 三数组：3T -> 恰好 3 个单元格
        // - 4数组：4T -> 恰好 4 个单元格
        if (m >= 2) {
          const cellSet = new Set<string>()
          for (const id of truthIds) cellSet.add(cellKeyOfCandId(id))
          if (cellSet.size !== m) return
        }

        // link 候选：必须与其覆盖到的 truth cand 的 truth-type 不同；并且必须覆盖至少一个 truth cand
        const linkOpts: Array<{
          info: RefInfo
          cover: Set<string> // truth cand ids covered by this link
        }> = []

        for (const li of links) {
          // 覆盖集合
          const cover = new Set<string>()
          let bad = false
          for (const id of li.ids) {
            if (!truthIds.has(id)) continue
            const tt = truthTypeOf.get(id)
            if (tt && tt === li.type) {
              bad = true
              break
            }
            cover.add(id)
          }
          if (bad) continue
          if (cover.size === 0) continue
          linkOpts.push({ info: li, cover })
        }

        // 覆盖搜索：选 m 个 link 使 union(cover)=truthIds
        linkOpts.sort((a, b) => b.cover.size - a.cover.size)

        const pickedLinks: RefInfo[] = []
        const covered = new Set<string>()

        const dfsLink = (startL: number) => {
          if (opts.maxPerHouse != null && houseOut.length >= opts.maxPerHouse) return
          if (pickedLinks.length === m) {
            if (covered.size !== truthIds.size) return
            // 生成删数：union(link nodes) - union(truth nodes)
            const linkAll = new Set<string>()
            for (const l of pickedLinks) unionInto(linkAll, l.ids)
            const dels = diffIds(linkAll, truthIds)
            if (dels.length === 0) return

            const eliminations = dels.map((id) => {
              const n = nodeFromId(id)
              return { idx: rcToIndex(n.r, n.c), d: n.d as Digit }
            })

            houseOut.push({
              techniqueId: opts.techId,
              techniqueName: opts.techName,
              eliminations,
              detail: `同一${houseLabel(house)}内的 R0 结构（m=${m}）`,
              rankStructure: {
                truths: pickTruths.map((x) => x.ref),
                links: pickedLinks.map((x) => x.ref),
                T: m,
                L: m,
                R: 0,
              },
            })
            return
          }

          // 贪心剪枝：剩余 link 数不足
          const remainSlots = m - pickedLinks.length
          if (linkOpts.length - startL < remainSlots) return

          // 找一个未覆盖 truth cand
          let target: string | null = null
          for (const id of truthIds) {
            if (!covered.has(id)) {
              target = id
              break
            }
          }
          if (!target) return

          for (let i = startL; i < linkOpts.length; i++) {
            const { info, cover } = linkOpts[i]
            if (!cover.has(target)) continue // 必须推进覆盖
            // 选入
            pickedLinks.push(info)
            const added: string[] = []
            for (const id of cover) {
              if (!covered.has(id)) {
                covered.add(id)
                added.push(id)
              }
            }
            dfsLink(i + 1)
            // 回溯
            for (const id of added) covered.delete(id)
            pickedLinks.pop()
            if (opts.maxPerHouse != null && houseOut.length >= opts.maxPerHouse) return
          }
        }

        dfsLink(0)
        return
      }

      for (let i = start; i < truthOpts.length; i++) {
        const t = truthOpts[i]
        if (!isDisjoint(usedTruthIds, t.ids)) continue
        pickTruths.push(t)
        for (const id of t.ids) {
          usedTruthIds.add(id)
          truthTypeOf.set(id, t.type)
        }
        dfsTruth(i + 1)
        // 回溯
        for (const id of t.ids) {
          usedTruthIds.delete(id)
          truthTypeOf.delete(id)
        }
        pickTruths.pop()
        if (opts.maxPerHouse != null && houseOut.length >= opts.maxPerHouse) return
      }
    }

    dfsTruth(0)
    out.push(...houseOut)
  }

  return out
}


