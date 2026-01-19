from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .solver_core import SolveResult, solve_with_rank
from .learn_params import update_params
from .metrics_store import record_step_event
from .log_store import append_event
from .replay_store import append_transition
from .nn_state import count_total_candidates
from .policy_runtime import current_ckpt as policy_current_ckpt
from .techlib_runtime import record_steps as techlib_record_steps


@dataclass
class SolveJob:
    id: str
    puzzle: str
    created_at_ms: int
    status: str  # running | solved | stopped | error
    error: Optional[str] = None
    message: str = ""
    message_kind: str = "idle"  # idle | found | search | referee | done
    message_at_ms: int = 0

    # best-so-far
    steps: List[Any] = field(default_factory=list)
    snapshots: List[str] = field(default_factory=list)

    # exploration bookkeeping
    attempts: int = 0
    params: Dict[str, Any] = field(default_factory=dict)
    last_progress_at_ms: int = 0

    # control
    stop_event: threading.Event = field(default_factory=threading.Event, repr=False)


_LOCK = threading.Lock()
_JOBS: Dict[str, SolveJob] = {}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _msg_priority(kind: str) -> int:
    # 数值越大优先级越高
    if kind == "done":
        return 40
    if kind == "found":
        return 30
    if kind == "search":
        return 20
    if kind == "referee":
        return 10
    return 0


def _maybe_set_message(job: SolveJob, *, kind: str, msg: str) -> None:
    """
    避免“referee 校验中”刷屏覆盖用户更关心的信息（已找到/搜索中/已完成）。
    - referee 默认低优先级
    - 同优先级按时间更新
    """
    now = _now_ms()
    cur_kind = getattr(job, "message_kind", "idle") or "idle"
    cur_at = int(getattr(job, "message_at_ms", 0) or 0)
    if _msg_priority(kind) < _msg_priority(cur_kind) and (now - cur_at) < 1200:
        return
    job.message = msg
    job.message_kind = kind
    job.message_at_ms = now


def create_job(
    puzzle: str,
    *,
    min_t: int,
    max_t: int,
    max_r: int,
    max_structures_per_step: int,
    truth_types: list[str] | None = None,
    enable_ur1: bool = True,
    use_policy: bool = False,
    rank_time_budget_ms: int = 1200,
) -> SolveJob:
    jid = uuid.uuid4().hex
    job = SolveJob(
        id=jid,
        puzzle=puzzle,
        created_at_ms=_now_ms(),
        status="running",
        steps=[],
        snapshots=[],
        attempts=0,
        params={
            "min_t": min_t,
            "max_t": max_t,
            "max_r": max_r,
            "max_structures_per_step": max_structures_per_step,
            "truth_types": truth_types,
            "enable_ur1": bool(enable_ur1),
            "use_policy": bool(use_policy),
            "rank_time_budget_ms": int(rank_time_budget_ms),
        },
        last_progress_at_ms=_now_ms(),
        message="",
    )
    with _LOCK:
        _JOBS[jid] = job
    t = threading.Thread(target=_run_job, args=(jid,), daemon=True)
    t.start()
    return job


def get_job(jid: str) -> Optional[SolveJob]:
    with _LOCK:
        return _JOBS.get(jid)


def stop_job(jid: str) -> bool:
    with _LOCK:
        job = _JOBS.get(jid)
        if not job:
            return False
        job.stop_event.set()
        return True


def _run_job(jid: str) -> None:
    """
    持续探索：
    - 不允许 ORACLE/猜测
    - stuck 不结束：逐步加大秩结构搜索参数反复尝试
    - 若发现更长 steps（有进展），更新 best-so-far
    - 直到 solved 或用户 stop
    """
    while True:
        with _LOCK:
            job = _JOBS.get(jid)
        if not job:
            return
        if job.stop_event.is_set():
            with _LOCK:
                job.status = "stopped"
            return

        try:
            # 关键升级：实时显示步骤
            # - solve_with_rank 内部每产出一步就回调 on_emit（包含 snapshot0）
            # - 这样前端不会“长时间无进度”，而是随着推理推进实时增长
            p = dict(job.params)
            old_len = len(job.steps)
            step_time_ms: Dict[int, int] = {}

            def on_emit(step_index: int, step: Any, snap_key: str) -> None:
                # step_index: 0 => 初始快照；>=1 => 第 step_index 步后快照
                nonlocal old_len
                with _LOCK:
                    jj = _JOBS.get(jid)
                if not jj:
                    return
                if jj.stop_event.is_set():
                    return
                if step_index == 0:
                    with _LOCK:
                        if not jj.snapshots:
                            jj.snapshots = [snap_key]
                        else:
                            jj.snapshots[0] = snap_key
                    return
                if step_index <= old_len:
                    return
                now = _now_ms()
                step_time_ms[step_index] = now
                with _LOCK:
                    # 追加 step（去重）
                    if step is not None and len(jj.steps) < step_index:
                        jj.steps.append(step)
                        # 产出逻辑步时立刻刷新 message（高优先级）
                        try:
                            _maybe_set_message(jj, kind="found", msg=f"已找到：{getattr(step, 'rationale', '')}")
                        except Exception:
                            pass
                    # 对齐 snapshots（长度应为 step_index+1）
                    if len(jj.snapshots) < step_index + 1:
                        # 确保有 snapshot0
                        if not jj.snapshots:
                            jj.snapshots = [snap_key]
                        while len(jj.snapshots) < step_index:
                            jj.snapshots.append(jj.snapshots[-1])
                        jj.snapshots.append(snap_key)
                    else:
                        jj.snapshots[step_index] = snap_key
                    jj.last_progress_at_ms = now
                time.sleep(0.02)
                # 事件日志：记录逻辑步（用于导出/可视化）
                try:
                    if step is not None:
                        append_event(
                            {
                                "type": "step",
                                "job_id": jid,
                                "puzzle": job.puzzle,
                                "step_index": int(step_index),
                                "action_type": str(getattr(step, "action_type", "")),
                                "rationale": str(getattr(step, "rationale", "")),
                                "meta": (getattr(step, "meta", None) or None),
                                "proof": (getattr(step, "proof", None) or None),
                                "use_policy": bool(p.get("use_policy", False)),
                                "policy_ckpt": (policy_current_ckpt() if bool(p.get("use_policy", False)) else None),
                            }
                        )
                except Exception:
                    pass

            def on_rank_heartbeat(info: Dict[str, Any]) -> None:
                # 更新“搜索心跳”（不改盘面，不计为逻辑步）
                try:
                    phase = str(info.get("phase", ""))
                    if phase == "t1_fast":
                        d = info.get("d", "?")
                        tt = info.get("truth_type", "?")
                        h = info.get("house", "?")
                        msg = (
                            f"搜索中：T=1(L=1,R=0) 区块删数 fastpass "
                            f"d={d} truth={tt}[{h}] found={info.get('found',0)} elapsed={info.get('elapsed_ms',0)}ms"
                        )
                        kind = "search"
                    elif phase == "fish_fast":
                        msg = (
                            f"搜索中：rank0 fish fastpass "
                            f"d={info.get('d','?')} truth={info.get('truth_type','?')} link={info.get('link_type','?')} "
                            f"n={info.get('n','?')} found={info.get('found',0)} elapsed={info.get('elapsed_ms',0)}ms"
                        )
                        kind = "search"
                    elif phase == "cell_fast":
                        msg = (
                            f"搜索中：cell-fast（跨区域 cell Truth） "
                            f"sub={info.get('subphase','?')} found={info.get('found',0)} "
                            f"T{info.get('min_t','?')}~{info.get('max_t','?')} R<={info.get('max_r','?')} "
                            f"truthI={info.get('truth_iters',0)} linkN={info.get('link_nodes',0)} elapsed={info.get('elapsed_ms',0)}ms"
                        )
                        kind = "search"
                    elif phase == "hc_fast":
                        msg = (
                            f"搜索中：house→cell fastpass "
                            f"d={info.get('d','?')} T={info.get('T','?')} opts={info.get('opts','?')} "
                            f"found={info.get('found',0)} elapsed={info.get('elapsed_ms',0)}ms"
                        )
                        kind = "search"
                    elif phase == "forcing":
                        stg = str(info.get("stage", ""))
                        idx = info.get("idx", None)
                        d = info.get("d", None)
                        if isinstance(idx, int) and isinstance(d, int):
                            r = idx // 9 + 1
                            c = idx % 9 + 1
                            rc = f"r{r}c{c}"
                        else:
                            rc = "r?c?"
                        if stg == "try":
                            msg = (
                                f"搜索中：forcing(短链) 试探 {info.get('i','?')}/{info.get('n','?')} "
                                f"assume {rc}={d if d is not None else '?'} elapsed={info.get('elapsed_ms',0)}ms"
                            )
                            kind = "search"
                        elif stg == "found":
                            msg = (
                                f"已找到：forcing(短链) {rc}={d if d is not None else '?'} 导致矛盾 ⇒ 可删 "
                                f"tested={info.get('tested','?')} elapsed={info.get('elapsed_ms',0)}ms"
                            )
                            kind = "found"
                        else:
                            msg = f"搜索中：forcing(短链) … elapsed={info.get('elapsed_ms',0)}ms"
                            kind = "search"
                    elif phase == "subset_scan":
                        msg = (
                            f"搜索中：SUBSET 子集扫描 "
                            f"house={info.get('house','?')} n={info.get('n','?')} elapsed={info.get('elapsed_ms',0)}ms"
                        )
                        kind = "search"
                    elif phase == "referee":
                        # referee 非常频繁：仅在“耗时明显/超时/否决”时显示，避免刷屏造成“卡住”的错觉
                        stage = str(info.get("stage", ""))
                        elapsed = int(info.get("elapsed_ms", 0) or 0)
                        result = info.get("result", None)
                        if stage == "start":
                            return
                        show = (elapsed >= 120) or (result is None) or (result is False)
                        if not show:
                            return
                        msg = (
                            f"校验中：referee "
                            f"elapsed={elapsed}ms nodes={info.get('nodes_used','?')} result={result}"
                        )
                        kind = "referee"
                    elif phase == "phase_policy":
                        msg = (
                            f"策略选择：order={info.get('order',[])} "
                            f"scores={info.get('scores',{})} "
                            f"rank_budget_ms={info.get('rank_budget_ms','?')} "
                            f"value={info.get('value',None)}"
                        )
                        kind = "search"
                    else:
                        msg = (
                            f"搜索中：rank r<=? T{p.get('min_t',1)}~{p.get('max_t',12)} "
                            f"phase={phase} found={info.get('found',0)} truthI={info.get('truth_iters',0)} linkN={info.get('link_nodes',0)} "
                            f"elapsed={info.get('elapsed_ms',0)}ms"
                        )
                        kind = "search"
                except Exception:
                    msg = "搜索中：rank …"
                    kind = "search"
                with _LOCK:
                    jj = _JOBS.get(jid)
                    if jj:
                        _maybe_set_message(jj, kind=kind, msg=msg)
                # 事件日志：记录搜索心跳（限频由 rank_engine 的 heartbeat_ms 控制）
                try:
                    append_event(
                        {
                            "type": "heartbeat",
                            "job_id": jid,
                            "puzzle": job.puzzle,
                            "phase": str(info.get("phase", "")),
                            "info": dict(info),
                            "message": str(msg),
                            "message_kind": str(kind),
                            "use_policy": bool(p.get("use_policy", False)),
                            "policy_ckpt": (policy_current_ckpt() if bool(p.get("use_policy", False)) else None),
                        }
                    )
                except Exception:
                    pass

            res: SolveResult = solve_with_rank(
                job.puzzle,
                max_steps=200000,
                min_t=int(p.get("min_t", 1)),
                max_t=int(p.get("max_t", 12)),
                max_r=int(p.get("max_r", 3)),
                max_structures_per_step=int(p.get("max_structures_per_step", 200)),
                truth_types=(p.get("truth_types") if isinstance(p.get("truth_types"), list) else None),
                enable_ur1=bool(p.get("enable_ur1", True)),
                use_policy=bool(p.get("use_policy", False)),
                on_emit=on_emit,
                rank_time_budget_ms=int(p.get("rank_time_budget_ms", 1200)),
                on_rank_heartbeat=on_rank_heartbeat,
            )
            job.attempts += 1

            # 性能/体验：题解已完成时，先把 solved 状态立刻暴露给前端（减少“上一题结束到下一题开始”的等待）
            # 后面的 replay/metrics/techlib 收尾允许在已 solved 状态下继续执行。
            if res.status == "solved":
                with _LOCK:
                    jj = _JOBS.get(jid)
                    if jj:
                        jj.status = "solved"
                        jj.steps = res.steps
                        jj.snapshots = res.snapshots
                        jj.last_progress_at_ms = _now_ms()
                        _maybe_set_message(jj, kind="done", msg="已完成：solved（收尾写入中…）")

            # 若发现 invalid（例如 proof 校验失败或删数导致无解），立刻停止任务并报告 error
            if res.status == "invalid":
                with _LOCK:
                    job.status = "error"
                    # 尽量把原因直接反馈给前端（不要只显示“暂无步骤”）
                    try:
                        last = res.steps[-1].rationale if res.steps else ""
                        job.error = last if last else "invalid"
                    except Exception:
                        job.error = "invalid"
                    # 不要清空/回退已有的 best-so-far
                    # - on_emit 可能已把前序步骤实时写入 job.steps
                    # - res.steps 可能因为异常/早停而更短
                    if res.steps and len(res.steps) >= len(job.steps):
                        job.steps = res.steps
                    if res.snapshots and len(res.snapshots) >= len(job.snapshots):
                        job.snapshots = res.snapshots
                    job.last_progress_at_ms = _now_ms()
                return

            # 后处理：对新增段写入 learn_params / metrics / techlib / replay（保证 reward/forced_chain 可用）
            new_steps = res.steps[old_len:]
            total_steps = len(res.steps)
            if new_steps:
                for k, s in enumerate(new_steps):
                    if job.stop_event.is_set():
                        with _LOCK:
                            job.status = "stopped"
                        return
                    counts = {"basic": 0, "rank": 0, "techlib": 0, "ur": 0}
                    meta = getattr(s, "meta", None) or {}
                    kind = meta.get("kind")
                    source = meta.get("source")
                    if kind == "RANK" and source == "techlib":
                        counts["techlib"] += 1
                    elif kind == "RANK":
                        counts["rank"] += 1
                    elif kind == "UR1":
                        counts["ur"] += 1
                    elif getattr(s, "action_type", "") == "commit":
                        counts["basic"] += 1
                    update_params(counts, solved=False, progressed=True)

                    # 用 callback 记录的时间来估算 stall
                    abs_step_index = old_len + k + 1
                    prev_ms = step_time_ms.get(abs_step_index - 1, int(job.last_progress_at_ms or job.created_at_ms))
                    cur_ms = step_time_ms.get(abs_step_index, prev_ms)
                    prev_progress_at_ms = int(prev_ms)
                    _now_for_reward = int(cur_ms)

                    try:
                        before_key = res.snapshots[abs_step_index - 1] if res.snapshots and (abs_step_index - 1) < len(res.snapshots) else ""
                        after_key = res.snapshots[abs_step_index] if res.snapshots and abs_step_index < len(res.snapshots) else before_key
                        meta2 = getattr(s, "meta", None) or {}
                        proof2 = getattr(s, "proof", None) or None
                        affected2 = [[int(a), (int(b) if b is not None else None)] for (a, b) in (getattr(s, "affected", []) or [])]

                        before_cnt = count_total_candidates(before_key) if before_key else 0
                        after_cnt = count_total_candidates(after_key) if after_key else before_cnt
                        cand_drop = max(0, int(before_cnt - after_cnt))

                        forced_chain = 0
                        try:
                            j = (old_len + k) + 1
                            while j < len(res.steps):
                                s2 = res.steps[j]
                                if getattr(s2, "action_type", "") != "commit":
                                    break
                                forced_chain += 1
                                j += 1
                        except Exception:
                            forced_chain = 0

                        dels_cnt = len([x for x in affected2 if x[1] is not None])
                        reward = 0.0
                        reward += 0.001 * float(cand_drop)
                        reward += 0.03 * float(forced_chain) if getattr(s, "action_type", "") == "eliminate" else 0.0
                        reward += 0.02 * float(dels_cnt)
                        reward += 0.05 if getattr(s, "action_type", "") == "commit" else 0.0

                        stall_ms = max(0, int(_now_for_reward - prev_progress_at_ms))
                        if stall_ms > 2000:
                            reward -= min(0.2, 0.00002 * float(stall_ms - 2000))

                        try:
                            kind2 = str(meta2.get("kind", ""))
                            sig = kind2
                            if kind2 == "RANK":
                                sig = f"RANK:T{meta2.get('T','?')}L{meta2.get('L','?')}R{meta2.get('R','?')}:{meta2.get('source','')}"
                            elif kind2 == "UR1":
                                sig = "UR1"
                            window = 80
                            abs_idx = old_len + k
                            start = max(0, abs_idx - window)
                            reps = 0
                            for prev in res.steps[start:abs_idx]:
                                pm = getattr(prev, "meta", None) or {}
                                pk = str(pm.get("kind", ""))
                                ps = pk
                                if pk == "RANK":
                                    ps = f"RANK:T{pm.get('T','?')}L{pm.get('L','?')}R{pm.get('R','?')}:{pm.get('source','')}"
                                elif pk == "UR1":
                                    ps = "UR1"
                                if ps == sig:
                                    reps += 1
                            if reps >= 2:
                                reward -= 0.06 * float(reps - 1)
                        except Exception:
                            pass

                        try:
                            ref = (proof2 or {}).get("referee") if isinstance(proof2, dict) else None
                            if isinstance(ref, dict) and ref.get("has_any_solution") is None:
                                reward -= 0.15
                        except Exception:
                            pass

                        is_last = (old_len + k + 1) == total_steps
                        terminal = (res.status in ("solved", "invalid")) and is_last
                        if terminal and res.status == "solved":
                            reward += 1.0
                        if terminal and res.status == "invalid":
                            reward -= 1.0

                        on_policy = bool(p.get("use_policy", False))
                        append_transition(
                            {
                                "puzzle": job.puzzle,
                                "job_id": jid,
                                "step_index": abs_step_index,
                                "before_key": before_key,
                                "after_key": after_key,
                                "action_type": str(getattr(s, "action_type", "")),
                                "affected": affected2,
                                "meta": meta2,
                                "proof": proof2,
                                "reward": float(reward),
                                "done": bool(terminal),
                                "terminal_status": (res.status if terminal else None),
                                "on_policy": on_policy,
                                "policy_ckpt": (policy_current_ckpt() if on_policy else None),
                                "cand_before": int(before_cnt),
                                "cand_after": int(after_cnt),
                                "cand_drop": int(cand_drop),
                                "forced_chain": int(forced_chain),
                            }
                        )
                    except Exception:
                        pass

                    try:
                        meta3 = getattr(s, "meta", None) or {}
                        record_step_event(
                            kind=str(meta3.get("kind", "")),
                            source=(meta3.get("source") if meta3.get("source") else None),
                            action_type=str(getattr(s, "action_type", "")),
                            deletions_count=len([x for x in getattr(s, "affected", []) if x and x[1] is not None]),
                            progressed=True,
                            at_ms=_now_ms(),
                        )
                    except Exception:
                        pass

                try:
                    techlib_record_steps(job.puzzle, res.snapshots, res.steps, start_idx=old_len)
                except Exception:
                    pass

            # 关键修复：不允许回退
            # - solve_with_rank 每轮都可能走不同路径，导致 steps 更短/不同
            # - 我们只在“更长”时更新 best-so-far，避免前端看到进度回滚
            with _LOCK:
                cur_len = len(job.steps)
                if len(res.steps) > cur_len:
                    job.steps = res.steps
                    job.snapshots = res.snapshots
                    job.last_progress_at_ms = _now_ms()

            # 如果 solve_with_rank 直接 solved，但 steps 没增长（少见），仍同步快照
            with _LOCK:
                if res.snapshots and len(res.snapshots) > len(job.snapshots):
                    job.snapshots = res.snapshots

            if res.status == "solved":
                update_params({"basic": 0, "rank": 0, "techlib": 0, "ur": 0}, solved=True, progressed=bool(new_steps))
                # 状态已提前设置为 solved，这里仅结束线程
                return

            # stuck：不结束，扩展参数继续探索
            with _LOCK:
                mst = int(job.params.get("max_structures_per_step", 200))
                if mst < 50000:
                    job.params["max_structures_per_step"] = min(50000, max(400, mst * 2))

            time.sleep(0.2)
        except Exception as e:
            with _LOCK:
                job.status = "error"
                job.error = str(e)
            return

