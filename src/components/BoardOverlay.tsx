import { useMemo } from 'react'
import type { Board } from '../lib/sudoku'
import type { RegionRef } from '../lib/rank'
import { resolveGroup } from '../lib/rank'
import { indexToRC } from '../lib/sudoku'

type GroupStyle = {
  kind: 'truth' | 'link'
  ref: RegionRef
  color: string
}

const palette = [
  '#175cd3', // blue
  '#067647', // green
  '#b42318', // red
  '#6941c6', // purple
  '#b54708', // orange
  '#344054', // dark
]

const BOARD_PAD = 2 // must match .board padding in CSS

function pointForCandidate(
  boardPx: number,
  r: number,
  c: number,
  d: number,
): { x: number; y: number } {
  const inner = Math.max(0, boardPx - BOARD_PAD * 2)
  const cell = inner / 9
  const rr = Math.floor((d - 1) / 3)
  const cc = (d - 1) % 3
  const x = BOARD_PAD + (c + (cc * 2 + 1) / 6) * cell
  const y = BOARD_PAD + (r + (rr * 2 + 1) / 6) * cell
  return { x, y }
}

function candKey(r: number, c: number, d: number): string {
  return `${r}-${c}-${d}`
}

function sign(x: number): number {
  return x < 0 ? -1 : 1
}

function clippedAxisSegment(
  a: { x: number; y: number },
  b: { x: number; y: number },
  axis: 'x' | 'y',
  clip: number,
): string {
  const dx = b.x - a.x
  const dy = b.y - a.y
  if (axis === 'x') {
    const dist = Math.abs(dx)
    if (dist <= clip * 2) return ''
    const sx = a.x + sign(dx) * clip
    const ex = b.x - sign(dx) * clip
    return `M ${sx.toFixed(2)} ${a.y.toFixed(2)} L ${ex.toFixed(2)} ${a.y.toFixed(2)}`
  }
  const dist = Math.abs(dy)
  if (dist <= clip * 2) return ''
  const sy = a.y + sign(dy) * clip
  const ey = b.y - sign(dy) * clip
  return `M ${a.x.toFixed(2)} ${sy.toFixed(2)} L ${a.x.toFixed(2)} ${ey.toFixed(2)}`
}

function buildClippedOrthPath(points: { x: number; y: number }[], clip: number): string {
  if (points.length === 0) return ''
  const pts = points.slice().sort((a, b) => (a.y - b.y) || (a.x - b.x))
  const segs: string[] = []
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1]
    const b = pts[i]
    const dx = b.x - a.x
    const dy = b.y - a.y
    if (dx === 0 || dy === 0) {
      segs.push(clippedAxisSegment(a, b, dx === 0 ? 'y' : 'x', clip))
      continue
    }

    // 选择拐点方向：尽量让第一段有足够长度（避免被 clip 吃掉导致“断线”）
    const horizFirstOk = Math.abs(dx) > clip * 2
    const vertFirstOk = Math.abs(dy) > clip * 2
    const horizFirst = horizFirstOk && (!vertFirstOk || Math.abs(dx) >= Math.abs(dy))
    if (horizFirst) {
      const corner = { x: b.x, y: a.y }
      // 第一段：从 a 到 corner（只在起点做裁剪，corner 不是候选圆心）
      const sx = a.x + sign(dx) * clip
      const ex = corner.x
      if (Math.abs(ex - sx) > 0.5) segs.push(`M ${sx.toFixed(2)} ${a.y.toFixed(2)} L ${ex.toFixed(2)} ${a.y.toFixed(2)}`)
      // 第二段：从 corner 到 b（只在终点做裁剪）
      const sy = corner.y
      const ey = b.y - sign(dy) * clip
      if (Math.abs(ey - sy) > 0.5) segs.push(`M ${corner.x.toFixed(2)} ${sy.toFixed(2)} L ${corner.x.toFixed(2)} ${ey.toFixed(2)}`)
    } else {
      const corner = { x: a.x, y: b.y }
      const sy = a.y + sign(dy) * clip
      const ey = corner.y
      if (Math.abs(ey - sy) > 0.5) segs.push(`M ${a.x.toFixed(2)} ${sy.toFixed(2)} L ${a.x.toFixed(2)} ${ey.toFixed(2)}`)
      const sx = corner.x
      const ex = b.x - sign(dx) * clip
      if (Math.abs(ex - sx) > 0.5) segs.push(`M ${sx.toFixed(2)} ${corner.y.toFixed(2)} L ${ex.toFixed(2)} ${corner.y.toFixed(2)}`)
    }
  }
  return segs.filter(Boolean).join(' ')
}

function cellRects(boardPx: number, idx: number): { outer: any; inner: any } {
  const inner = Math.max(0, boardPx - BOARD_PAD * 2)
  const cell = inner / 9
  const { r, c } = indexToRC(idx)
  const x0 = BOARD_PAD + c * cell
  const y0 = BOARD_PAD + r * cell
  const padOuter = cell * 0.12
  const padInner = cell * 0.20
  return {
    outer: { x: x0 + padOuter, y: y0 + padOuter, w: cell - padOuter * 2, h: cell - padOuter * 2 },
    inner: { x: x0 + padInner, y: y0 + padInner, w: cell - padInner * 2, h: cell - padInner * 2 },
  }
}

export function truthCellSet(truths: RegionRef[]): Set<number> {
  const set = new Set<number>()
  for (const t of truths) if (t.type === 'cell') set.add(t.idx)
  return set
}

export function BoardOverlay({
  board,
  boardPx,
  truths,
  links,
  deletions,
}: {
  board: Board
  boardPx: number
  truths: RegionRef[]
  links: RegionRef[]
  deletions: Array<{ r: number; c: number; d: number }>
}) {
  const truthCovered = useMemo(() => {
    const set = new Set<string>()
    for (const t of truths) {
      for (const n of resolveGroup(board, t)) set.add(candKey(n.r, n.c, n.d))
    }
    return set
  }, [board, truths])

  const styles: GroupStyle[] = useMemo(() => {
    const out: GroupStyle[] = []
    let pi = 0
    for (const t of truths) {
      if (t.type === 'cell') continue
      out.push({ kind: 'truth', ref: t, color: palette[pi++ % palette.length] })
    }
    pi = 0
    for (const l of links) {
      if (l.type === 'cell') continue
      out.push({ kind: 'link', ref: l, color: palette[(pi++ + 2) % palette.length] })
    }
    return out
  }, [truths, links])

  const linkCellIdxs = useMemo(() => links.filter((x) => x.type === 'cell').map((x) => x.idx), [links])

  if (boardPx <= 0) return null

  const innerSize = Math.max(0, boardPx - BOARD_PAD * 2)
  const cellSize = innerSize / 9
  const candRadius = Math.max(5.5, cellSize * 0.16)
  const linkDash = Math.max(8, cellSize * 0.22)
  const linkGap = Math.max(6, cellSize * 0.18)

  return (
    <svg
      className="boardOverlay"
      width={boardPx}
      height={boardPx}
      viewBox={`0 0 ${boardPx} ${boardPx}`}
      style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
    >
      {/* Deletions: red circles around deletable candidates */}
      {deletions.map((m, i) => {
        const p = pointForCandidate(boardPx, m.r, m.c, m.d)
        const radius = candRadius
        return (
          <g key={`del-${i}`}>
            {/* 实心红圈：半透明填充 + 描边，尽量不遮挡数字 */}
            <circle cx={p.x} cy={p.y} r={radius} fill="#b42318" opacity="0.28" />
            <circle cx={p.x} cy={p.y} r={radius} fill="none" stroke="#b42318" strokeWidth="2.0" opacity="0.9" />
          </g>
        )
      })}

      {/* Link: cell double boxes */}
      {linkCellIdxs.map((idx) => {
        const { outer, inner } = cellRects(boardPx, idx)
        return (
          <g key={`lc-${idx}`}>
            <rect
              x={outer.x}
              y={outer.y}
              width={outer.w}
              height={outer.h}
              rx={6}
              ry={6}
              fill="none"
              stroke="#175cd3"
              strokeWidth="2"
              opacity="0.9"
            />
            <rect
              x={inner.x}
              y={inner.y}
              width={inner.w}
              height={inner.h}
              rx={5}
              ry={5}
              fill="none"
              stroke="#175cd3"
              strokeWidth="2"
              opacity="0.55"
            />
          </g>
        )
      })}

      {/* House-digit groups: lines */}
      {styles.map((g, i) => {
        const nodes = resolveGroup(board, g.ref)
        const isTruth = g.kind === 'truth'
        const shownNodes = isTruth ? nodes : nodes.filter((n) => truthCovered.has(candKey(n.r, n.c, n.d)))
        const pts = shownNodes.map((n) => pointForCandidate(boardPx, n.r, n.c, n.d))
        const d = buildClippedOrthPath(pts, candRadius + 1.5)
        if (!d) return null
        if (isTruth) {
          return (
            <g key={`t-${i}`}>
              <path
                d={d}
                fill="none"
                stroke={g.color}
                strokeWidth="3.1"
                strokeLinecap="round"
                strokeLinejoin="round"
                opacity="0.82"
              />
              {/* 强区域候选点：逐个圈出（不填充，避免遮挡） */}
              {shownNodes.map((n, j) => {
                const p = pointForCandidate(boardPx, n.r, n.c, n.d)
                return (
                  <circle
                    key={`tc-${i}-${j}`}
                    cx={p.x}
                    cy={p.y}
                    r={candRadius}
                    fill="none"
                    stroke={g.color}
                    strokeWidth="1.8"
                    opacity="0.9"
                  />
                )
              })}
            </g>
          )
        }
        // link: single dashed, only show candidates that are also within Truth-covered set; no candidate circles
        return (
          <g key={`l-${i}`}>
            <path
              d={d}
              fill="none"
              stroke={g.color}
              strokeWidth="1.5"
              strokeDasharray={`${linkDash} ${linkGap}`}
              strokeLinecap="butt"
              strokeLinejoin="round"
              opacity="0.78"
            />
          </g>
        )
      })}
    </svg>
  )
}


