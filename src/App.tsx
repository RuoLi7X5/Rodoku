import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './sudoku.css'
import type { Digit } from './lib/sudoku'
import {
  clearAllCandidates,
  clearCellCandidates,
  computeConflicts,
  createEmptyBoard,
  exportPuzzleString,
  fillAllCandidates,
  indexToRC,
  rcToIndex,
  setCellValue,
  toggleCellCandidate,
  validateGivenBoard,
} from './lib/sudoku'
import type { MarkColor } from './lib/sudoku'
import { IconButton } from './components/IconButton'
import { Modal } from './components/Modal'
import { IconCandidates, IconExport, IconImage, IconImport, IconSparkle, IconTrash } from './components/icons'
import type { RegionRef } from './lib/rank'
import type { FoundStructure, SearchCache, SearchProgress } from './lib/rankSearch'
import { getOrBuildSearchCache, searchRankStructures } from './lib/rankSearch'
import { BoardOverlay, truthCellSet } from './components/BoardOverlay'
import { computeDeletableCandidates } from './lib/rankDeductions'
import { applyCandidateEliminations } from './lib/sudoku'
import { solveBoardFast } from './lib/solver'
import { parsePuzzleInput } from './lib/importPuzzle'

type Mode = 'value' | 'candidate'
type MenuKey = 'file' | 'edit' | 'rank' | 'settings' | 'help'
type PickedCandidate = { idx: number; d: Digit } | null

function CandidateGrid({
  candidates,
  candidateColors,
  cellIdx,
  picked,
  onPick,
}: {
  candidates: boolean[]
  candidateColors?: (MarkColor | null)[] | null
  cellIdx: number
  picked: PickedCandidate
  onPick: (idx: number, d: Digit) => void
}) {
  return (
    <div className="candGrid" aria-hidden="true">
      {Array.from({ length: 9 }, (_, k) => {
        const d = (k + 1) as Digit
        const c = candidateColors?.[d] ?? null
        const isShown = candidates[d]
        const isPicked = picked?.idx === cellIdx && picked.d === d
        return (
          <div
            key={d}
            className={'cand' + (isShown ? ' isPickable' : '') + (isPicked ? ' isPicked' : '')}
            style={c ? { color: colorToText(c) } : undefined}
            onClick={(e) => {
              e.stopPropagation()
              if (!isShown) return
              onPick(cellIdx, d)
            }}
          >
            {isShown ? d : ''}
          </div>
        )
      })}
    </div>
  )
}

function colorToText(c: MarkColor): string {
  if (c === 'red') return '#b42318'
  if (c === 'orange') return '#b54708'
  if (c === 'yellow') return '#b54708'
  if (c === 'green') return '#067647'
  if (c === 'blue') return '#175cd3'
  return '#6941c6'
}

function colorToBg(c: MarkColor): string {
  if (c === 'red') return '#fff1f3'
  if (c === 'orange') return '#fff6ed'
  if (c === 'yellow') return '#fffaeb'
  if (c === 'green') return '#ecfdf3'
  if (c === 'blue') return '#eff8ff'
  return '#f4f3ff'
}

export default function App() {
  const [board, setBoard] = useState(() => createEmptyBoard())
  const [selected, setSelected] = useState<number | null>(null)
  const [mode, setMode] = useState<Mode>('value')
  const [activeMenu, setActiveMenu] = useState<MenuKey>('file')
  const [modal, setModal] = useState<'import' | 'export' | null>(null)
  const [ioText, setIoText] = useState<string>(
    '000539002009000000400001809190080003000163290200905100001350984300090600980014007',
  )
  const [ioError, setIoError] = useState<string>('')
  const [solveStatus, setSolveStatus] = useState<'unknown' | 'unique' | 'multiple'>('unknown')
  const [solution, setSolution] = useState<Digit[] | null>(null)
  const [solutionKey, setSolutionKey] = useState<string>('')
  const [picked, setPicked] = useState<PickedCandidate>(null)
  const digitsKey = useMemo(() => exportPuzzleString(board), [board])

  // 秩结构查询状态
  const [tMin, setTMin] = useState<number>(1)
  const [tMax, setTMax] = useState<number>(8)
  const [isSearching, setIsSearching] = useState<boolean>(false)
  const [progress, setProgress] = useState<SearchProgress | null>(null)
  const [results, setResults] = useState<FoundStructure[]>([])
  const [selectedDelSig, setSelectedDelSig] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const cacheRef = useRef<SearchCache | null>(null)

  function delSigOf(ms: Array<{ idx: number; d: number }>): string {
    return ms
      .map((m) => `${m.d}@${m.idx}`)
      .sort()
      .join(',')
  }

  function compressDeletionSummary(ms: Array<{ idx: number; d: Digit }>): string {
    if (ms.length === 0) return ''
    // group by digit+col -> rows
    const byCol = new Map<string, number[]>()
    const byRow = new Map<string, number[]>()
    for (const m of ms) {
      const r = Math.floor(m.idx / 9) + 1
      const c = (m.idx % 9) + 1
      const k1 = `${m.d}|c|${c}`
      const k2 = `${m.d}|r|${r}`
      byCol.set(k1, (byCol.get(k1) ?? []).concat(r))
      byRow.set(k2, (byRow.get(k2) ?? []).concat(c))
    }
    const parts: string[] = []
    const used = new Set<string>()

    // prefer compressing same digit in same column across multiple rows
    for (const [k, rows] of byCol.entries()) {
      const [dStr, , cStr] = k.split('|')
      const d = Number(dStr) as Digit
      const c = Number(cStr)
      const uniqRows = Array.from(new Set(rows)).sort((a, b) => a - b)
      if (uniqRows.length >= 2) {
        const rowStr = uniqRows.join('')
        parts.push(`r${rowStr}c${c}<>${d}`)
        for (const rr of uniqRows) used.add(`${rr}-${c}-${d}`)
      }
    }

    // then compress same digit in same row across multiple cols
    for (const [k, cols] of byRow.entries()) {
      const [dStr, , rStr] = k.split('|')
      const d = Number(dStr) as Digit
      const r = Number(rStr)
      const uniqCols = Array.from(new Set(cols)).sort((a, b) => a - b)
      const remaining = uniqCols.filter((c) => !used.has(`${r}-${c}-${d}`))
      if (remaining.length >= 2) {
        parts.push(`r${r}c${remaining.join('')}<>${d}`)
        for (const cc of remaining) used.add(`${r}-${cc}-${d}`)
      }
    }

    // fallback singles
    for (const m of ms) {
      const r = Math.floor(m.idx / 9) + 1
      const c = (m.idx % 9) + 1
      const d = m.d
      if (used.has(`${r}-${c}-${d}`)) continue
      parts.push(`r${r}c${c}<>${d}`)
      used.add(`${r}-${c}-${d}`)
    }
    return parts.join(' ')
  }

  const visibleItems = useMemo(() => {
    const out: Array<{
      struct: FoundStructure
      delSig: string
      dels: Array<{ idx: number; d: Digit }>
      summary: string
    }> = []
    const seen = new Set<string>()
    const canGuide = solution != null && solutionKey === digitsKey

    for (const st of results) {
      const delsAll = computeDeletableCandidates(board, st)
      if (delsAll.length === 0) continue
      const dels = (canGuide ? delsAll.filter((m) => solution![m.idx] !== m.d) : delsAll) as Array<{
        idx: number
        d: Digit
      }>
      if (dels.length === 0) continue
      const sig = delSigOf(dels)
      if (seen.has(sig)) continue // 同删数去重
      seen.add(sig)
      out.push({ struct: st, delSig: sig, dels, summary: compressDeletionSummary(dels) })
    }
    return out
  }, [board, digitsKey, results, solution, solutionKey])

  const selectedItem = useMemo(
    () => (selectedDelSig ? visibleItems.find((x) => x.delSig === selectedDelSig) ?? null : null),
    [selectedDelSig, visibleItems],
  )

  const selectedStruct = selectedItem?.struct ?? null
  const selectedDeletions = selectedItem?.dels ?? []

  const selectedTruthCellIdx = useMemo(
    () => (selectedStruct ? truthCellSet(selectedStruct.truths) : new Set<number>()),
    [selectedStruct],
  )

  // board overlay size
  const boardRef = useRef<HTMLDivElement | null>(null)
  const [boardPx, setBoardPx] = useState<number>(0)

  useEffect(() => {
    const el = boardRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      const rect = el.getBoundingClientRect()
      setBoardPx(Math.min(rect.width, rect.height))
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // 换题（数字盘面变化）清空缓存与结果（候选删除 forbidden 变化不清空：便于“应用后保留列表”）
  useEffect(() => {
    if (isSearching) return
    setResults([])
    setSelectedDelSig(null)
    setProgress(null)
    cacheRef.current = null
  }, [digitsKey])

  // 若盘面数字发生变化（非仅 forbidden），则当前保存的解可能失效：查询时会按需重新求解

  const conflicts = useMemo(() => computeConflicts(board), [board])
  const selectedCell = selected == null ? null : board[selected]

  const setValue = useCallback(
    (idx: number, v: Digit | 0) => {
      setBoard((prev) => setCellValue(prev, idx, v))
    },
    [setBoard],
  )

  const toggleCandidate = useCallback((idx: number, d: Digit) => {
    setBoard((prev) => toggleCellCandidate(prev, idx, d))
  }, [])

  const clearAll = useCallback(() => {
    setBoard(createEmptyBoard())
    setSelected(null)
  }, [])

  const importPuzzle = useCallback(() => {
    const parsed = parsePuzzleInput(ioText)
    if (!parsed) {
      setIoError('格式错误：支持 81位(0/./空格) 或 特殊 :...:...:: 格式。')
      return
    }
    // 校验：题目本身也必须满足基本规则（不允许行/列/宫重复）
    if (!validateGivenBoard(parsed.board)) {
      setIoError('题目不合法：存在行/列/宫重复数字。')
      return
    }
    const solved = solveBoardFast(parsed.board, 2)
    if (solved.status === 'none') {
      setIoError('题目无解：不予导入。')
      return
    }
    setBoard(parsed.board)
    setSelected(null)
    setIoError('')
    setModal(null)
    setSolution(solved.solution)
    setSolutionKey(solved.key)
    setSolveStatus(solved.status === 'unique' ? 'unique' : 'multiple')
  }, [ioText])

  const exportPuzzle = useCallback(() => {
    setIoText(exportPuzzleString(board))
  }, [board])

  const doFullMark = useCallback(() => {
    setBoard((prev) => fillAllCandidates(prev))
  }, [])

  const doClearAllCandidates = useCallback(() => {
    setBoard((prev) => clearAllCandidates(prev))
  }, [])

  const doDelete = useCallback(() => {
    if (selected == null) return
    if (mode === 'value') setBoard((prev) => setCellValue(prev, selected, 0))
    else setBoard((prev) => clearCellCandidates(prev, selected))
  }, [mode, selected])

  const onPickCandidate = useCallback((idx: number, d: Digit) => {
    setSelected(idx)
    setPicked({ idx, d })
  }, [])

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (selected == null) return
      const key = e.key
      if (key >= '1' && key <= '9') {
        const d = Number(key) as Digit
        if (mode === 'value') setValue(selected, d)
        else toggleCandidate(selected, d)
        e.preventDefault()
      } else if (key === 'Backspace' || key === 'Delete' || key === '0') {
        if (mode === 'value') setValue(selected, 0)
        else setBoard((prev) => clearCellCandidates(prev, selected))
        e.preventDefault()
      } else if (key === ' ') {
        setMode((m) => (m === 'value' ? 'candidate' : 'value'))
        e.preventDefault()
      } else if (key.startsWith('Arrow')) {
        const { r, c } = indexToRC(selected)
        let nr = r
        let nc = c
        if (key === 'ArrowUp') nr = Math.max(0, r - 1)
        if (key === 'ArrowDown') nr = Math.min(8, r + 1)
        if (key === 'ArrowLeft') nc = Math.max(0, c - 1)
        if (key === 'ArrowRight') nc = Math.min(8, c + 1)
        setSelected(rcToIndex(nr, nc))
        e.preventDefault()
      }
    },
    [mode, selected, setValue, toggleCandidate],
  )

  const canDelete =
    selected != null &&
    selectedCell != null &&
    !selectedCell.given &&
    (mode === 'value' ? selectedCell.value !== 0 : selectedCell.value === 0)

  const menuDefs: { key: MenuKey; label: string }[] = [
    { key: 'file', label: '文件' },
    { key: 'edit', label: '编辑' },
    { key: 'rank', label: '秩查询' },
    { key: 'settings', label: '设置' },
    { key: 'help', label: '帮助' },
  ]

  function formatRef(ref: RegionRef, kind: 'truth' | 'link'): string {
    const up = kind === 'truth'
    if (ref.type === 'cell') {
      const { r, c } = indexToRC(ref.idx)
      return `${r + 1}${up ? 'N' : 'n'}${c + 1}`
    }
    if (ref.type === 'rowDigit') return `${ref.d}${up ? 'R' : 'r'}${ref.row + 1}`
    if (ref.type === 'colDigit') return `${ref.d}${up ? 'C' : 'c'}${ref.col + 1}`
    return `${ref.d}${up ? 'B' : 'b'}${ref.box + 1}`
  }

  function formatStructureDetail(s: FoundStructure): string {
    const tStr = s.truths.map((r) => formatRef(r, 'truth')).join('-')
    const lStr = s.links.map((r) => formatRef(r, 'link')).join(' ')
    return `T${s.T}=${tStr}\nL${s.L}={${lStr}}\nrank ${s.R}`
  }

  const startSearch = useCallback(async () => {
    if (isSearching) return
    const minT = Math.max(1, Math.floor(tMin))
    const maxT = Math.max(minT, Math.floor(tMax))

    // 确保有用于导航的解（基于当前数字盘面，不依赖 forbidden）
    const digitsKeyNow = exportPuzzleString(board)
    let sol = solution
    let solStatus = solveStatus
    if (!sol || solutionKey !== digitsKeyNow) {
      const solved = solveBoardFast(board, 2)
      if (solved.status === 'none') {
        setProgress(null)
        setResults([])
        setSelectedDelSig(null)
        setIsSearching(false)
        setSolveStatus('unknown')
        setSolution(null)
        setSolutionKey('')
        return
      }
      sol = solved.solution
      solStatus = solved.status === 'unique' ? 'unique' : 'multiple'
      setSolution(sol)
      setSolutionKey(solved.key)
      setSolveStatus(solStatus)
    }

    setResults([])
    setSelectedDelSig(null)
    setProgress({ currentT: minT, exploredTruthSets: 0, found: 0 })
    setIsSearching(true)

    const ac = new AbortController()
    abortRef.current = ac

    try {
      const cache = getOrBuildSearchCache(board, cacheRef.current)
      cacheRef.current = cache
      const gen = searchRankStructures(
        board,
        { minT, maxT },
        (p) => setProgress(p),
        ac.signal,
        cache,
      )
      for await (const st of gen) {
        if (ac.signal.aborted) break
        // 只展示“有删数”的结构
        const delsAll = computeDeletableCandidates(board, st)
        if (delsAll.length === 0) continue
        // 用解做导航：仅保留能删掉“与解不一致”的候选
        const dels = delsAll.filter((m) => sol![m.idx] !== m.d)
        if (dels.length === 0) continue
        setResults((prev) => prev.concat(st))
      }
    } finally {
      setIsSearching(false)
      abortRef.current = null
    }
  }, [board, isSearching, solveStatus, solution, solutionKey, tMax, tMin])

  const stopSearch = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  return (
    <div className="page" onKeyDown={onKeyDown} tabIndex={0}>
      <div className="topBar">
        <div className="title">数独秩理论研究</div>
        <div className="muted">9×9 标准数独</div>
      </div>

      <div className="menuBar" role="tablist" aria-label="菜单栏">
        {menuDefs.map((m) => (
          <button
            key={m.key}
            type="button"
            className={'menuBtn' + (activeMenu === m.key ? ' isActive' : '')}
            onClick={() => setActiveMenu(m.key)}
            role="tab"
            aria-selected={activeMenu === m.key}
          >
            {m.label}
          </button>
        ))}
      </div>

      <div className="actionBar" aria-label="功能区">
        {activeMenu === 'file' && (
          <>
            <IconButton
              icon={<IconImport />}
              label="导入题目"
              tip="粘贴 81 位字符串导入提示数（0 表示空格）。"
              onClick={() => {
                setIoError('')
                setModal('import')
              }}
            />
            <IconButton
              icon={<IconExport />}
              label="导出题目"
              tip="导出当前盘面为 81 位字符串（含用户填写）。"
              onClick={() => {
                exportPuzzle()
                setIoError('')
                setModal('export')
              }}
            />
            <IconButton
              icon={<IconImage />}
              label="转图片"
              tip="将盘面导出为图片（占位：后续实现）。"
              onClick={() => window.alert('转图片：功能占位，后续实现。')}
            />
            <IconButton
              icon={<IconTrash />}
              label="清空盘面"
              tip="清空所有提示/填写/候选（请谨慎）。"
              onClick={clearAll}
            />
          </>
        )}

        {activeMenu === 'edit' && (
          <>
            <IconButton
              icon={<IconTrash />}
              label={mode === 'value' ? '删除数字' : '清空候选'}
              tip={mode === 'value' ? '清空当前格数字（仅用户填写可删）。' : '清空当前格全部候选数。'}
              onClick={doDelete}
              disabled={!canDelete}
            />
            <IconButton
              icon={<IconSparkle />}
              label="切换模式"
              tip="填数/候选切换（也可按空格）。"
              onClick={() => setMode((m) => (m === 'value' ? 'candidate' : 'value'))}
            />
            <IconButton
              icon={<IconCandidates />}
              label="全标候选"
              tip="基于行/列/宫排除逻辑，一键生成所有空格候选数。"
              onClick={doFullMark}
            />
            <IconButton
              icon={<IconSparkle />}
              label="清空候选"
              tip="清空全盘候选数（不影响已填数字）。"
              onClick={doClearAllCandidates}
            />
            <IconButton
              icon={<IconTrash />}
              label="清空盘面"
              tip="清空所有提示/填写/候选（请谨慎）。"
              onClick={clearAll}
            />
          </>
        )}

        {activeMenu === 'rank' && (
          <div className="muted">秩查询：功能区占位（后续会在此展示查询/计算入口）。</div>
        )}
        {activeMenu === 'settings' && <div className="muted">设置：占位。</div>}
        {activeMenu === 'help' && <div className="muted">帮助：占位。</div>}
      </div>

      <main className="main">
        <div className="leftCol">
          <div className="boardWrap" aria-label="盘面容器">
            {solution ? (
              <div className="solutionMiniFloating" aria-label="解缩略图">
                <div className="solutionGrid" role="grid" aria-label="解缩略图网格">
                  {solution.map((v, i) => (
                    <div key={i} className="solutionCell" role="gridcell">
                      {v}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            <div ref={boardRef} className="board" role="grid" aria-label="数独盘面">
              {board.map((cell, idx) => {
                const { r, c } = indexToRC(idx)
                const selectedCls = selected === idx ? ' isSelected' : ''
                const givenCls = cell.given ? ' isGiven' : ''
                const conflictCls = conflicts[idx] ? ' isConflict' : ''
                const truthCellCls = selectedTruthCellIdx.has(idx) ? ' isTruthCell' : ''
                const thickTop = r % 3 === 0 ? ' thickTop' : ''
                const thickLeft = c % 3 === 0 ? ' thickLeft' : ''
                const thickRight = c === 8 ? ' thickRight' : ''
                const thickBottom = r === 8 ? ' thickBottom' : ''

                return (
                  <button
                    key={idx}
                    type="button"
                    className={
                      'cell' +
                      selectedCls +
                      givenCls +
                      conflictCls +
                      truthCellCls +
                      thickTop +
                      thickLeft +
                      thickRight +
                      thickBottom
                    }
                    onClick={() => {
                      setSelected(idx)
                      setPicked(null)
                    }}
                    onContextMenu={(e) => {
                      // 右键：在选中候选数字位置填数；再次右键取消填数
                      e.preventDefault()
                      if (picked == null) return
                      if (picked.idx !== idx) return
                      if (cell.given) return
                      if (cell.value === 0) setValue(idx, picked.d)
                      else if (cell.value === picked.d) setValue(idx, 0)
                    }}
                    role="gridcell"
                    aria-selected={selected === idx}
                    data-rc={`${r + 1}-${c + 1}`}
                    style={cell.cellColor ? { backgroundColor: colorToBg(cell.cellColor) } : undefined}
                  >
                    {cell.value !== 0 ? (
                      <span className={cell.given ? 'value given' : 'value user'}>{cell.value}</span>
                    ) : (
                      <CandidateGrid
                        candidates={cell.candidates}
                        candidateColors={cell.candidateColors}
                        cellIdx={idx}
                        picked={picked}
                        onPick={onPickCandidate}
                      />
                    )}
                  </button>
                )
              })}

              {selectedStruct ? (
                <BoardOverlay
                  board={board}
                  boardPx={boardPx}
                  truths={selectedStruct.truths}
                  links={selectedStruct.links}
                  deletions={selectedDeletions.map((m) => ({
                    r: Math.floor(m.idx / 9),
                    c: m.idx % 9,
                    d: m.d,
                  }))}
                />
              ) : null}
            </div>
          </div>
          <div className="reserveStrip" aria-label="盘面下方预留区域" />
        </div>

        <div className="rankCol" aria-label="秩结构展示区">
          <div className="panel rankPane">
            <div className="panelTitle">秩结构展示区</div>
            <div className="row" style={{ marginBottom: 8 }}>
              <span className="tag">Truth 范围</span>
              <input
                className="monoText"
                style={{ width: 70, padding: '8px 10px' }}
                value={String(tMin)}
                onChange={(e) => setTMin(Number(e.target.value))}
                inputMode="numeric"
              />
              <span className="muted">到</span>
              <input
                className="monoText"
                style={{ width: 70, padding: '8px 10px' }}
                value={String(tMax)}
                onChange={(e) => setTMax(Number(e.target.value))}
                inputMode="numeric"
              />
              {!isSearching ? (
                <button type="button" className="smallBtn" onClick={startSearch}>
                  查询
                </button>
              ) : (
                <button type="button" className="smallBtn danger" onClick={stopSearch}>
                  Stop
                </button>
              )}
            </div>

            {progress ? (
              <div className="muted" style={{ marginBottom: 8 }}>
                进度：T={progress.currentT} ｜ 已遍历Truth组合={progress.exploredTruthSets} ｜ 已找到结构={progress.found}
              </div>
            ) : (
              <div className="muted" style={{ marginBottom: 8 }}>
                提示：结构基于“行列宫排除”的允许候选自动计算。点击列表项会在盘面上渲染该结构。
              </div>
            )}

            {selectedStruct ? (
              <div className="listItem" style={{ marginBottom: 10 }}>
                <div className="listItemTop">
                  <div style={{ fontWeight: 900, fontSize: 12 }}>
                    当前结构：#{selectedItem ? visibleItems.findIndex((x) => x.delSig === selectedItem.delSig) + 1 : '-'}
                  </div>
                  <span className={'tag' + (selectedStruct.R < 0 ? ' bad' : ' good')}>
                    T{selectedStruct.T} / L{selectedStruct.L} / R{selectedStruct.R}
                  </span>
                </div>
                <textarea className="monoText" readOnly rows={4} value={formatStructureDetail(selectedStruct)} />
                <div className="row" style={{ marginBottom: 6 }}>
                  <span className={'tag' + (selectedDeletions.length > 0 ? ' bad' : '')}>
                    可删候选：{selectedDeletions.length}
                  </span>
                  <button
                    type="button"
                    className="smallBtn"
                    disabled={selectedDeletions.length === 0}
                    onClick={() => {
                      // 应用删数：只删本结构的删数集合；随后列表会基于当前盘面自动隐藏同删数/无效结构
                      setBoard((prev) => applyCandidateEliminations(prev, selectedDeletions.map((m) => ({ idx: m.idx, d: m.d }))))
                      setSelectedDelSig(null)
                    }}
                  >
                    应用
                  </button>
                </div>
                <div className="muted">删数：{selectedItem?.summary ?? ''}</div>
                <div className="muted">
                  Truth：单元格=蓝底；行/列/宫-数字=粗实线连接候选。Link：单元格=双层蓝框；行/列/宫-数字=双虚线连接候选（均为直角折线）。
                </div>
              </div>
            ) : null}

            <div className="rankListScroll">
              <div className="list" aria-label="结构列表">
                {visibleItems.length === 0 ? (
                  <div className="muted">暂无结果。</div>
                ) : (
                  visibleItems.map((it, idx) => (
                    <button
                      key={it.delSig}
                      type="button"
                      className="listItem"
                      style={{
                        textAlign: 'left',
                        cursor: 'pointer',
                        background: it.delSig === selectedDelSig ? '#eff8ff' : '#fff',
                        padding: '10px 12px',
                      }}
                      onClick={() => setSelectedDelSig(it.delSig)}
                      title="点击查看并在盘面上渲染该结构"
                    >
                      <div style={{ fontWeight: 900, fontSize: 12 }}>
                        {idx + 1}. {it.struct.T}T{it.struct.L}L {it.summary}
                      </div>
                    </button>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      </main>

      <Modal title="导入题目" open={modal === 'import'} onClose={() => setModal(null)}>
        <textarea
          className="monoText"
          value={ioText}
          onChange={(e) => setIoText(e.target.value)}
          spellCheck={false}
          rows={4}
        />
        {ioError ? <div className="error">{ioError}</div> : null}
        <div className="row">
          <button type="button" className="btn primary" onClick={importPuzzle}>
            导入
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => {
              setIoText('')
              setIoError('')
            }}
          >
            清空输入
          </button>
        </div>
      </Modal>

      <Modal title="导出题目" open={modal === 'export'} onClose={() => setModal(null)}>
        <textarea className="monoText" value={ioText} readOnly rows={4} />
        <div className="row">
          <button
            type="button"
            className="btn primary"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(ioText)
              } catch {
                // ignore
              }
            }}
          >
            复制到剪贴板
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => {
              exportPuzzle()
            }}
          >
            刷新
          </button>
        </div>
      </Modal>
    </div>
  )
}


