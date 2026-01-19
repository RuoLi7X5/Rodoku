import { useMemo } from 'react'
import type { Board, Digit } from '../lib/sudoku'
import { computeConflicts, indexToRC } from '../lib/sudoku'

type CandidateMarkClass = string // e.g. "mk0".."mk7"

function CandidateGrid({
  candidates,
  highlightRemoved,
  candidateMarks,
}: {
  candidates: boolean[]
  highlightRemoved?: Set<Digit>
  candidateMarks?: Map<Digit, CandidateMarkClass>
}) {
  return (
    <div className="candGrid" aria-hidden="true">
      {Array.from({ length: 9 }, (_, k) => {
        const d = (k + 1) as Digit
        const isShown = candidates[d]
        const isRemoved = highlightRemoved?.has(d) ?? false
        const mk = candidateMarks?.get(d)
        return (
          <div key={d} className={'cand' + (isShown ? ' isPickable' : '') + (isRemoved ? ' isRemoved' : '')}>
            {isShown ? (mk ? <span className={'candDot ' + mk}>{d}</span> : d) : isRemoved ? <span className="delDot">{d}</span> : ''}
          </div>
        )
      })}
    </div>
  )
}

export function RodokuBoard({
  board,
  highlightElims,
  cellMarks,
  candidateMarks,
}: {
  board: Board
  highlightElims?: Map<number, Set<Digit>>
  // cell background marks (e.g. strong/weak)
  cellMarks?: Map<number, 'strong' | 'weak'>
  // per-cell candidate marks: idx -> (digit -> class)
  candidateMarks?: Map<number, Map<Digit, CandidateMarkClass>>
}) {
  const conflicts = useMemo(() => computeConflicts(board), [board])

  return (
    <div className="boardWrap" aria-label="Rodoku 盘面">
      <div className="board" role="grid" aria-label="数独盘面">
        {board.map((cell, idx) => {
          const { r, c } = indexToRC(idx)
          const givenCls = cell.given ? ' isGiven' : ''
          const conflictCls = conflicts[idx] ? ' isConflict' : ''
          const mark = cellMarks?.get(idx)
          const markCls = mark === 'strong' ? ' isStrongCell' : mark === 'weak' ? ' isWeakCell' : ''
          const thickTop = r % 3 === 0 ? ' thickTop' : ''
          const thickLeft = c % 3 === 0 ? ' thickLeft' : ''
          const thickRight = c === 8 ? ' thickRight' : ''
          const thickBottom = r === 8 ? ' thickBottom' : ''
          return (
            <div
              key={idx}
              className={'cell' + givenCls + conflictCls + markCls + thickTop + thickLeft + thickRight + thickBottom}
              role="gridcell"
              aria-selected={false}
              data-rc={`${r + 1}-${c + 1}`}
              style={cell.cellColor ? { backgroundColor: '#fff' } : undefined}
            >
              {cell.value !== 0 ? (
                <span className={cell.given ? 'value given' : 'value user'}>{cell.value}</span>
              ) : (
                <CandidateGrid
                  candidates={cell.candidates}
                  highlightRemoved={highlightElims?.get(idx)}
                  candidateMarks={candidateMarks?.get(idx)}
                />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

