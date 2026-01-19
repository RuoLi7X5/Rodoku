import { useEffect, useMemo, useRef, useState } from 'react'
import '../sudoku.css'
import { createEmptyBoard, fillAllCandidates } from '../lib/sudoku'
import { parsePuzzleBankText } from './parsePuzzleBank'
import type { RodokuRun, RodokuStep } from './types'
import { RodokuBoard } from './RodokuBoard'
import { boardFromStateKey } from './boardFromStateKey'
import type { Digit } from '../lib/sudoku'

export function RodokuPage() {
  const [bankText, setBankText] = useState<string>('')
  const [parseMsg, setParseMsg] = useState<string>('')
  const [puzzles, setPuzzles] = useState<string[]>([])
  const [runs, setRuns] = useState<RodokuRun[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)
  const [playStep, setPlayStep] = useState<number>(0)
  const [isTraining, setIsTraining] = useState<boolean>(false)
  const [trainMsg, setTrainMsg] = useState<string>('')
  const [followTraining, setFollowTraining] = useState<boolean>(true)
  const followTrainingRef = useRef<boolean>(true)
  const [backendUrl, setBackendUrl] = useState<string>('http://127.0.0.1:8000')
  // 生成器/探索控制（最小可用版：控制 Rank truth 类型、T/R 范围、UR1 开关）
  const [genMaxR, setGenMaxR] = useState<number>(3)
  const [genMinT, setGenMinT] = useState<number>(1)
  const [genMaxT, setGenMaxT] = useState<number>(12)
  const [truthTypeCell, setTruthTypeCell] = useState<boolean>(true)
  const [truthTypeRow, setTruthTypeRow] = useState<boolean>(true)
  const [truthTypeCol, setTruthTypeCol] = useState<boolean>(true)
  const [truthTypeBox, setTruthTypeBox] = useState<boolean>(true)
  const [enableUr1, setEnableUr1] = useState<boolean>(true)
  const [usePolicy, setUsePolicy] = useState<boolean>(false)
  const abortRef = useRef<AbortController | null>(null)
  // 防止双击/重复触发 startTraining（state 更新有延迟，可能出现并发刷题）
  const trainingGuardRef = useRef<boolean>(false)
  // 页面卸载时停止所有仍在跑的 solve_job，避免后台继续跑 & 旧轮询泄漏
  const activeJobIdsRef = useRef<Set<string>>(new Set())
  const fileRef = useRef<HTMLInputElement | null>(null)
  const expandedStepsRef = useRef<HTMLDivElement | null>(null)

  const selectedRun = useMemo(() => runs.find((r) => r.id === selectedRunId) ?? null, [runs, selectedRunId])

  useEffect(() => {
    followTrainingRef.current = followTraining
  }, [followTraining])

  useEffect(() => {
    return () => {
      // 1) 停止前端轮询
      abortRef.current?.abort()
      // 2) 通知后端停止仍在跑的 job（fire-and-forget）
      const base = backendUrl.replace(/\/$/, '')
      for (const jid of Array.from(activeJobIdsRef.current.values())) {
        fetch(`${base}/solve_job/${encodeURIComponent(jid)}/stop`, { method: 'POST' }).catch(() => { })
      }
      activeJobIdsRef.current.clear()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendUrl])

  useEffect(() => {
    // 自动滚到底部：仅对当前展开的那一题
    if (!expandedStepsRef.current) return
    if (!expandedRunId) return
    const run = runs.find((r) => r.id === expandedRunId)
    if (!run) return
    expandedStepsRef.current.scrollTop = expandedStepsRef.current.scrollHeight
  }, [runs, expandedRunId])

  const boardForView = useMemo(() => {
    // 1) 正常回放：选中某一题
    if (selectedRun) {
      const idx = Math.max(0, Math.min(playStep, selectedRun.snapshots.length - 1))
      const key = selectedRun.snapshots[idx]
      const b = boardFromStateKey(key, selectedRun.puzzle)
      return b ?? fillAllCandidates(createEmptyBoard())
    }
    // 2) 仅解析题库后：展示第一题题面预览（避免“盘面空白/异常”）
    if (puzzles.length > 0) {
      const p0 = puzzles[0]
      const b = boardFromStateKey(initialStateKey(p0), p0)
      return b ?? fillAllCandidates(createEmptyBoard())
    }
    return fillAllCandidates(createEmptyBoard())
  }, [selectedRun, playStep, puzzles])

  function onImportText() {
    const ps = parsePuzzleBankText(bankText)
    setPuzzles(ps)
    setRuns([])
    setSelectedRunId(null)
    setExpandedRunId(null)
    setPlayStep(0)
    setParseMsg(ps.length > 0 ? `解析成功：${ps.length} 题` : '未解析到题目：请确认题库包含 0/./1-9 且每题合计 81 格')
  }

  function importBankText(text: string, source?: string) {
    const raw = String(text ?? '')
    setBankText(raw)
    const ps = parsePuzzleBankText(raw)
    setPuzzles(ps)
    setRuns([])
    setSelectedRunId(null)
    setExpandedRunId(null)
    setPlayStep(0)
    const src = source ? `（${source}）` : ''
    setParseMsg(ps.length > 0 ? `已导入${src}：解析成功 ${ps.length} 题` : `已导入${src}：未解析到题目（请确认每题 81 格）`)
  }

  function initialStateKey(puzzle: string): string {
    // digits|forbiddenKey，forbiddenKey=每格2位base36的0，即 "00" * 81
    return `${puzzle}|${'00'.repeat(81)}`
  }

  async function startSolveJob(puzzle: string, signal: AbortSignal): Promise<string> {
    const base = backendUrl.replace(/\/$/, '')
    const truth_types = [
      ...(truthTypeCell ? ['cell'] : []),
      ...(truthTypeRow ? ['rowDigit'] : []),
      ...(truthTypeCol ? ['colDigit'] : []),
      ...(truthTypeBox ? ['boxDigit'] : []),
    ]
    const startResp = await fetch(`${base}/solve_job/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        puzzle,
        min_t: Math.max(1, Math.min(30, Math.floor(genMinT))),
        max_t: Math.max(1, Math.min(12, Math.floor(genMaxT))),
        max_r: Math.max(0, Math.min(3, Math.floor(genMaxR))),
        max_structures_per_step: 200,
        truth_types: truth_types.length === 0 ? null : truth_types,
        enable_ur1: !!enableUr1,
        use_policy: !!usePolicy,
      }),
      signal,
    })
    if (!startResp.ok) {
      const text = await startResp.text().catch(() => '')
      throw new Error(`后端错误：HTTP ${startResp.status} ${text}`)
    }
    const startData = (await startResp.json()) as { id: string }
    return startData.id
  }

  async function pollSolveJob(
    jobId: string,
    signal: AbortSignal
  ): Promise<{
    status: string
    message?: string
    steps: Array<{ action_type: 'eliminate' | 'commit'; rationale: string; affected: Array<[number, number | null]>; meta?: any }>
    snapshots: string[]
    error?: string
  }> {
    const base = backendUrl.replace(/\/$/, '')
    if (signal.aborted) {
      await fetch(`${base}/solve_job/${encodeURIComponent(jobId)}/stop`, { method: 'POST' }).catch(() => { })
      throw new Error('aborted')
    }
    const resp = await fetch(`${base}/solve_job/${encodeURIComponent(jobId)}`, { method: 'GET' })
    const st = await resp.json().catch(() => ({}))
    if (!resp.ok) {
      const msg = typeof (st as any)?.detail === 'string' ? String((st as any).detail) : JSON.stringify(st)
      throw new Error(`后端错误：HTTP ${resp.status} ${msg}`)
    }
    return st as any
  }

  async function startTraining() {
    if (isTraining) return
    if (trainingGuardRef.current) return
    if (puzzles.length === 0) return
    trainingGuardRef.current = true
    setIsTraining(true)
    setTrainMsg('准备开始…')
    const ac = new AbortController()
    abortRef.current = ac

    try {
      const nextRuns: RodokuRun[] = []
      for (let i = 0; i < puzzles.length; i++) {
        if (ac.signal.aborted) break
        const puzzle = puzzles[i]
        const runId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
        setTrainMsg(`正在第 ${i + 1}/${puzzles.length} 题（后端计算中）…`)
        // 仅在“跟随刷题”开启时自动切到当前题；否则尊重用户正在回放的题目
        if (followTrainingRef.current) {
          setSelectedRunId(runId)
          setExpandedRunId(runId)
          setPlayStep(0)
        }

        // 先立刻显示题面（不然等待后端时盘面为空）
        const placeholder: RodokuRun = {
          id: runId,
          puzzle,
          startedAtMs: Date.now(),
          status: 'running',
          steps: [],
          snapshots: [initialStateKey(puzzle)],
        }
        nextRuns.push(placeholder)
        setRuns(nextRuns.slice())
        if (followTrainingRef.current) setPlayStep(0)

        // 失败时也要保留已产生的步骤/快照（用于审计“哪一步删数导致无解”）
        let builtStepsForErr: RodokuStep[] = []
        let latestSnapsForErr: string[] = [initialStateKey(puzzle)]

        try {
          // 关键修复：每题只 start 一次 job，然后持续 poll 同一个 jobId（不会重置回初始）
          let jobId = await startSolveJob(puzzle, ac.signal)
          activeJobIdsRef.current.add(jobId)
          const idx0 = nextRuns.findIndex((x) => x.id === runId)
          if (idx0 >= 0) nextRuns[idx0] = { ...placeholder, jobId }
          setRuns(nextRuns.slice())

          let lastStepsLen = -1
          let lastSnapsLen = -1
          let lastStatus = ''
          let lastMsg = ''
          // 性能：避免每次轮询都把全部 steps 从头 map（步数大时会导致题与题之间明显卡顿/GC）
          let builtSteps: RodokuStep[] = builtStepsForErr
          let restartTimes = 0
          while (true) {
            const data = await pollSolveJob(jobId, ac.signal)
            const status = String(data.status)
            const msg = (data as any).message ? String((data as any).message) : ''
            if (msg) setTrainMsg(msg)
            if (status === 'stopped') throw new Error('aborted')
            if (status === 'not_found') {
              // 后端 uvicorn --reload 或进程重启会导致内存态 job 丢失；这里自动重启该题的 job，避免“卡在第4题最后一步”
              if (restartTimes < 2) {
                restartTimes += 1
                setTrainMsg(`后端 job 丢失，正在自动重启本题（${restartTimes}/2）…`)
                jobId = await startSolveJob(puzzle, ac.signal)
                activeJobIdsRef.current.add(jobId)
                const idxr = nextRuns.findIndex((x) => x.id === runId)
                if (idxr >= 0) nextRuns[idxr] = { ...(nextRuns[idxr] ?? placeholder), jobId }
                setRuns(nextRuns.slice())
                // 重启后继续轮询（steps/snapshots 会从头来）
                lastStepsLen = -1
                lastSnapsLen = -1
                builtSteps = []
                latestSnapsForErr = [initialStateKey(puzzle)]
                continue
              }
              throw new Error('后端 job 不存在（可能后端重启/热重载），已超过自动重启次数')
            }

            const stepsArr = (data.steps ?? []) as Array<{
              action_type: 'eliminate' | 'commit'
              rationale: string
              affected: Array<[number, number | null]>
              meta?: any
            }>
            const snapsArr = (data.snapshots ?? []) as string[]
            if (snapsArr.length > 0) latestSnapsForErr = snapsArr

            // 只有在“有新进展或状态变化”时才更新 UI（避免闪回/抖动）
            // 重要：最后一步可能不会再新增 steps/snapshots，但 status 会从 running->solved；
            // 若不刷新会表现为“解完但卡在最后一步不动”。
            const shouldUpdate =
              stepsArr.length !== lastStepsLen ||
              snapsArr.length !== lastSnapsLen ||
              status !== lastStatus ||
              msg !== lastMsg
            if (shouldUpdate && (stepsArr.length > 0 || snapsArr.length > 0 || status)) {
              const prevBuiltLen = builtSteps.length
              lastStepsLen = stepsArr.length
              lastSnapsLen = snapsArr.length
              lastStatus = status
              lastMsg = msg

              if (stepsArr.length > builtSteps.length) {
                const delta = stepsArr.slice(builtSteps.length)
                const add = delta.map((s, i2) => {
                  const first = s.affected[0] ?? [0, null]
                  const idx = first[0]
                  const d = ((first[1] ?? 1) as number) as Digit
                  const stepIndex = prevBuiltLen + i2
                  return {
                    stepIndex,
                    atMs: Date.now(),
                    action: { type: s.action_type, idx, d } as any,
                    rationale: s.rationale,
                    meta: s.meta,
                    affected: s.affected.map(([ii, dd]) => ({ idx: ii, d: (dd ?? undefined) as any })),
                  }
                })
                builtSteps = builtSteps.concat(add)
              }
              builtStepsForErr = builtSteps

              const runStatus: RodokuRun['status'] =
                status === 'solved' ? 'solved' : status === 'running' ? 'running' : status === 'error' ? 'error' : 'running'

              const run: RodokuRun = {
                id: runId,
                jobId,
                puzzle,
                startedAtMs: placeholder.startedAtMs,
                finishedAtMs: status === 'solved' ? Date.now() : undefined,
                status: runStatus,
                steps: builtSteps,
                snapshots: snapsArr.length > 0 ? snapsArr : [initialStateKey(puzzle)],
                error: status === 'error' ? String((data as any).error ?? 'error') : undefined,
              }
              const idx = nextRuns.findIndex((x) => x.id === runId)
              if (idx >= 0) nextRuns[idx] = run
              setRuns(nextRuns.slice())

              // 关键：自动跟随最新盘面（否则会一直停留在 playStep=0，必须手点最新步骤才更新）
              if (followTrainingRef.current) {
                setSelectedRunId(runId)
                setExpandedRunId(runId)
                const last = Math.max(0, (run.snapshots?.length ?? 1) - 1)
                setPlayStep(last)
              }
            }

            if (status === 'error') break
            if (status === 'solved') break
            await new Promise((r) => setTimeout(r, 350))
          }
          // solved 后不再需要继续跟踪该 job
          activeJobIdsRef.current.delete(jobId)
        } catch (e) {
          const msg = e instanceof Error ? e.message : String(e)
          const idx = nextRuns.findIndex((x) => x.id === runId)
          const bad: RodokuRun = {
            ...placeholder,
            jobId: nextRuns.find((x) => x.id === runId)?.jobId,
            status: ac.signal.aborted ? 'aborted' : 'error',
            error: msg,
            finishedAtMs: Date.now(),
            steps: builtStepsForErr,
            snapshots: latestSnapsForErr,
          }
          if (idx >= 0) nextRuns[idx] = bad
          setRuns(nextRuns.slice())
        }
      }
    } finally {
      setIsTraining(false)
      abortRef.current = null
      setTrainMsg('')
      trainingGuardRef.current = false
    }
  }

  function stopTraining() {
    abortRef.current?.abort()
  }

  function GeneratorPanel() {
    return (
      <div className="panel" style={{ marginBottom: 10 }}>
        <div className="panelTitle">生成器/探索控制（可控面板）</div>
        <div className="row" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'center', marginTop: 8 }}>
          <span className="tag">秩逻辑</span>
          <span className="muted">R上限（≤3）</span>
          <input className="monoText" style={{ width: 64 }} value={genMaxR} onChange={(e) => setGenMaxR(Number(e.target.value || 0))} />
          <span className="muted">T范围</span>
          <input className="monoText" style={{ width: 64 }} value={genMinT} onChange={(e) => setGenMinT(Number(e.target.value || 1))} />
          <span className="muted">~</span>
          <input className="monoText" style={{ width: 64 }} value={genMaxT} onChange={(e) => setGenMaxT(Number(e.target.value || 12))} />
          <span className="muted">Truth类型</span>
          <label className="muted" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            <input type="checkbox" checked={truthTypeCell} onChange={(e) => setTruthTypeCell(e.target.checked)} />单元格
          </label>
          <label className="muted" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            <input type="checkbox" checked={truthTypeRow} onChange={(e) => setTruthTypeRow(e.target.checked)} />行
          </label>
          <label className="muted" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            <input type="checkbox" checked={truthTypeCol} onChange={(e) => setTruthTypeCol(e.target.checked)} />列
          </label>
          <label className="muted" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            <input type="checkbox" checked={truthTypeBox} onChange={(e) => setTruthTypeBox(e.target.checked)} />宫
          </label>
        </div>
        <div className="row" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'center', marginTop: 10 }}>
          <span className="tag">致命结构</span>
          <label className="muted" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            <input type="checkbox" checked={enableUr1} onChange={(e) => setEnableUr1(e.target.checked)} />
            启用 UR1（当前实现）
          </label>
          <span className="tag">Policy</span>
          <label className="muted" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            <input type="checkbox" checked={usePolicy} onChange={(e) => setUsePolicy(e.target.checked)} />
            使用模型排序/剪枝（不改变逻辑正确性）
          </label>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <div className="topBar">
        <div className="title">Rodoku 训练/回放（MVP）</div>
        <div className="muted">题库导入 → 自动刷题（基于秩结构R&lt;3）→ 步骤日志</div>
      </div>

      <main className="main" style={{ gridTemplateColumns: '1fr 420px' }}>
        <div className="leftCol">
          <div className="panel" style={{ marginBottom: 10 }}>
            <div className="panelTitle">题库导入（文本）</div>
            <textarea
              className="monoText"
              value={bankText}
              onChange={(e) => setBankText(e.target.value)}
              rows={6}
              placeholder="粘贴题库文本：支持 0 或 . 表示空格；任意分隔。"
              spellCheck={false}
            />
            <div className="row" style={{ marginTop: 8, gap: 8 }}>
              <button type="button" className="smallBtn" onClick={onImportText}>
                解析题库
              </button>
              <span className="tag">后端</span>
              <input
                className="monoText"
                style={{ flex: 1, minWidth: 220, padding: '8px 10px' }}
                value={backendUrl}
                onChange={(e) => setBackendUrl(e.target.value)}
                placeholder="http://127.0.0.1:8000"
                spellCheck={false}
              />
              <button
                type="button"
                className="smallBtn"
                onClick={() => fileRef.current?.click()}
                title="从本地选择题库文本文件"
              >
                选择文件
              </button>
              <input
                ref={fileRef}
                type="file"
                accept=".txt,.md,.csv,.log,text/plain"
                style={{ display: 'none' }}
                onClick={(e) => {
                  // 关键：同一个文件二次选择时也触发 onChange（否则看起来“无法导入”）
                  ; (e.currentTarget as HTMLInputElement).value = ''
                }}
                onChange={(e) => {
                  const input = e.currentTarget
                  const f = input.files?.[0]
                  if (!f) return
                  const reader = new FileReader()
                  reader.onerror = () => {
                    setParseMsg(`读取失败：${f.name}`)
                  }
                  reader.onload = () => {
                    const text = String(reader.result ?? '')
                    // 体验：选完文件即完成导入+解析（仍保留“解析题库”按钮用于手动编辑后重解析）
                    importBankText(text, `文件:${f.name}`)
                  }
                  reader.readAsText(f)
                }}
              />
              <span className="muted">已解析题目：{puzzles.length}</span>
              <button
                type="button"
                className="smallBtn"
                onClick={() => setFollowTraining((v) => !v)}
                title="开启：自动跳到当前正在刷的题；关闭：你手动回放时不会被自动切题打断"
              >
                {followTraining ? '跟随刷题：开' : '跟随刷题：关'}
              </button>
              {!isTraining ? (
                <button type="button" className="smallBtn" onClick={startTraining} disabled={puzzles.length === 0}>
                  开始刷题
                </button>
              ) : (
                <button type="button" className="smallBtn danger" onClick={stopTraining}>
                  Stop
                </button>
              )}
            </div>
            {parseMsg ? (
              <div className="muted" style={{ marginTop: 6 }}>
                {parseMsg}
              </div>
            ) : null}
            {isTraining ? (
              <div className="muted" style={{ marginTop: 6 }}>
                {trainMsg || '运行中…'}
              </div>
            ) : null}
          </div>

          <div className="panel">
            <div className="panelTitle">盘面（回放占位）</div>
            {(() => {
              const m = new Map<number, Set<Digit>>()
              if (selectedRun && playStep > 0) {
                const s = selectedRun.steps[playStep - 1]
                if (s?.action?.type === 'eliminate' && s.affected) {
                  for (const a of s.affected) {
                    if (a.d == null) continue
                    const set = m.get(a.idx) ?? new Set<Digit>()
                    set.add(a.d as Digit)
                    m.set(a.idx, set)
                  }
                }
              }
              return <RodokuBoard board={boardForView} highlightElims={m.size ? m : undefined} />
            })()}
            {selectedRun ? (
              <div className="muted" style={{ marginTop: 8 }}>
                当前题：{runs.findIndex((r) => r.id === selectedRun.id) + 1}/{runs.length} ｜ 状态：{selectedRun.status}{' '}
                ｜ 步数：{selectedRun.steps.length} ｜ 回放步：{playStep}
              </div>
            ) : (
              <div className="muted" style={{ marginTop: 8 }}>
                请选择一题开始回放（下一步会接入 snapshots 还原真实过程）。
              </div>
            )}
            {selectedRun ? (
              <div className="row" style={{ marginTop: 10, gap: 8 }}>
                <button
                  type="button"
                  className="smallBtn"
                  onClick={() => setPlayStep((s) => Math.max(0, s - 1))}
                  disabled={playStep <= 0}
                >
                  上一步
                </button>
                <button
                  type="button"
                  className="smallBtn"
                  onClick={() => setPlayStep((s) => Math.min(selectedRun.snapshots.length - 1, s + 1))}
                  disabled={playStep >= selectedRun.snapshots.length - 1}
                >
                  下一步
                </button>
                <span className="muted">
                  快照：{playStep + 1}/{selectedRun.snapshots.length}
                </span>
              </div>
            ) : null}
          </div>
        </div>

        <div className="rankCol" aria-label="刷题记录与步骤详情">
          <GeneratorPanel />
          <div className="panel rankPane">
            <div className="panelTitle">刷题记录</div>
            {runs.length === 0 ? (
              <div className="muted">暂无记录。先导入题库并开始刷题。</div>
            ) : (
              <div className="rankListScroll">
                <div className="list" aria-label="题目列表">
                  {runs.map((r, idx) => {
                    const isSel = r.id === selectedRunId
                    const isOpen = r.id === expandedRunId
                    return (
                      <div
                        key={r.id}
                        className="listItem"
                        style={{
                          background: isSel ? '#eff8ff' : '#fff',
                          padding: '10px 12px',
                          borderRadius: 12,
                          border: '1px solid #eaecf0',
                          marginBottom: 8,
                        }}
                      >
                        <div
                          role="button"
                          tabIndex={0}
                          onClick={() => {
                            setFollowTraining(false)
                            setSelectedRunId(r.id)
                            setPlayStep(0)
                            setExpandedRunId((prev) => (prev === r.id ? null : r.id))
                          }}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              e.preventDefault()
                              setFollowTraining(false)
                              setSelectedRunId(r.id)
                              setPlayStep(0)
                              setExpandedRunId((prev) => (prev === r.id ? null : r.id))
                            }
                          }}
                          style={{ cursor: 'pointer' }}
                        >
                          <div style={{ fontWeight: 900, fontSize: 12 }}>
                            #{idx + 1} ｜ {r.status} ｜ steps={r.steps.length} {isOpen ? '（展开）' : ''}
                          </div>
                          {r.error ? <div className="error">{r.error}</div> : null}
                          <div className="muted" style={{ marginTop: 4 }}>
                            {r.error
                              ? '（失败：详见红色错误信息）'
                              : r.steps.length > 0
                                ? r.steps[r.steps.length - 1].rationale
                                : '（暂无步骤）'}
                          </div>
                        </div>

                        {isOpen ? (
                          <div
                            ref={expandedStepsRef}
                            style={{
                              marginTop: 10,
                              maxHeight: 320,
                              overflow: 'auto',
                              border: '1px solid #eaecf0',
                              borderRadius: 10,
                              padding: 10,
                              background: '#fff',
                            }}
                          >
                            {r.steps.length === 0 ? (
                              <div className="muted">
                                {r.error ? `（失败：${r.error}）` : '（暂无步骤：后端暂未产出推理）'}
                              </div>
                            ) : (
                              r.steps.map((s, i2) => {
                                const meta = s.meta ?? {}
                                const kind = meta.kind as string | undefined
                                const isRank = kind === 'RANK'
                                const isElim = s.action.type === 'eliminate'
                                const isOracle = typeof s.rationale === 'string' && s.rationale.startsWith('ORACLE：')

                                const truths = Array.isArray(meta.truths) ? meta.truths : []
                                const links = Array.isArray(meta.links) ? meta.links : []

                                const encodeRef = (ref: any, asLink: boolean) => {
                                  if (!ref || !ref.type) return 'unknown'
                                  if (ref.type === 'candidate') {
                                    const idx0 = Number(ref.idx ?? -1)
                                    const rr = Math.floor(idx0 / 9) + 1
                                    const cc = (idx0 % 9) + 1
                                    const d = Number(ref.d ?? 0)
                                    return `r${rr}c${cc}=${d}`
                                  }
                                  if (ref.type === 'cell') {
                                    const idx0 = Number(ref.idx ?? -1)
                                    const rr = Math.floor(idx0 / 9) + 1
                                    const cc = (idx0 % 9) + 1
                                    return `${rr}${asLink ? 'n' : 'N'}${cc}`
                                  }
                                  const d = Number(ref.d ?? 0)
                                  if (ref.type === 'rowDigit') return `${d}${asLink ? 'r' : 'R'}${Number(ref.row ?? 0) + 1}`
                                  if (ref.type === 'colDigit') return `${d}${asLink ? 'c' : 'C'}${Number(ref.col ?? 0) + 1}`
                                  if (ref.type === 'boxDigit') return `${d}${asLink ? 'b' : 'B'}${Number(ref.box ?? 0) + 1}`
                                  return String(ref.type)
                                }

                                const compress = (refs: any[], asLink: boolean) => {
                                  const out: string[] = []
                                  const boxMap = new Map<string, number[]>()
                                  for (const r0 of refs) {
                                    if (r0?.type === 'boxDigit') {
                                      const d = Number(r0.d ?? 0)
                                      const key = `${d}${asLink ? 'b' : 'B'}`
                                      const b = Number(r0.box ?? -1) + 1
                                      if (!boxMap.has(key)) boxMap.set(key, [])
                                      boxMap.get(key)!.push(b)
                                    } else {
                                      out.push(encodeRef(r0, asLink))
                                    }
                                  }
                                  for (const [k, bs] of boxMap.entries()) {
                                    const uniq = Array.from(new Set(bs)).sort((a, b) => a - b)
                                    out.push(`${k}${uniq.join('')}`)
                                  }
                                  return out
                                }

                                return (
                                  <div
                                    key={s.stepIndex}
                                    role="button"
                                    tabIndex={0}
                                    onClick={() => setPlayStep(i2 + 1)}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Enter' || e.key === ' ') {
                                        e.preventDefault()
                                        setPlayStep(i2 + 1)
                                      }
                                    }}
                                    style={{
                                      padding: '8px 10px',
                                      borderRadius: 10,
                                      border: '1px solid #f2f4f7',
                                      marginBottom: 8,
                                      cursor: 'pointer',
                                      background: playStep === i2 + 1 ? '#ecfdf3' : '#fff',
                                    }}
                                  >
                                    <div style={{ fontWeight: 900, fontSize: 12 }}>
                                      {(() => {
                                        const meta = (s.meta ?? {}) as any
                                        const kind = meta.kind as string | undefined
                                        if (s.action.type === 'eliminate' && (kind === 'RANK' || kind === 'FORCING')) {
                                          const T = meta.T ?? 0
                                          const L = meta.L ?? 0
                                          const dels = (s.affected ?? [])
                                            .filter((x) => x.d != null)
                                            .map((x) => {
                                              const r = Math.floor(x.idx / 9) + 1
                                              const c = (x.idx % 9) + 1
                                              return { r, c, d: x.d as Digit }
                                            })
                                          const byCell = new Map<string, Digit[]>()
                                          for (const d0 of dels) {
                                            const k = `r${d0.r}c${d0.c}`
                                            const arr = byCell.get(k) ?? []
                                            arr.push(d0.d)
                                            byCell.set(k, arr)
                                          }
                                          const parts: any[] = []
                                          for (const [k, ds] of Array.from(byCell.entries())) {
                                            parts.push(
                                              <span key={k} style={{ marginRight: 8 }}>
                                                {k}&lt;&gt;
                                                {ds.map((d) => (
                                                  <span key={`${k}-${d}`} className="delDot" style={{ marginLeft: 4 }}>
                                                    {d}
                                                  </span>
                                                ))}
                                              </span>
                                            )
                                          }
                                          return (
                                            <span>
                                              {i2 + 1}. T{T} L{L} {parts}
                                            </span>
                                          )
                                        }
                                        return `${i2 + 1}. ${s.rationale}`
                                      })()}
                                    </div>
                                    {isOracle ? (
                                      <div className="muted" style={{ marginTop: 4 }}>
                                        （兜底补全：不计入技巧库/结构统计）
                                      </div>
                                    ) : isElim ? (
                                      <div className="muted" style={{ marginTop: 4 }}>
                                        核心逻辑：
                                        {kind === 'UR1'
                                          ? 'UR 唯一性致命结构'
                                          : isRank
                                            ? 'Truth/Link/R 秩删数'
                                            : '逻辑删数'}
                                      </div>
                                    ) : null}
                                    {isRank ? (
                                      <div className="muted" style={{ marginTop: 4, lineHeight: 1.5 }}>
                                        <div>
                                          T/L/R：T={meta.T ?? truths.length}，L={meta.L ?? links.length}，R={meta.R ?? '未知'}
                                        </div>
                                        <div>
                                          T{meta.T ?? truths.length}＝{truths.length ? compress(truths, false).join('-') : '无'}
                                        </div>
                                        <div>
                                          L{meta.L ?? links.length}＝{links.length ? `{${compress(links, true).join(' ')}}` : '无'}
                                        </div>
                                        <div>rank {meta.R ?? '未知'}</div>
                                      </div>
                                    ) : null}
                                  </div>
                                )
                              })
                            )}
                          </div>
                        ) : null}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}

